#!/usr/bin/env bash
# Publish one release of the mushaf page SVG to cdn.quran.ws/svg/pages/.
#
#   scripts/publish-cdn.sh v1.1.1               # download the release, stage, upload
#   scripts/publish-cdn.sh v1.1.1 --stage-only  # build the tree and the manifest, upload nothing
#
# One object per page, because a reader wants one page and not a 121 MB archive:
#
#   svg/pages/v1.1.1/hafs-kfqc/001.svg     the artwork
#   svg/pages/v1.1.1/hafs-kfqc/001.json    the ayah polygons for that page
#
# Every mushaf the release carries is published, one folder per edition. A page that holds
# two surahs also has a per-surah file beside it, and those travel with it.
#
# The artwork comes from the release zips, which are the canonical artefact. The polygon
# layer is not in them, so it is read from the working tree; the workflow checks out only
# those directories.
#
# Only the raw `svg` set is published. The repository also ships `svg-br`, but a Compression
# Rule on cdn.quran.ws negotiates zstd, brotli or gzip per client, so a second pre-compressed
# copy would double the object count and serve no client that the edge does not already.
#
# Needs: curl (>= 7.75, for --aws-sigv4), unzip, sha256sum/shasum, jq, gh.
# Credentials: see scripts/cdn-put.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/cdn-put.sh

VERSION="${1:?usage: publish-cdn.sh <tag> [--stage-only]}"; shift
STAGE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --stage-only) STAGE_ONLY=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

FAMILY=svg/pages
PREFIX="$FAMILY/$(cdn_version "$VERSION")"
STAGE="dist/cdn/$VERSION"
SRC="$STAGE/src"

# Every mushaf in the release is published. The list comes from the release itself rather
# than from a constant here, so another riwayah or another print is carried the moment it
# ships, with no edit to this script. Set EDITIONS to publish a subset while testing.
EDITIONS="${EDITIONS:-$(gh release view "$VERSION" --repo quran-ws/quran-svg --json assets \
  --jq '.assets[] | select(.name | endswith("-svg.zip")) | .name | rtrimstr("-svg.zip")')}"
[ -n "$EDITIONS" ] || { echo "$VERSION publishes no *-svg.zip asset" >&2; exit 1; }
echo "== $VERSION: $(echo "$EDITIONS" | wc -w | tr -d ' ') mushafs — $(echo $EDITIONS)"

echo "== fetching $VERSION"
rm -rf "$STAGE" && mkdir -p "$SRC"
for edition in $EDITIONS; do
  # `hafs-kfqc` is riwayah `hafs`, print `kfqc`; the polygon layer sits under both.
  riwayah="${edition%-*}"; print="${edition##*-}"
  zip="$STAGE/$edition-svg.zip"
  gh release download "$VERSION" --repo quran-ws/quran-svg --clobber -D "$STAGE" -p "$edition-svg.zip"
  mkdir -p "$SRC/$edition"
  # The zip's internal layout is not part of the contract, so take the pages by name wherever
  # they sit inside it and flatten them under the edition. Flattening would silently drop a
  # page if two directories in the zip held the same basename, so count both sides.
  want=$(unzip -Z1 "$zip" '*.svg' | wc -l | tr -d ' ')
  unzip -q -j -o "$zip" '*.svg' -d "$SRC/$edition"
  got=$(find "$SRC/$edition" -name '*.svg' | wc -l | tr -d ' ')
  [ "$want" = "$got" ] || { echo "$edition: zip holds $want pages but $got survived flattening" >&2; exit 1; }
  rm -f "$zip"
  [ -f "$SRC/$edition/001.svg" ] || { echo "$edition: the release zip had no 001.svg" >&2; exit 1; }

  # The polygon layer travels with the artwork: a page without it cannot highlight an ayah.
  poly="mushafs/$riwayah/$print/json"
  [ -d "$poly" ] || { echo "$edition: $poly is missing — check out the polygon layer" >&2; exit 1; }
  cp "$poly"/*.json "$SRC/$edition/"
  echo "   $edition: $(ls "$SRC/$edition"/*.svg | wc -l | tr -d ' ') pages, $(ls "$SRC/$edition"/*.json | wc -l | tr -d ' ') polygon files"
done

echo "== staging $PREFIX"
( cd "$SRC" && find . -type f ! -name '.*' | sed 's|^\./||' | sort ) > "$STAGE/.files"
: > "$STAGE/.files.tsv"
while IFS= read -r f; do
  printf '%s\t%s\t%s\n' "$f" "$(wc -c < "$SRC/$f" | tr -d ' ')" "$(sha256 "$SRC/$f")" >> "$STAGE/.files.tsv"
done < "$STAGE/.files"

jq -n --arg version "$(cdn_version "$VERSION")" --arg base "https://$CDN_HOST/$PREFIX/" \
      --arg release "$VERSION" --arg editions "$EDITIONS" \
      --rawfile tsv "$STAGE/.files.tsv" '
  {version: $version, release: $release, base: $base, encoding: "identity",
   editions: ($editions | rtrimstr("\n") | split("\n")),
   files: ($tsv | rtrimstr("\n") | split("\n") | map(split("\t") |
     {name: .[0], bytes: (.[1]|tonumber), sha256: .[2]}))}
' > "$STAGE/manifest.json"
echo "   $(wc -l < "$STAGE/.files" | tr -d ' ') objects + manifest, $(du -sh "$SRC" | cut -f1) raw"

[ "$STAGE_ONLY" = 1 ] && { echo "== staged only: $STAGE"; exit 0; }

cdn_init
cdn_guard "$PREFIX" || exit 1

echo "== uploading to r2://$BUCKET/$PREFIX"
export PREFIX SRC
xargs -P 16 -I{} bash -c 'cdn_put "$PREFIX/{}" "$SRC/{}"' < "$STAGE/.files"
cdn_put "$PREFIX/manifest.json" "$STAGE/manifest.json" "public, max-age=300"
cdn_latest "$FAMILY" "$(cdn_version "$VERSION")"

echo "== published https://$CDN_HOST/$PREFIX/manifest.json"

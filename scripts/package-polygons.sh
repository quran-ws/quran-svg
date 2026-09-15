#!/usr/bin/env bash
# Package the ayah polygon layer of every mushaf as a release archive.
#
#   scripts/package-polygons.sh v1.1.1           # from the working tree
#   scripts/package-polygons.sh v1.1.1 --from-tag  # from the tag, ignoring the working tree
#
# The artwork has shipped as `<edition>-svg.zip` since the first release; the polygons did
# not, because at 3.7 MB against 414 MB per mushaf they are cheap to take from git. That
# left the release incomplete: a page without its polygons cannot highlight an ayah, and a
# mirror of the release could not carry the whole product. One archive per mushaf, named to
# match the artwork beside it.
#
# Needs: zip, sha256sum/shasum, git for --from-tag.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: package-polygons.sh <version> [--from-tag]}"; shift
FROM_TAG=0
for arg in "$@"; do
  case "$arg" in
    --from-tag) FROM_TAG=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

OUT=dist/release
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

rm -rf "$OUT" && mkdir -p "$OUT"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

# Read the tree from the tag rather than the checkout, so an archive can be cut for a
# release that is already out without disturbing whatever the working tree is holding.
if [ "$FROM_TAG" = 1 ]; then
  git rev-parse --verify "$VERSION^{commit}" >/dev/null 2>&1 \
    || { echo "no such tag: $VERSION — fetch it first" >&2; exit 1; }
  git archive "$VERSION" mushafs | tar -x -C "$WORK"
  ROOT="$WORK"
else
  ROOT=.
fi

found=0
for poly in "$ROOT"/mushafs/*/*/json; do
  [ -d "$poly" ] || continue
  edition="$(basename "$(dirname "$(dirname "$poly")")")-$(basename "$(dirname "$poly")")"
  zip="$PWD/$OUT/$edition-json.zip"
  # -X drops the extra timestamps and uid/gid that would make two builds of the same tree
  # differ byte for byte.
  ( cd "$poly" && zip -q -X -r "$zip" . -i '*.json' )
  printf '%s  %s\n' "$(sha256 "$zip")" "$edition-json.zip" > "$zip.sha256"
  echo "   $edition-json.zip  $(ls "$poly" | wc -l | tr -d ' ') files, $(du -h "$zip" | cut -f1)"
  found=$((found + 1))
done
[ "$found" -gt 0 ] || { echo "no mushafs/*/*/json found" >&2; exit 1; }
echo "== $found archives in $OUT"

#!/usr/bin/env bash
# Upload objects to cdn.quran.ws (Cloudflare R2). Sourced by the publishers, not run.
#
# One host carries every published artefact of the stack, each family in its own folder and
# each folder on its own version line:
#
#   qvp/v0.3.0/            page data from this repo
#   svg/pages/v1.2.0/      full-page mushaf SVG, from quran-svg
#   svg/elements/v0.4.0/   element SVG and index, from quran-svg-elements
#   engine/wasm/v0.2.1/    the engine builds
#
# A version folder is written once and served forever, so objects go up with
# `Cache-Control: immutable` and nothing overwrites them. Two objects are the exception:
# `manifest.json` inside a folder, and `latest.json` beside them. Both are entry points, and
# an entry point cached for a year is a footgun — a mistake in one is unreachable without a
# cache purge. Five minutes costs one request per POP per five minutes and keeps it fixable.
#
# Needs: curl (>= 7.75, for --aws-sigv4), jq, sha256sum/shasum.
# Credentials come from the environment: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, and optionally R2_BUCKET (default: cdn-quran-ws).

CDN_HOST="${CDN_HOST:-cdn.quran.ws}"
BUCKET="${R2_BUCKET:-cdn-quran-ws}"

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# The tag names a release; the URL names a version. `data-v0.3.0` and `v0.3.0` are the same
# page data, and the folder holding it should not record which repo convention produced it.
cdn_version() { echo "${1#data-}"; }

cdn_init() {
  : "${R2_ACCOUNT_ID:?}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}"
  ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
  export ENDPOINT BUCKET CDN_HOST R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY
}

# cdn_put <key> <file> [cache-control]
# The key is the full path under the bucket, so a caller can write both inside a version
# folder and beside it.
cdn_put() {
  local key="$1" file="$2" cache="${3:-public, max-age=31536000, immutable}" type code
  case "$key" in
    *.json) type=application/json ;;
    *.md)   type=text/markdown ;;
    *.svg)  type=image/svg+xml ;;
    *.wasm) type=application/wasm ;;
    *)      type=application/octet-stream ;;
  esac
  code=$(curl -sS -o /dev/null -w '%{http_code}' -X PUT \
    --aws-sigv4 "aws:amz:auto:s3" --user "$R2_ACCESS_KEY_ID:$R2_SECRET_ACCESS_KEY" \
    -H "Content-Type: $type" -H "Cache-Control: $cache" \
    --data-binary "@$file" "$ENDPOINT/$BUCKET/$key")
  [ "$code" = 200 ] || { echo "PUT $key failed: HTTP $code" >&2; return 1; }
}
export -f cdn_put

# cdn_exists <key> — true when the object is already published.
cdn_exists() {
  [ "$(curl -sS -o /dev/null -w '%{http_code}' -I \
       --aws-sigv4 "aws:amz:auto:s3" --user "$R2_ACCESS_KEY_ID:$R2_SECRET_ACCESS_KEY" \
       "$ENDPOINT/$BUCKET/$1")" = 200 ]
}

# cdn_guard <folder> — refuse to rewrite a version that is already published.
cdn_guard() {
  if cdn_exists "$1/manifest.json"; then
    echo "$1 is already published — versions are immutable; cut a new one" >&2
    return 1
  fi
}

# cdn_latest <family> <version> — point the family at this version.
# It only moves forward: republishing an older version must not demote the pointer, or a
# rebuild of last year's release would send every consumer back to it.
#
# The current value is read through the S3 API, not over https://$CDN_HOST. Reading the
# public URL of an object that does not exist yet leaves a cached 404 at every POP the probe
# touched, and the write that follows cannot clear it.
cdn_latest() {
  local family="$1" version="$2" tmp have
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' RETURN
  if curl -fsS --aws-sigv4 "aws:amz:auto:s3" \
       --user "$R2_ACCESS_KEY_ID:$R2_SECRET_ACCESS_KEY" \
       "$ENDPOINT/$BUCKET/$family/latest.json" -o "$tmp/have.json" 2>/dev/null; then
    have=$(jq -r '.version // empty' "$tmp/have.json")
    if [ -n "$have" ] && [ "$have" != "$version" ] &&
       [ "$(printf '%s\n%s\n' "${have#v}" "${version#v}" | sort -V | tail -1)" = "${have#v}" ]; then
      echo "   latest stays $have ($version is older)"
      return 0
    fi
  fi
  jq -n --arg v "$version" --arg m "https://$CDN_HOST/$family/$version/manifest.json" \
        --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{version: $v, manifest: $m, updated: $t}' > "$tmp/latest.json"
  cdn_put "$family/latest.json" "$tmp/latest.json" "public, max-age=300"
  echo "   latest -> $version"
}

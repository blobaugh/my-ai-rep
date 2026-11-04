#!/bin/sh
# Assert a built image is safe to deploy: linux/amd64, non-root (optional override),
# and no private paths or secret filenames baked in.
set -eu

usage() {
  echo "usage: scripts/verify_image.sh [--allow-root] IMAGE" >&2
  exit 2
}

allow_root=0
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-root)
      allow_root=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage
      ;;
    *)
      break
      ;;
  esac
done

if [ $# -ne 1 ]; then
  usage
fi

image=$1

if ! command -v docker >/dev/null 2>&1; then
  echo "verify_image: docker not found" >&2
  exit 1
fi

arch=$(docker image inspect -f '{{.Architecture}}' "$image")
if [ "$arch" != "amd64" ]; then
  echo "verify_image: expected linux/amd64, got architecture=$arch for $image" >&2
  exit 1
fi

uid=$(docker run --rm --entrypoint sh "$image" -c 'id -u' 2>/dev/null || true)
if [ -z "$uid" ]; then
  echo "verify_image: could not read user id in $image" >&2
  exit 1
fi
if [ "$uid" = "0" ] && [ "$allow_root" -eq 0 ]; then
  echo "verify_image: container runs as root (uid 0): $image" >&2
  exit 1
fi

# Paths that must not exist; filenames that must not appear under searchable trees.
scan_script='
set -eu
fail=0
for path in /app/content /content /app/data /data /app/.env /.env; do
  if [ -e "$path" ]; then
    echo "forbidden path: $path" >&2
    fail=1
  fi
done
search_roots="/app /usr/share/nginx/html /opt/ollama-seed"
for root in $search_roots; do
  [ -d "$root" ] || continue
  if find "$root" \( -name "qa*.md" -o -name ".env" -o -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" \) -print 2>/dev/null | grep -q .; then
    find "$root" \( -name "qa*.md" -o -name ".env" -o -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" \) -print 2>/dev/null >&2
    fail=1
  fi
done
exit "$fail"
'

if ! docker run --rm --entrypoint sh "$image" -c "$scan_script"; then
  echo "verify_image: private content check failed for $image" >&2
  exit 1
fi

echo "verify_image: ok ($image arch=$arch uid=$uid)"
exit 0

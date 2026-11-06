#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$root"

: "${IMAGE_API:?set IMAGE_API}"
: "${IMAGE_WEB:?set IMAGE_WEB}"
: "${IMAGE_EMBEDDER:?set IMAGE_EMBEDDER}"
: "${IMAGE_BACKUP:?set IMAGE_BACKUP}"

./scripts/verify_image.sh "$IMAGE_API"
./scripts/verify_image.sh "$IMAGE_WEB"
# Upstream Ollama image runs as root; models live under /root/.ollama (see docs/history/deploy-ci-operator.md).
./scripts/verify_image.sh --allow-root "$IMAGE_EMBEDDER"
./scripts/verify_image.sh "$IMAGE_BACKUP"

if command -v trivy >/dev/null 2>&1; then
  for img in "$IMAGE_API" "$IMAGE_WEB" "$IMAGE_EMBEDDER" "$IMAGE_BACKUP"; do
    echo "== trivy (warn only) $img =="
    trivy image --exit-code 0 --severity HIGH,CRITICAL "$img" || true
  done
else
  echo "verify_images: trivy not installed (optional)"
fi

echo "verify_images: ok"

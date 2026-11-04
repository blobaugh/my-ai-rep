#!/bin/sh
# Build linux/amd64 images locally or in GitLab CI. Tags are passed in IMAGE_* vars.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$root"

platform=${BENBOT_BUILD_PLATFORM:-linux/amd64}

build_one() {
  dockerfile=$1
  tag=$2
  echo "== build $tag ($platform) =="
  docker buildx build --platform "$platform" -f "$dockerfile" -t "$tag" --load "$root"
}

: "${IMAGE_API:?set IMAGE_API}"
: "${IMAGE_WEB:?set IMAGE_WEB}"
: "${IMAGE_EMBEDDER:?set IMAGE_EMBEDDER}"
: "${IMAGE_BACKUP:?set IMAGE_BACKUP}"

build_one docker/api/Dockerfile "$IMAGE_API"
build_one docker/web/Dockerfile "$IMAGE_WEB"
build_one docker/embedder/Dockerfile "$IMAGE_EMBEDDER"
build_one docker/backup/Dockerfile "$IMAGE_BACKUP"

echo "build_images: ok"

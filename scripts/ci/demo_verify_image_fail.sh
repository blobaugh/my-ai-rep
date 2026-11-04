#!/bin/sh
# Prove verify_image.sh fails when private content is baked into an image.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$root"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/Dockerfile" <<'EOF'
FROM python:3.9-slim-bookworm
RUN useradd --create-home --uid 10001 app
WORKDIR /app
RUN mkdir -p /app/content && echo leak > /app/content/qa-demo.md
USER app
EOF

bad=benbot/verify-demo-bad:local
docker build --platform linux/amd64 -f "$tmp/Dockerfile" -t "$bad" "$tmp"

if ./scripts/verify_image.sh "$bad"; then
  echo "demo_verify_image_fail: expected verify_image to fail" >&2
  exit 1
fi

echo "demo_verify_image_fail: verify_image correctly rejected bad image"

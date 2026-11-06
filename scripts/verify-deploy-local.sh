#!/bin/sh
# Dev-stack checks aligned with docs/history/deploy-verify-operator.md (localhost, not production).
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
export BENBOT_HOME="${BENBOT_HOME:-$root}"

base_web="${BENBOT_VERIFY_WEB:-http://127.0.0.1:8080}"
base_api="${BENBOT_VERIFY_API:-http://127.0.0.1:8000}"

echo "== web headers =="
curl -fsSI "$base_web/" | head -20

echo "== api health =="
curl -fsS "$base_api/api/health"
echo

echo "== embed CSP frame-ancestors =="
curl -fsSI "$base_web/embed" | grep -i content-security-policy || true

echo "== embedder not published =="
if docker port benbot_embedder 2>/dev/null | grep -q .; then
  echo "embedder has published ports" >&2
  exit 1
fi
echo "ok (no host ports)"

echo "verify-deploy-local: ok"

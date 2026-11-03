#!/bin/sh
# Run on a machine with Docker. Exercises BENBOT-24 acceptance checks.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

export BENBOT_HOME="${BENBOT_HOME:-$root}"

echo "== compose config (prod) =="
docker compose -f docker-compose.yml config >/dev/null
echo "ok"

echo "== compose config (dev merge) =="
docker compose -f docker-compose.yml -f docker-compose.dev.yml config >/dev/null
echo "ok"

echo "== build and start dev stack =="
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
trap 'docker compose -f docker-compose.yml -f docker-compose.dev.yml down' EXIT

echo "== wait for health =="
tries=0
while [ "$tries" -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null \
    && curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null; then
    break
  fi
  tries=$((tries + 1))
  sleep 5
done
curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null

echo "== embedder must not publish host ports =="
if docker port benbot_embedder 2>/dev/null | grep -q .; then
  echo "embedder published a port" >&2
  exit 1
fi

echo "== api reaches embedder =="
docker exec benbot_api python -c "
from openai import OpenAI
c = OpenAI(base_url='http://embedder:11434/v1', api_key='x')
r = c.embeddings.create(model='nomic-embed-text', input='ping')
assert r.data[0].embedding
print('embed ok')
"

echo "== api image has no private content =="
docker run --rm benbot/api:dev sh -c 'test ! -e /app/content && test ! -e /app/.env'

echo "verify-docker: ok"

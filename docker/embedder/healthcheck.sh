#!/bin/sh
set -eu

model="${EMBED_MODEL:-nomic-embed-text}"
if [ -z "$model" ]; then
  model=nomic-embed-text
fi

curl -fsS "http://127.0.0.1:11434/v1/embeddings" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"${model}\",\"input\":\"health\"}" >/dev/null

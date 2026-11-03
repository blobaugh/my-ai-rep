#!/bin/sh
set -eu

MODEL="${EMBED_MODEL:-nomic-embed-text}"
curl -fsS "http://127.0.0.1:11434/v1/embeddings" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"input\":\"health\"}" >/dev/null

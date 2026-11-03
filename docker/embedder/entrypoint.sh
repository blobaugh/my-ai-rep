#!/bin/sh
set -eu

MODEL="${EMBED_MODEL:-nomic-embed-text}"

start_server() {
  ollama serve &
  echo $!
}

wait_ready() {
  i=0
  while [ "$i" -lt 120 ]; do
    if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "ollama did not become ready" >&2
  return 1
}

if ! ollama list 2>/dev/null | grep -Fq "$MODEL"; then
  pid=$(start_server)
  wait_ready
  ollama pull "$MODEL"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
fi

exec ollama serve

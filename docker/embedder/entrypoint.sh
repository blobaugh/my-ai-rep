#!/bin/sh
set -eu

model="${EMBED_MODEL:-nomic-embed-text}"
if [ -z "$model" ]; then
  model=nomic-embed-text
fi

seed_dir="/opt/ollama-seed"
live_dir="/root/.ollama"

if [ ! -d "$live_dir/models" ] || [ -z "$(ls -A "$live_dir/models" 2>/dev/null)" ]; then
  if [ -d "$seed_dir/models" ]; then
    mkdir -p "$live_dir"
    cp -a "$seed_dir/." "$live_dir/"
  fi
fi

exec ollama serve

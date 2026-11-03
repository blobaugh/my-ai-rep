#!/bin/sh
# Start the dev stack from any checkout directory name.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not on PATH" >&2
  exit 1
fi

export BENBOT_HOME="${BENBOT_HOME:-$root}"

exec docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build "$@"

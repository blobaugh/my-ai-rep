#!/usr/bin/env bash
# Restore one Spaces/MinIO backup object into the live data volume.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <object-key> [target-sqlite-path]" >&2
  echo "example: $0 dev/hourly/benbot-20261103T120000Z.db.gz" >&2
  exit 1
fi

KEY="$1"
TARGET="${2:-/app/data/benbot.sqlite}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml)
if [[ ! -f docker-compose.dev.yml ]] || [[ "${BENBOT_RESTORE_PROD:-0}" == "1" ]]; then
  COMPOSE=(docker compose)
fi

echo "Stopping api so the database is not written during restore..."
"${COMPOSE[@]}" stop api 2>/dev/null || true

"${COMPOSE[@]}" run --rm backup restore "$KEY" "$TARGET"

echo "Starting api..."
"${COMPOSE[@]}" start api 2>/dev/null || "${COMPOSE[@]}" up -d api

echo "Restore finished. Check /api/health and the session log."

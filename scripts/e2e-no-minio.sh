#!/bin/sh
# Like e2e.sh but skips minio/backup when quay.io pull fails (common in CI/agents).
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
if [ -f "$root/.venv/bin/python" ]; then
  PATH="$root/.venv/bin:$PATH"
  export PATH
fi
export BENBOT_HOME="${BENBOT_HOME:-$root}"
export RUN_E2E=1
export E2E_IDLE_WAIT_SEC="${E2E_IDLE_WAIT_SEC:-70}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml)

report_dir="$root/data/e2e"
mkdir -p "$report_dir"
report_md="$report_dir/results.md"
log="$report_dir/run.log"
status_file="$report_dir/pytest.exit"

cleanup() {
  if [ "${E2E_LEAVE_UP:-0}" != "1" ]; then
    "${COMPOSE[@]}" stop api web embedder 2>/dev/null || true
  fi
}
trap cleanup EXIT

: >"$log"

run() {
  echo "$@"
  "$@" >>"$log" 2>&1
}

{
  echo "== e2e (no minio): build api web embedder =="
  "${COMPOSE[@]}" up --build -d api web embedder

  echo "== e2e: wait for health =="
  tries=0
  while [ "$tries" -lt 90 ]; do
    if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null \
      && curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null; then
      break
    fi
    tries=$((tries + 1))
    sleep 5
  done
  curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null

  echo "== e2e: ingest =="
  # Avoid cross-device rename when container /tmp and /app/data are different mounts.
  "${COMPOSE[@]}" exec -T api sh -c 'mkdir -p /app/data/tmp && TMPDIR=/app/data/tmp python -m src.ingest'

  echo "== e2e: pytest =="
  set +e
  python -m pytest tests/e2e -m e2e --tb=short -q
  pytest_status=$?
  set -e
  echo "$pytest_status" >"$status_file"

  {
    echo "# E2E results ($(date -u +%Y-%m-%dT%H:%MZ))"
    echo
    echo "| Item | Value |"
    echo "| --- | --- |"
    echo "| pytest exit | $pytest_status |"
    echo "| note | minio/backup skipped (quay pull); backup e2e use E2E_BACKUP=1 elsewhere |"
    echo "| log | data/e2e/run.log |"
  } >"$report_md"

  echo "E2E_EXIT=$pytest_status"
} 2>&1 | tee -a "$log"

exit "$(cat "$status_file" 2>/dev/null || echo 1)"

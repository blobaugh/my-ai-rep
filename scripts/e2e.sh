#!/bin/sh
# End-to-end suite (BENBOT-32): dev compose up, pytest tests/e2e, report, tear down.
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

cleanup() {
  if [ "${E2E_LEAVE_UP:-0}" != "1" ]; then
    "${COMPOSE[@]}" down
  fi
}
trap cleanup EXIT

echo "== e2e: build and start stack =="
"${COMPOSE[@]}" up --build -d

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

echo "== e2e: ingest (examples) =="
# /tmp vs mounted data/ may be different devices in Docker Desktop.
"${COMPOSE[@]}" exec -T api sh -c 'mkdir -p /app/data/tmp && TMPDIR=/app/data/tmp python -m src.ingest' \
  || "${COMPOSE[@]}" --profile tools run --rm ingest

echo "== e2e: pytest =="
set +e
python -m pytest tests/e2e -m "e2e and not e2e_failover and not e2e_browser" \
  --tb=short -q >"$report_dir/pytest.log" 2>&1
pytest_status=$?
set -e
cat "$report_dir/pytest.log"

{
  echo "# E2E results ($(date -u +%Y-%m-%dT%H:%MZ))"
  echo
  echo "| Item | Value |"
  echo "| --- | --- |"
  echo "| pytest exit | $pytest_status |"
  echo "| log | data/e2e/pytest.log |"
  echo "| timing | data/e2e/timing_http.json (if equivalence ran) |"
  echo
  echo "See docs/web/e2e.md for optional browser and failover groups."
} >"$report_md"

echo "wrote $report_md"
exit "$pytest_status"

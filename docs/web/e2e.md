# End-to-end tests (dev Docker stack)

BENBOT-32 exercises BenBot the way visitors do: **HTTP** through the dev web port
(`127.0.0.1:8080`) and optional **Playwright** UI checks. Tests live in
`tests/e2e/` and are **skipped by default** unless `RUN_E2E=1`.

## One command

```bash
./scripts/e2e.sh
```

This merges `docker-compose.yml`, `docker-compose.dev.yml`, and
`docker-compose.e2e.yml` (shorter session/limit settings), builds images, runs
ingest on `examples/`, runs `pytest tests/e2e`, writes `data/e2e/results.md`,
and tears the stack down. Set `E2E_LEAVE_UP=1` to keep containers running after
a failure.

### Prerequisites

- Docker with compose v2
- **Ollama on the host** (dev compose uses `host.docker.internal:11434`) **or**
  working `LLM_SECONDARY_*` in `.env` for failover-only paths
- Python dev deps: `pip install -e ".[dev,e2e]"`

## Run subsets manually

```bash
export RUN_E2E=1
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml up -d
docker compose --profile tools run --rm ingest

# No LLM (health, headers, embedder port, verify_image)
python -m pytest tests/e2e/test_stack_security.py tests/e2e/test_privacy.py -q

# LLM scenarios
python -m pytest tests/e2e -m "e2e and e2e_llm" -q

# Playwright (install browsers once: playwright install chromium)
python -m pytest tests/e2e/test_ui_browser.py -q
```

## Optional scenarios

| Flag / compose | Scenario |
| --- | --- |
| `docker-compose.e2e.yml` (default in `e2e.sh`) | Session cap, idle timeout, concurrency busy |
| `E2E_FAILOVER=1` + `docker-compose.e2e-failover.yml` | Dead primary, live secondary |
| `E2E_BACKUP=1` | MinIO backup while chatting (slow) |
| Manual | Stop embedder / both LLMs for unavailable UI |

Tests that are not automated document **`pytest.skip("could not test because …")`**
in the module — see `test_failover_embedder.py`, `test_backup_restore.py`,
`test_ui_browser.py`.

## Reports

- **`data/e2e/results.md`** — summary table from `e2e.sh`
- **`data/e2e/timing_http.json`** — per-question HTTP timings (spec §17 equivalence)
- **`data/e2e/pytest.log`** — full pytest output
- Screenshots: **`docs/web/screenshots/e2e/`** when Playwright tests run

## Non-e2e CI

Default `pytest` **does not** run e2e tests (they skip without `RUN_E2E=1`).
GitLab CI (`scripts/ci/test.sh`) runs unit tests only.

## Defects

This suite does **not** change product code. Failures become new FeedPebble issues.
Compare HTTP vs CLI equivalence failures carefully — both paths must share the
same `data/` index and model settings.

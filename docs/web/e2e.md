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
ingest on `examples/`, runs `pytest tests/e2e -m "e2e and not e2e_failover and not e2e_browser"`,
writes `data/e2e/results.md`, and tears the stack down. Set `E2E_LEAVE_UP=1` to
keep containers running after a failure.

The default pytest selection includes **HTTP**, **limits**, **privacy**,
**review**, **ingest**, **injection**, **equivalence**, and **MinIO backup**
(`test_backup_restore.py`). It does **not** include failover or Playwright (see
below).

### Prerequisites

- Docker with compose v2
- **Ollama on the host** (dev compose uses `host.docker.internal:11434`) **or**
  working `LLM_SECONDARY_*` in `.env` for chat and backup tests
- Python dev deps: `pip install -e ".[dev,e2e]"` (e2e extra only for Playwright)

## Run subsets manually

```bash
export RUN_E2E=1
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml up -d
docker compose --profile tools run --rm ingest

# Default e2e.sh selection (no browser, no failover)
python -m pytest tests/e2e -m "e2e and not e2e_failover and not e2e_browser" -q

# No LLM (health, headers, embedder port, verify_image)
python -m pytest tests/e2e/test_stack_security.py tests/e2e/test_privacy.py -q

# LLM scenarios only
python -m pytest tests/e2e -m "e2e and e2e_llm" -q

# Playwright (install browsers once: playwright install chromium)
python -m pytest tests/e2e/test_ui_browser.py -q
```

## Optional scenarios

| Flag / compose | Scenario |
| --- | --- |
| `docker-compose.e2e.yml` (default in `e2e.sh`) | Session cap, idle timeout, concurrency busy |
| `E2E_FAILOVER=1` + `docker-compose.e2e-failover.yml` | Dead primary, live secondary; `test_failover_embedder.py` |
| `web/dev/widget-e2e.html` | Same-origin widget host page for Playwright |

**Manual only (no automated test):** stop **both** LLM connections or stop the
embedder mid-suite — those disrupt the shared stack for other tests. Use
`docs/deploy/verify.md` step 8 for production failover instead.

### Failover pytest

```bash
export RUN_E2E=1 E2E_FAILOVER=1
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  -f docker-compose.e2e.yml -f docker-compose.e2e-failover.yml up -d
# ingest as usual
python -m pytest tests/e2e/test_failover_embedder.py -q
```

Expect a successful chat via secondary and at least one row from
`python -m src.review failovers --since 24h` inside the api container.

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
**Exit code:** `scripts/e2e.sh` writes pytest output to `data/e2e/pytest.log` and
uses pytest’s real exit status in `data/e2e/results.md` (not masked by `tee`).

**HTTP vs CLI byte equality:** live Ollama/OpenRouter text varies between calls
even at temperature 0. Exact `answer_turn` vs API parity is covered by
`RUN_INTEGRATION=1` → `tests/test_api_live.py`. E2E checks nginx `/api` routing
(deterministic validation errors), spec §17 questions over HTTP, and CLI smoke.

Compare failures carefully — both paths must share the same `data/` index and
model settings.

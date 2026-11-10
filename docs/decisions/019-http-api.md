# One HTTP API over the existing answer pipeline

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-21

## Decision

The visitor API is FastAPI 0.115.14 on Starlette 0.46.2, served by uvicorn 0.32.1. Those releases install and import on the checkout's Python 3.9.6. Newer FastAPI releases were not required. There is no second framework.

`python -m src.api` starts **one** worker on `127.0.0.1:8000`. Failover state lives in that process. A second worker would not know the first had failed over. The UTC daily message cap is persisted in SQLite (BENBOT-28); concurrency slots are in-process only.

Every route is declared under `/api` in the app. The proxy forwards the prefix and does not rewrite it.

`answer_turn` blocks. The chat route calls it with Starlette's `run_in_threadpool`, so the event loop can still serve `/api/health` during a turn. A test holds a fake turn for 0.4 seconds and checks that health returns in under 0.3 seconds.

The index is loaded through `load_index`. Each call stats `index.json` and `vectors.npy` and reuses the arrays until either time changes. A manual rebuild is picked up on the next retrieval. If that check is ever wrong, restart the process.

CORS is off unless `CORS_ALLOWED_ORIGINS` lists full origins. `*` is a startup error.

## Visitor copy

The label and opening line are built from `BOT_NAME` and `HUMAN_NAME`. `AI_LABEL`, `OPENING_MESSAGE`, and `LOGGING_NOTICE` replace them when set. The logging notice says conversations are kept and that messages are processed by AI model providers.

The sentences proposed on the issue, which name a person and a hobby, stay unset until Ben approves the wording (architecture open item 9). The generated lines always say the speaker is an AI.

## Errors

Visitors get one JSON shape: `session_id`, `reply`, `status`, `session`, `connection`. `connection` is `primary`, `secondary`, or `null`, so the operator can see from the browser which model connection answered. They do not get stack traces, paths, or settings. The log line is a JSON object with the request id, status, HTTP code, and when a model answered, the category and the same `connection`. It does not include the visitor text, an address, or a secret.

`busy` and `daily_limit` are returned by `src/api/limits.py` (BENBOT-28). Concurrency is in-process; the daily cap is stored in SQLite and survives restarts.

## What was verified

FastAPI 0.115.14, Starlette 0.46.2, and uvicorn 0.32.1 import on Python 3.9.6 in this checkout. Docker image tags, Nginx Proxy Manager path handling, and Cloudflare were not re-checked here.

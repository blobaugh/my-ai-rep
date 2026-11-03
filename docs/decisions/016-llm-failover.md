# Primary and secondary chat connections

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-18

## Decision

Chat completions go through one in-process pool (`src/llm_pool.py`). It tries the primary connection. On a connection failure, a timeout, HTTP 429, or any 5xx it tries the secondary, marks the primary down, and keeps using the secondary. After `FAILOVER_RETRY_SECONDS` (default 300) the next real request tries the primary once. Success makes the primary active again. Failure serves the request from the secondary and restarts the timer.

`LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are the primary connection when `LLM_PRIMARY_*` is unset, so an existing `.env` keeps working. A blank value means unset. A secondary connection exists only when its base URL, key, and model are all set.

## What triggers failover

- The host refuses the connection, DNS fails, or the host cannot be reached.
- The call exceeds its timeout.
- The host responds with HTTP 429 or any 5xx.
- The HTTP status is listed in `FAILOVER_ON_HTTP_STATUS`.

A 429 or a 5xx is not a broken connection. The host accepted the request and then refused to complete it: rate limit, overload, or an internal error. That connection did not produce an answer, so the pool treats it the same as a dead host and tries the other one immediately. It does not retry that status on the same host first.

Other 4xx responses stay put. A 400, 401, or 404 means this request was rejected. Sending it to the other host would repeat a request problem, not survive an outage. HTTP 408 is the exception that still retries on the same host (three tries, 0.4s then 0.8s) unless 408 is added to `FAILOVER_ON_HTTP_STATUS`. That list is for extra statuses. It is empty by default because 429 and 5xx are already included.

Decided by Ben on 2026-11-03. The earlier default, which failed over only on connection failure and timeout, is withdrawn.

## Timeouts

The connect timeout is 5 seconds. A dead port should fail over quickly.

The total timeout defaults to 120 seconds (`LLM_PRIMARY_TIMEOUT_SECONDS` and `LLM_SECONDARY_TIMEOUT_SECONDS`). A cold local model takes about 18 seconds to the first token, then generates up to `LLM_MAX_TOKENS` (600). 120 seconds covers that cold start without treating a slow first token as a dead primary. A warm call is a few seconds and finishes well inside the same limit. The answer is still generated in full before it is shown.

The OpenAI client is created with `max_retries=0`. SDK retries would sit on a dead primary before the pool could switch.

## State

The down-until timestamp lives in the process. One log line is written when the primary goes down, when a later probe fails and the timer restarts, and when the primary recovers. Each request does not log. Concurrent requests share that state under a lock. The HTTP call itself is outside the lock.

More than one worker means more than one pool. The API is specified to run one worker (BENBOT-21). A second worker would not know that this worker had failed over.

The embedder (`EMBED_BASE_URL`) is not part of the pool. If it is down, startup still reports an error. An unreachable chat primary is a warning when the embedder is a different, reachable host. When they share one host, an unreachable embedder is still an error, because retrieval cannot run.

Both chat connections failing raises `ModelUnavailable`. `answer_turn` lets it propagate. `python -m src.chat --ask` prints one sentence and exits non-zero, without a traceback.

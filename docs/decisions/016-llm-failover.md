# Primary and secondary chat connections

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-18

## Decision

Chat completions go through one in-process pool (`src/llm_pool.py`). It tries the primary connection. On a connection failure or a timeout it tries the secondary, marks the primary down, and keeps using the secondary. After `FAILOVER_RETRY_SECONDS` (default 300) the next real request tries the primary once. Success makes the primary active again. Failure serves the request from the secondary and restarts the timer.

`LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are the primary connection when `LLM_PRIMARY_*` is unset, so an existing `.env` keeps working. A blank value means unset. A secondary connection exists only when its base URL, key, and model are all set.

## What triggers failover

- The host refuses the connection, DNS fails, or the host cannot be reached.
- The call exceeds its timeout.
- The HTTP status is listed in `FAILOVER_ON_HTTP_STATUS`.

The default list is empty. A 4xx or 5xx response, including 429, is an answer from a live model process. Switching hosts would hide a prompt, auth, or rate-limit problem and could send the same request to a second provider. Those errors stay on the connection that returned them. A 408, 429, 500, 502, 503, or 504 that is not in the failover list is retried up to three times on that same connection, with the same backoff as before (0.4s, then 0.8s). Whether 429 or 5xx should fail over instead is an open question for the person who runs this checkout. The default is no.

## Timeouts

The connect timeout is 5 seconds. A dead port should fail over quickly.

The total timeout defaults to 120 seconds (`LLM_PRIMARY_TIMEOUT_SECONDS` and `LLM_SECONDARY_TIMEOUT_SECONDS`). A cold local model takes about 18 seconds to the first token, then generates up to `LLM_MAX_TOKENS` (600). 120 seconds covers that cold start without treating a slow first token as a dead primary. A warm call is a few seconds and finishes well inside the same limit. The answer is still generated in full before it is shown.

The OpenAI client is created with `max_retries=0`. SDK retries would sit on a dead primary before the pool could switch.

## State

The down-until timestamp lives in the process. One log line is written when the primary goes down, when a later probe fails and the timer restarts, and when the primary recovers. Each request does not log. Concurrent requests share that state under a lock. The HTTP call itself is outside the lock.

More than one worker means more than one pool. The API is specified to run one worker (BENBOT-21). A second worker would not know that this worker had failed over.

The embedder (`EMBED_BASE_URL`) is not part of the pool. If it is down, startup still reports an error. An unreachable chat primary is a warning when the embedder is a different, reachable host. When they share one host, an unreachable embedder is still an error, because retrieval cannot run.

Both chat connections failing raises `ModelUnavailable`. `answer_turn` lets it propagate. `python -m src.chat --ask` prints one sentence and exits non-zero, without a traceback.

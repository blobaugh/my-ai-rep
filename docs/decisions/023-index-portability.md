# Production index is rebuilt on the droplet

**Status:** Accepted  
**Date:** 2026-11-03  
**Issue:** BENBOT-25

## Decision

Never copy `data/index/` from a developer machine to production. After `content/` is on the droplet, run `docker compose --profile tools run --rm ingest` (or `--rebuild` when embed settings change) so vectors are produced by the **embedder container** on that host.

Local dev may use Mac Ollama or the compose embedder; either way, the droplet index is always a fresh build against `http://embedder:11434/v1`.

## Why

Embedding models and runtimes are not guaranteed to emit identical floats across hosts. Even with the same model name (`nomic-embed-text`), different Ollama builds, CPU paths, or prefix handling can shift vectors. Retrieval compares query vectors to stored document vectors; mixed sources would weaken scores and break incremental updates keyed by content hash.

## Measurement

Compare the same texts on two OpenAI-compatible embed endpoints with `scripts/measure_embed_portability.py`. The script embeds at least 20 strings and reports per-text cosine similarity and the minimum.

Example (Mac Ollama vs compose embedder):

```bash
.venv/bin/python scripts/measure_embed_portability.py \
  --embed-a http://127.0.0.1:11434/v1 \
  --embed-b http://127.0.0.1:11434/v1
```

Point `--embed-b` at the compose embedder from a container on the internal network when comparing Mac Ollama to droplet embedder. Treat **min cosine &lt; 0.999** as confirmation that copying indexes is unsafe even when the model name matches.

Same endpoint twice (sanity check): min cosine **1.000000** on 20 texts (Nov 2026, Mac Ollama).

## Ingest safety

`python -m src.ingest` writes a new index under a temp directory, then atomically replaces `data/index/index.json` and `data/index/vectors.npy`. A failed run leaves the previous index untouched. The HTTP API reloads the index when those file mtimes change (no restart).

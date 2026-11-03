# Docker Compose for api, web, and an internal embedder

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-24

## Decision

Three services run under a fixed Compose project name `benbot`: `benbot_api` (Python 3.9 slim), `benbot_web` (nginx unprivileged on port 8080 inside the container), and `benbot_embedder` (Ollama 0.12.6 with `nomic-embed-text` only). Production compose pulls `linux/amd64` images and publishes no host ports. Dev compose builds for the local CPU, publishes `127.0.0.1:8080` and `127.0.0.1:8000`, and sets `DEV_PROXY_API=1` so `/api` is proxied through web like a single origin.

Private markdown, SQLite, and the NumPy index live under a host `data/` and `content/` (or `examples/` in dev) bind mount. They are listed in `.dockerignore` and never copied into the api image. Runtime dependencies are pinned in `docker/api/requirements.txt` from `pip-compile`.

The embedder stores models in a named volume and pulls `nomic-embed-text` on first start. `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_NUM_PARALLEL=1`, and `OLLAMA_MAX_LOADED_MODELS=1` keep one small model resident on a CPU droplet. The health check calls `/v1/embeddings`, not just the TCP port.

Production images target `linux/amd64` because DigitalOcean droplets are x86-64. Images built on an M1 Mac without `--platform linux/amd64` will not run there.

## Python version

The container uses Python 3.9 to match `requires-python = ">=3.9"` and the Xcode 3.9.6 dev machine. No minimum bump was needed.

## What was not verified here

Docker Desktop and OrbStack were not available in the agent environment (`docker` missing; `orbctl run docker` timed out). Builds, `docker compose up`, embedder timing, and memory measurements must be run on Ben's Mac. Document the commands in the BENBOT-24 work log when they succeed.

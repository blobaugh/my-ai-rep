# Web architecture (generic)

This stack is a **small retrieval-grounded chat API** plus **static HTML/CSS/JS** (full page and an optional embeddable widget). There is no front-end framework and no build step for the visitor UI.

## Pieces

- **Web container (`benbot_web`)** — Serves `/`, `/embed`, and `widget.js` behind nginx; sets `Content-Security-Policy` (including `frame-ancestors` for `/embed`). Optionally proxies `/api` to the API in dev (`DEV_PROXY_API=1`).
- **API container (`benbot_api`)** — FastAPI app on `/api/*`; SQLite sessions and turn log; calls `answer_turn` for every chat message.
- **Embedder (`benbot_embedder`)** — OpenAI-compatible embeddings (typically Ollama + `nomic-embed-text`), internal Docker network only.
- **Backup (optional)** — Periodic SQLite snapshots to S3-compatible storage.

Visitor-facing wording (labels, opening line) comes from environment variables (`BOT_NAME`, `HUMAN_NAME`, overrides) — see `.env.example` and `src/api/copy.py`.

## Config highlights

| Concern | Where |
| --- | --- |
| CORS | `CORS_ALLOWED_ORIGINS` (comma-separated); blank = off (same-origin widget is typical) |
| Who may iframe `/embed` | `FRAME_ANCESTORS` (space-separated origins); blank uses `web/frame_ancestors.default` (see file comments) |
| Models | `LLM_*`, `LLM_PRIMARY_*`, `LLM_SECONDARY_*`, `EMBED_*` |

## Further reading

- Decision records: [`../decisions/`](../decisions/)
- Docker layout: [containers.md](containers.md)
- Widget install: [embedding.md](embedding.md)
- Optional deep narrative with concrete hostnames (historical): [`../history/architecture-operator-deployment.md`](../history/architecture-operator-deployment.md)

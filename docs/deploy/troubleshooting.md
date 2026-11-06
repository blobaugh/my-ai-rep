# Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| **502** from NPM / Cloudflare | api or web container down, wrong upstream port | `docker compose ps`; check `benbot_web:8080`, `benbot_api:8000`; read `docker compose logs api web` |
| **`/api/health` returns HTML** (chat page) | NPM custom location strips `/api` or points to web | Fix NPM location ([deploy-droplet-setup-operator.md](../history/deploy-droplet-setup-operator.md)); use advanced `proxy_pass` without path suffix |
| **Widget blank / “refused to frame”** | CSP `frame-ancestors` missing or wrong | `curl -sI https://…/embed`; fix `FRAME_ANCESTORS` in `.env`; ensure NPM/Cloudflare do not strip CSP |
| **Embedder unhealthy** | Model volume empty, slow start, OOM | `docker compose logs embedder`; wait start-period; check disk; `docker compose restart embedder` |
| **`unavailable` replies** | Primary Mac/Ollama unreachable and secondary misconfigured | Test URLs from api container; check OpenRouter key; `python -m src.review failovers` |
| **“Index missing” / no retrieval** | Ingest never run or failed | `docker compose --profile tools run --rm ingest`; check embedder health during ingest |
| **Permission denied on `data/`** | Host ownership not UID 10001 | `chown -R 10001:10001 data/` ([deploy-droplet-setup-operator.md](../history/deploy-droplet-setup-operator.md)) |
| **Stale answers after content edit** | Index not rebuilt | Rsync content, run ingest ([content.md](./content.md)); `about.md` only needs restart-less reload |
| **Failover stuck on secondary** | Primary still down past retry window | Restore Mac/Ollama; wait `FAILOVER_RETRY_SECONDS`; check review failovers |
| **No backups in Spaces** | Wrong credentials, clock, or network | `docker compose logs backup`; verify `SPACES_*`; see [backup-restore.md](./backup-restore.md) |
| **Daily cap / busy messages** | Limits hit | `docs/web/limits.md`; raise caps or wait UTC midnight |
| **Arm64 image on amd64 droplet** | Pulled Mac-built image | Re-pull from GitLab CI amd64 tags ([deploy-ci-operator.md](../history/deploy-ci-operator.md)); `docker image inspect … Architecture` |

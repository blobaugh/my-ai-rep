# BenBot deployment runbook

Production runs as **Docker Compose on a DigitalOcean droplet**. The droplet holds
**no git checkout** — only `docker-compose.yml`, `.env`, `content/`, and `data/`.
Container images are **built in private GitLab CI** and pulled at deploy time
([ci.md](./ci.md)).

Ben configures **Nginx Proxy Manager (NPM)** and **Cloudflare** by hand; they are
not in this repository.

## Documents

| Doc | Purpose |
| --- | --- |
| [droplet-setup.md](./droplet-setup.md) | First-time server prep, directories, firewall, registry login |
| [content.md](./content.md) | Copying markdown and running ingest |
| [ci.md](./ci.md) | GitLab pipeline, image tags, dual remotes |
| [verify.md](./verify.md) | Production health checklist (curl, widget, backup, review) |
| [operations.md](./operations.md) | Updates, rollback, migrations, logs, monitoring |
| [mac-connectivity.md](./mac-connectivity.md) | Options for reaching Ollama on Ben's Mac from the droplet |
| [troubleshooting.md](./troubleshooting.md) | Symptom → fix table |
| [backup-restore.md](./backup-restore.md) | Spaces snapshots and restore |

## Quick path (already prepared droplet)

1. Set `BENBOT_HOME` (for example `/opt/benbot`), place `docker-compose.yml`, `.env`, `content/`, `data/`.
2. `docker login` to the GitLab registry; set `BENBOT_IMAGE_PREFIX` and `BENBOT_TAG` in `.env`.
3. `docker compose pull && docker compose up -d`
4. Wait for healthy containers, then `docker compose --profile tools run --rm ingest`
5. Configure NPM for `bot.benlobaugh.com` (see [droplet-setup.md](./droplet-setup.md#nginx-proxy-manager))
6. Run [verify.md](./verify.md) top to bottom

## Local validation (developer machine)

With the dev stack up (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`):

```bash
chmod +x scripts/verify-deploy-local.sh
./scripts/verify-deploy-local.sh
```

This mirrors a subset of [verify.md](./verify.md) against `127.0.0.1:8080` / `:8000`.

## Droplet-only checklist

Items that **cannot** be fully verified without Ben's production host:

- [ ] NPM custom location forwards `/api/chat` unchanged (**UNVERIFIED** forward-path UI)
- [ ] Cloudflare SSL mode vs NPM origin certificate
- [ ] Cloudflare proxy timeout under cold local model load
- [ ] `Content-Security-Policy: frame-ancestors` unchanged through NPM + Cloudflare
- [ ] Mac → droplet path to Ollama (connectivity choice)
- [ ] DigitalOcean Spaces backup upload and dead-man's-switch URL
- [ ] Widget on live `benlobaugh.com` / second site
- [ ] Public embedder port 11434 blocked at firewall

See each doc for how to test.

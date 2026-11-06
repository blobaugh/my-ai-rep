# BenBot deployment runbook

Production runs as **Docker Compose on a DigitalOcean droplet**. The droplet holds
**no git checkout** — only `docker-compose.yml`, `.env`, `content/`, and `data/`.
Container images are **built in private GitLab CI** and pulled at deploy time
([deploy-ci-operator.md](./deploy-ci-operator.md)).

Ben configures **Nginx Proxy Manager (NPM)** and **Cloudflare** by hand; they are
not in this repository.

## Documents

| Doc | Purpose |
| --- | --- |
| [deploy-droplet-setup-operator.md](./deploy-droplet-setup-operator.md) | First-time server prep, directories, firewall, registry login |
| [../deploy/content.md](../deploy/content.md) | Copying markdown and running ingest |
| [deploy-ci-operator.md](./deploy-ci-operator.md) | GitLab pipeline, image tags, dual remotes |
| [deploy-verify-operator.md](./deploy-verify-operator.md) | Production health checklist (curl, widget, backup, review) |
| [deploy-operations-operator.md](./deploy-operations-operator.md) | Updates, rollback, migrations, logs, monitoring |
| [../deploy/mac-connectivity.md](../deploy/mac-connectivity.md) | Options for reaching Ollama on a home machine from the droplet |
| [../deploy/troubleshooting.md](../deploy/troubleshooting.md) | Symptom → fix table |
| [../deploy/backup-restore.md](../deploy/backup-restore.md) | Spaces snapshots and restore |

## Quick path (already prepared droplet)

1. Set `BENBOT_HOME` (for example `/opt/benbot`), place `docker-compose.yml`, `.env`, `content/`, `data/`.
2. `docker login` to the GitLab registry; set `BENBOT_IMAGE_PREFIX` and `BENBOT_TAG` in `.env`.
3. `docker compose pull && docker compose up -d`
4. Wait for healthy containers, then `docker compose --profile tools run --rm ingest`
5. Configure NPM for `bot.benlobaugh.com` (see [deploy-droplet-setup-operator.md](./deploy-droplet-setup-operator.md#nginx-proxy-manager))
6. Run [deploy-verify-operator.md](./deploy-verify-operator.md) top to bottom

## Local validation (developer machine)

With the dev stack up (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`):

```bash
chmod +x scripts/verify-deploy-local.sh
./scripts/verify-deploy-local.sh
```

This mirrors a subset of [deploy-verify-operator.md](./deploy-verify-operator.md) against `127.0.0.1:8080` / `:8000`.

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

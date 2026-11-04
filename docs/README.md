# Documentation index

## Web (visitor-facing system)

| Doc | Topic |
| --- | --- |
| [web/architecture.md](web/architecture.md) | Hostname routing, containers, decisions D1–D17 |
| [web/api.md](web/api.md) | HTTP routes under `/api` |
| [web/containers.md](web/containers.md) | Docker Compose prod vs dev |
| [web/embedding.md](web/embedding.md) | Widget install |
| [web/limits.md](web/limits.md) | Concurrency and daily caps |
| [web/review.md](web/review.md) | Review CLI for gaps and flags |
| [web/e2e.md](web/e2e.md) | End-to-end test suite |

## Deployment

| Doc | Topic |
| --- | --- |
| [deploy/README.md](deploy/README.md) | Runbook index |
| [deploy/droplet-setup.md](deploy/droplet-setup.md) | Server prep, NPM, registry |
| [deploy/verify.md](deploy/verify.md) | Production checklist |
| [deploy/operations.md](deploy/operations.md) | Updates, rollback, monitoring |
| [deploy/ci.md](deploy/ci.md) | GitLab CI and images |
| [deploy/content.md](deploy/content.md) | Rsync and ingest on the droplet |
| [deploy/backup-restore.md](deploy/backup-restore.md) | Spaces snapshots |
| [deploy/mac-connectivity.md](deploy/mac-connectivity.md) | Reach home Ollama from VPS |
| [deploy/troubleshooting.md](deploy/troubleshooting.md) | Symptom table |

## Spec and decisions

| Doc | Topic |
| --- | --- |
| [spec/benbot-behavior.md](spec/benbot-behavior.md) | Behavior spec (parts 1–2) |
| [decisions/](decisions/) | Architecture decision records (numbered) |

## Screenshots

Captured by optional e2e UI tests: [web/screenshots/e2e/](web/screenshots/e2e/).

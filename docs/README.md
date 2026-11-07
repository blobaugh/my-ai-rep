# Documentation index

Start here after the root [`README.md`](../README.md). Decision records under
[`decisions/`](decisions/) are the long-form “why”; web and deploy docs are the
“how to run it.”

Operator-specific notes (example domains and CI layout) live under [`history/`](history/).

## Tutorials

| Doc | Topic |
| --- | --- |
| [tutorials/digitalocean-docker.md](tutorials/digitalocean-docker.md) | Clone, build, and run on an Ubuntu droplet; review turn categories |
| [tutorials/README.md](tutorials/README.md) | Tutorial index |

## Web (visitor-facing system)

| Doc | Topic |
| --- | --- |
| [web/architecture.md](web/architecture.md) | Containers, CSP, frame-ancestors, config map |
| [web/api.md](web/api.md) | HTTP routes under `/api` |
| [web/containers.md](web/containers.md) | Docker Compose prod vs dev |
| [web/embedding.md](web/embedding.md) | Widget install |
| [web/limits.md](web/limits.md) | Concurrency and daily caps |
| [web/review.md](web/review.md) | Review CLI for gaps and flags |
| [web/e2e.md](web/e2e.md) | End-to-end test suite (`./scripts/e2e.sh`) |

## Deployment

| Doc | Topic |
| --- | --- |
| [deploy/README.md](deploy/README.md) | Deploy doc index |
| [deploy/content.md](deploy/content.md) | Private markdown and ingest |
| [deploy/backup-restore.md](deploy/backup-restore.md) | Object storage snapshots |
| [deploy/mac-connectivity.md](deploy/mac-connectivity.md) | Reach home Ollama from a VPS |
| [deploy/troubleshooting.md](deploy/troubleshooting.md) | Symptom table |

## Public repo and safety

| Doc | Topic |
| --- | --- |
| [decisions/015-public-repo-private-files.md](decisions/015-public-repo-private-files.md) | What is tracked vs gitignored, MIT license, pre-commit |
| [../scripts/check_public_safe.sh](../scripts/check_public_safe.sh) | Block private paths before push (also `scripts/ci/scan.sh`) |

## Spec and decisions

| Doc | Topic |
| --- | --- |
| [spec/benbot-behavior.md](spec/benbot-behavior.md) | Behavior spec; template adopters replace the named persona |
| [decisions/](decisions/) | Architecture decision records (numbered) |

## Local scripts (no separate doc)

| Script | Role |
| --- | --- |
| [`../scripts/dev-up.sh`](../scripts/dev-up.sh) | `docker compose` dev stack |
| [`../scripts/e2e.sh`](../scripts/e2e.sh) | Full e2e with report under `data/e2e/` |
| [`../scripts/ci/`](../scripts/ci/) | Lint, test, scan, image verify |

## Screenshots

Captured by optional e2e UI tests: [web/screenshots/e2e/](web/screenshots/e2e/).

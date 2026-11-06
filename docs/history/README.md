# Historical / operator-specific documentation

Files here describe one production-style deployment (concrete hostnames, registry layout, and runbooks used during development). **They are not required** to run the app locally or to adopt this repo as a template.

For a generic overview, see:

- [`../web/architecture.md`](../web/architecture.md) — how the pieces fit together
- [`../deploy/README.md`](../deploy/README.md) — deploy-related docs that apply to any operator

| File | Notes |
| --- | --- |
| [architecture-operator-deployment.md](architecture-operator-deployment.md) | Full D1–D17 narrative with example domains |
| [embedding-operator-deployment.md](embedding-operator-deployment.md) | Widget tag examples with a live hostname |
| [deploy-readme-operator.md](deploy-readme-operator.md) | Operator runbook index |
| [deploy-droplet-setup-operator.md](deploy-droplet-setup-operator.md) | VPS, NPM, registry |
| [deploy-verify-operator.md](deploy-verify-operator.md) | Production curl checks |
| [deploy-operations-operator.md](deploy-operations-operator.md) | Monitoring and updates |
| [deploy-ci-operator.md](deploy-ci-operator.md) | Private CI building container images |

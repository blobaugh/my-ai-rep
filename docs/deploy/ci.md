# GitLab CI and container registry

BenBot’s **source of truth for automation** is a **private, self-hosted GitLab**
project. The **public GitHub** repo ([`blobaugh/my-ai-rep`](https://github.com/blobaugh/my-ai-rep))
is for readable history and issues; **images are built only on GitLab** and pushed
to the GitLab Container Registry. Production droplets **pull** those images; they
do not build on the server (see deployment runbooks in this directory).

## Why amd64 in CI

Apple Silicon builds produce `linux/arm64` images by default. The production
droplet is **x86-64**. CI therefore builds with
`docker buildx build --platform linux/amd64` (see `.gitlab-ci.yml` and
`scripts/ci/build_images.sh`).

## Pipeline overview

| Stage | Job | What it runs |
| --- | --- | --- |
| `lint` | `lint:ruff` | `scripts/ci/lint.sh` |
| `test` | `test:pytest-js` | `scripts/ci/test.sh` (pytest + `node --test` on `web/`) |
| `scan` | `scan:public-safe` | `scripts/check_public_safe.sh` (+ `gitleaks` if installed on the runner) |
| `build` | `build:images` | buildx push `api`, `web`, `embedder`, `backup` for `linux/amd64` |
| `verify-images` | `verify:images` | `scripts/ci/verify_images.sh` |

**Build tool:** Docker Buildx with the **docker-in-docker (`dind`) service**. This
is the most common GitLab setup when a shell runner mounts Docker or a dedicated
runner registers with the `docker` executor. **Kaniko** is an alternative when
`dind` is forbidden; this repo does not ship a Kaniko pipeline until a runner
constraint is confirmed.

### Image names and tags

Images use the **product** layout, not the GitHub repo name `my-ai-rep`:

- `${BENBOT_REGISTRY}/api`
- `${BENBOT_REGISTRY}/web`
- `${BENBOT_REGISTRY}/embedder`
- `${BENBOT_REGISTRY}/backup`

`BENBOT_REGISTRY` defaults to GitLab’s `CI_REGISTRY_IMAGE` (project registry root).
On the droplet, set `BENBOT_IMAGE_PREFIX` in `.env` to that same prefix (without
the `/api` suffix) so `docker-compose.yml` resolves the same names.

Tags:

- `:<short-sha>` — every pipeline on the default branch or a version tag
- `:latest` — default branch only
- `:vX.Y.Z` — when `CI_COMMIT_TAG` matches `vMAJOR.MINOR.PATCH`

Registry credentials in CI use GitLab’s **`CI_REGISTRY_USER` / `CI_REGISTRY_PASSWORD`**
(job token or deploy token configured on the project). Do not echo credentials in
job logs.

### Post-build verification

`scripts/verify_image.sh` checks:

- `docker image inspect` architecture is **amd64**
- container **UID ≠ 0** (except embedder; see below)
- no baked-in `content/`, `.env`, `*.db`, or `qa*.md` under searchable trees

Optional: install **Trivy** on the runner; `verify_images.sh` runs it with
**exit code 0** (warn only).

**Embedder exception:** the upstream `ollama/ollama` image runs as **root** and
stores models under `/root/.ollama`. CI passes `--allow-root` for embedder only.
Hardening embedder to a non-root user is **out of scope** for the CI issue; treat
as follow-up if policy requires strict non-root everywhere.

## One repo, two remotes (documented commands only)

Do **not** run these from automation; they are for Ben’s workstation.

```bash
# Existing checkout
git remote add gitlab git@gitlab.example.com:ben/benbot.git   # UNVERIFIED host/path
git remote add github https://github.com/blobaugh/my-ai-rep.git

# Push code
git push github main          # public
git push gitlab main          # private; triggers CI

# Tags (release images on GitLab)
git tag v1.2.3
git push github v1.2.3
git push gitlab v1.2.3
```

**Why GitHub stays safe:** `scripts/check_public_safe.sh` and `.dockerignore`
block private paths and high-confidence secret patterns before push (BENBOT-17).

**Mirroring:** GitLab can mirror GitHub → GitLab or the reverse depending on
edition and admin settings. **UNVERIFIED** on this project — confirm on Ben’s
instance before relying on mirroring instead of dual push.

## Local amd64 build (one-off)

When CI is unavailable:

```bash
export BENBOT_IMAGE_PREFIX=benbot   # or your registry prefix
export TAG=local-amd64
docker buildx build --platform linux/amd64 -f docker/api/Dockerfile \
  -t "${BENBOT_IMAGE_PREFIX}/api:${TAG}" .
# repeat for web, embedder, backup
```

Or set `IMAGE_*` and run `scripts/ci/build_images.sh` (requires buildx `--load`).

## Droplet pull (deploy token)

**UNVERIFIED** registry URL and token steps — fill in after GitLab project exists:

1. Create a **deploy token** or **read-only** registry credential on the GitLab project.
2. On the droplet: `docker login registry.example.com` (masked; not in git).
3. Set `BENBOT_IMAGE_PREFIX` and `BENBOT_TAG` in `.env`, then `docker compose pull`.

Details overlap with the deployment runbook (BENBOT-29).

## CI/CD variables Ben must confirm

| Variable | Required | Notes |
| --- | --- | --- |
| (built-in) `CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` | yes | Provided when Container Registry is enabled |
| `BENBOT_REGISTRY` | optional | Override registry image root; default `CI_REGISTRY_IMAGE` |
| Custom secrets for tests | no | pytest uses no live API keys |

### Questions for Ben (UNVERIFIED)

1. Is the **Container Registry** enabled on the self-hosted GitLab project?
2. Is there a **Docker-capable runner** (dind or socket-bound Docker) for `linux/amd64` builds?
3. Exact **GitLab project path** and registry hostname for `BENBOT_IMAGE_PREFIX` on the droplet?
4. Preferred **deploy token** vs **CI job token** for droplet pulls?

## Validate without GitLab

Run the same scripts locally:

```bash
./scripts/ci/lint.sh
./scripts/ci/test.sh
./scripts/ci/scan.sh

export IMAGE_API=benbot/api:ci IMAGE_WEB=benbot/web:ci \
  IMAGE_EMBEDDER=benbot/embedder:ci IMAGE_BACKUP=benbot/backup:ci
./scripts/ci/build_images.sh   # needs Docker buildx
./scripts/ci/verify_images.sh

# Prove verify fails on leaked content (needs Docker):
./scripts/ci/demo_verify_image_fail.sh
```

**YAML lint:** validate `.gitlab-ci.yml` with the GitLab **CI Lint API** on Ben’s
instance (`POST /api/v4/ci/lint`) or a local linter. This agent environment has
**no GitLab URL or token**, so lint was not executed against a live server.

### What only works on real GitLab

- Registry login with project credentials and **push** of all four images
- **buildcache** refs on the registry
- Runner provisioning (`dind` networking, disk, embedder model download time)
- Tag rules tied to `CI_DEFAULT_BRANCH` and release tags
- Optional **Trivy** / **gitleaks** packages on the runner image

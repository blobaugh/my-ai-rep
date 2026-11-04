# Droplet setup

Prepare a **linux/amd64** Ubuntu (or similar) VPS. BenBot does not install application
source on the server.

## Prerequisites

Install **Docker Engine** and the **Compose plugin** using Docker’s current
[Install Docker Engine](https://docs.docker.com/engine/install/) and
[Install the Compose plugin](https://docs.docker.com/compose/install/linux/)
guides. **UNVERIFIED:** exact package names on your Ubuntu version — follow the
official docs at install time.

Confirm architecture matches CI images:

```bash
uname -m
# expect: x86_64
```

## Deploy user

Create a non-root user (for example `deploy`) in the `docker` group. Do not run
Compose as root long term.

```bash
sudo adduser deploy
sudo usermod -aG docker deploy
```

## Directory layout

Recommended:

```text
/opt/benbot/
  docker-compose.yml   # copy from repo
  .env                 # from .env.example; secrets never in git
  content/             # private markdown (rsync from Mac)
  data/                # SQLite + index (created on first run)
```

Set in `.env`:

```bash
BENBOT_HOME=/opt/benbot
```

### File ownership and container UIDs

| Service | Container user | UID |
| --- | --- | --- |
| api | `app` | **10001** |
| backup | `backup` | **10002** |
| web (nginx) | nginx unprivileged | **101** |
| embedder | root (upstream Ollama) | **0** |

The api container writes SQLite under `/app/data` (bind-mounted from `data/`).
Ensure `data/` is writable by UID **10001** on the host, for example:

```bash
sudo mkdir -p /opt/benbot/data /opt/benbot/content
sudo chown -R 10001:10001 /opt/benbot/data
# content/: world-readable is enough (see content.md)
chmod -R a+rX /opt/benbot/content
```

## Proxy network

NPM and BenBot share an **external Docker network**. Find NPM’s network:

```bash
docker network ls
docker inspect <npm_container> --format '{{json .NetworkSettings.Networks}}'
```

Set in `.env`:

```bash
PROXY_NETWORK=proxy   # use the name NPM actually uses
```

Production `docker-compose.yml` attaches `web` and `api` to `proxy` so NPM can
reach `benbot_web` and `benbot_api` by container name.

## Firewall

Allow only **22**, **80**, and **443** (DigitalOcean Cloud Firewall and/or `ufw`).

Confirm no extra ports are published:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
ss -tlnp
```

Embedder must **not** appear on `0.0.0.0:11434`. `docker port benbot_embedder`
should print nothing.

## Registry access

See [ci.md](./ci.md) for image names (`${REGISTRY}/api`, `/web`, `/embedder`, `/backup`)
and tags (`:latest`, `:<short-sha>`, `:vX.Y.Z`).

**UNVERIFIED:** exact GitLab UI for a read-only deploy token on Ben’s instance.

1. Create a **read-only** registry token in GitLab (project → Settings → Repository
   → Deploy tokens, or equivalent).
2. On the droplet:

```bash
docker login registry.example.com   # hostname from Ben’s GitLab
```

3. In `.env`:

```bash
BENBOT_IMAGE_PREFIX=registry.example.com/<group>/<project>
BENBOT_TAG=latest                   # or pin a CI short SHA / release tag
```

## First deployment

1. Copy `docker-compose.yml` and create `.env` from `.env.example`.
2. Fill **required** settings (minimum for production):

| Variable | Notes |
| --- | --- |
| `BENBOT_HOME` | Host path with `data/` and `content/` |
| `BENBOT_IMAGE_PREFIX`, `BENBOT_TAG` | Registry images from CI |
| `PROXY_NETWORK` | NPM Docker network name |
| `BOT_NAME`, `HUMAN_NAME` | Persona |
| `CONTENT_DIR` | Use `/content` in compose (default via mount) |
| `LLM_PRIMARY_*` or `LLM_*` | URL reachable **from inside api container** (often Mac Ollama — see [mac-connectivity.md](./mac-connectivity.md)) |
| `LLM_SECONDARY_*` | OpenRouter failover |
| `SPACES_*`, `BACKUP_*` | Backup container (BENBOT-26) |
| `FRAME_ANCESTORS` | Sites allowed to embed the widget |

Full list: `.env.example` and `src/config.py`.

3. Rsync `content/` ([content.md](./content.md)).
4. Pull and start:

```bash
cd /opt/benbot
docker compose pull
docker compose up -d
```

5. Wait until `docker compose ps` shows healthy for api, web, embedder.
6. Build the search index:

```bash
docker compose --profile tools run --rm ingest
```

7. Smoke from the droplet (before NPM):

```bash
curl -fsS http://127.0.0.1:8080/api/health   # only if dev-style port publish — production uses NPM
docker exec benbot_api curl -fsS http://127.0.0.1:8000/api/health
```

Production traffic uses HTTPS via NPM ([verify.md](./verify.md)).

## Nginx Proxy Manager

Host: **`bot.benlobaugh.com`** (example). Two upstreams on the **same Docker network**
as NPM:

| Entry | Forward to | Port | Notes |
| --- | --- | --- | --- |
| Proxy host `/` | `benbot_web` | **8080** | Static UI, `/embed`, `widget.js` |
| Custom location `/api` | `benbot_api` | **8000** | API keeps `/api` prefix |

### Custom location path (**UNVERIFIED**)

The FastAPI app mounts routes under **`/api`** (for example `/api/chat`, `/api/health`).
NPM must **not** strip the prefix.

- **Intended:** leave NPM’s “forward path” / rewrite field **empty** so the upstream
  receives the same path the browser sent.
- **Proof test** (after NPM is live):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Content-Type: application/json' \
  -d '{"message":"ping"}' \
  https://bot.benlobaugh.com/api/chat
# expect 200 or 4xx from API — not nginx serving index.html
curl -sS https://bot.benlobaugh.com/api/health
# expect JSON {"status":"ok"} or similar — not HTML
```

If `/api/health` returns the chat HTML page, the location block is wrong.

### Fallback advanced config

In NPM “Advanced” for the host, if the UI strips paths:

```nginx
location /api/ {
    proxy_pass http://benbot_api:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Why no URI after the port:** `proxy_pass http://benbot_api:8000;` (no trailing
path) forwards the original request URI unchanged, so `/api/chat` stays `/api/chat`.
A trailing slash on `proxy_pass` would rewrite the path.

### Other NPM settings

- **Websockets:** off (chat uses JSON request/response today).
- **Block common exploits:** optional; test after enabling — **UNVERIFIED** whether
  it interferes with JSON POST bodies.
- **Advanced → timeouts:** set `proxy_read_timeout` high enough for a cold local
  model (start with **120s**; tune using logs). See BENBOT-18.
- **`client_max_body_size`:** **16k** is enough (API rejects bodies over 8KB); use
  **32k** for margin.

**Proxy buffering:** responses are a single JSON blob, not streamed. Default NPM
buffering is fine. If streaming is added later, disable buffering on `/api` and
raise timeouts end-to-end (NPM, Cloudflare, origin).

## Cloudflare

Ben uses Cloudflare in front of NPM. **UNVERIFIED** without testing on the live zone:

| Topic | Guidance |
| --- | --- |
| SSL/TLS mode | Often **Full (strict)** when NPM serves a valid origin cert. Confirm in [Cloudflare SSL modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/) — do not guess the current dashboard default. |
| Proxy read timeout | Free/pro plans often cap around **100 seconds** at the edge. **UNVERIFIED:** see [Cloudflare timeout documentation](https://developers.cloudflare.com/) for your plan; cold local LLM may need secondary failover within that window. |
| Caching | **Bypass cache** for `/api/*`. Short cache (for example 5 minutes) for `widget.js`; no cache for `/` and `/embed` while iterating. |
| `frame-ancestors` | Web container sets `Content-Security-Policy`. Verify with `curl -sI https://bot.benlobaugh.com/embed` — header must reach the browser **once**, unchanged. Test with NPM only, then with Cloudflare orange-cloud. |

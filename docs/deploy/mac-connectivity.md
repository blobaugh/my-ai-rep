# Mac connectivity (primary LLM)

Production often keeps the **primary model on Ben’s Mac** (Ollama) while the droplet
runs api, web, embedder, and backup. The api container must reach an **OpenAI-compatible**
HTTP API (`LLM_PRIMARY_*` or legacy `LLM_*` in `.env`).

Ben chooses the network path (BENBOT-16 open item 2). This document lists options only —
**nothing here is verified on your network until you test it.**

## What the app needs

- From **inside** `benbot_api`, `curl` to the configured base URL + `/v1/models` or a
  minimal chat request must succeed.
- Timeouts: default **120s** total per request — cold local models can take tens of
  seconds before tokens arrive (BENBOT-18).
- **Secondary** (`LLM_SECONDARY_*` / OpenRouter) should remain configured so chat works
  when the Mac is offline.

## Ollama on the Mac (**UNVERIFIED** settings)

Ollama’s default listen address is often **localhost only**. To accept connections from
a tunnel or LAN, you must change bind/listen settings per **current Ollama documentation**
— do not rely on this file for the exact flag names.

**Never** expose Ollama on the public internet without authentication.

## Option A: Overlay VPN (e.g. Tailscale)

| Pros | Cons |
| --- | --- |
| Stable private IP for the Mac | Another service to maintain |
| No port forwarding on home router | Latency vs same-room LAN |

Point `LLM_PRIMARY_BASE_URL` at `http://<mac-tailscale-ip>:11434/v1` (port **UNVERIFIED**).

## Option B: Tunnel (Cloudflare Tunnel, ngrok, similar)

| Pros | Cons |
| --- | --- |
| Works without opening inbound ports | URL/egress policies; may violate ToS for some providers |
| Quick to trial | Extra hop and timeout limits |

Use the tunnel’s HTTPS URL as base (must speak OpenAI-compatible API).

## Option C: SSH reverse tunnel

| Pros | Cons |
| --- | --- |
| No new accounts if SSH already trusted | Fragile if SSH session drops |
| | Mac must stay awake |

Example shape only (**UNVERIFIED**):

```bash
# On Mac — forward local Ollama to a port on the droplet
ssh -N -R 11434:127.0.0.1:11434 deploy@droplet
```

Then `LLM_PRIMARY_BASE_URL=http://127.0.0.1:11434/v1` **does not** work from inside
api — the tunnel must bind on an address reachable from the api container (often the
droplet’s docker bridge or `host.docker.internal` patterns). **Test with:**

```bash
docker compose exec api curl -fsS "$LLM_PRIMARY_BASE_URL/models"
```

## Verification checklist

- [ ] Primary answers from droplet api container
- [ ] Failover to OpenRouter when primary is stopped ([deploy-verify-operator.md](../history/deploy-verify-operator.md) §8)
- [ ] No public Ollama port on Mac WAN IP

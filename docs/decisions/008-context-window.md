# Effective Ollama context window and budget guard

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-6

## Background

UNVERIFIED belief: Ollama may run models with a default `num_ctx` below the model’s advertised maximum, and over-long prompts may truncate silently — possibly from the *start*, which would drop system rules.

## Measurement (2026-10-15)

Probe, since removed (`scripts/prototypes/probe_context_window.py`, deleted in BENBOT-34), against `llama3.1:8b` via the OpenAI-compatible API. A canary string is placed at the start of the system message; the model is asked to echo it.

| Approx system chars | `usage.prompt_tokens` | Sees canary |
|---------------------|----------------------|-------------|
| 1k–16k | scales (~238–2918) | yes |
| 32k+ | **stuck at 2050** | **no** |

So the stock model’s effective context is about **2048 tokens**, and truncation drops the **prefix** (rules are at risk).

Derived model `benbot-llama` (`FROM llama3.1:8b` + `PARAMETER num_ctx 8192`):

| Approx system chars | `usage.prompt_tokens` | Sees canary |
|---------------------|----------------------|-------------|
| 16k | ~2918 | yes |
| 32k | ~5773 | yes |
| 64k | ~4098 (degraded) | no |

Raw probes: `data/eval/context_probe_*.json`.

## Decision

1. Ship a Modelfile-derived model with `num_ctx 8192` (`benbot-llama`) and point `LLM_MODEL` at it. Reproduce via README / Modelfile at repo root.
2. Estimate prompt size with a documented heuristic: `ceil(total_chars / 4)`.
3. Enforce `CONTEXT_BUDGET_TOKENS` (default **7000** ≈ 8192 − `max_tokens` − margin). When over budget: drop oldest history turns first, then lowest-ranked chunks; never drop the system message. Log when the guard acts.

## Alternatives considered

- Rely on the stock 2k window — rejected (rules truncated under load).
- Raise `num_ctx` only in raw Ollama options — rejected for now so the app stays on the OpenAI-compatible client path.

# OpenRouter model comparison (BENBOT-31)

**Date:** 2026-11-03 (Pacific). **Catalog source:** OpenRouter `GET /api/v1/models` on that date.

## Candidates

| Model id | Role | Context (from API) | Pricing in/out (USD per token) | Notes |
|----------|------|--------------------|--------------------------------|-------|
| `benbot-llama` | Local baseline | n/a (Ollama) | $0 | Tuned reference |
| `meta-llama/llama-3.1-8b-instruct` | OpenRouter | 131072 | 5e-8 / 8e-8 | Same family as local 8B |
| `meta-llama/llama-3.2-3b-instruct` | OpenRouter small | 131072 | (see catalog JSON) | Faster, more fallbacks in eval |
| `openai/gpt-4o-mini` | OpenRouter mid | 128000 | 1.5e-7 / 6e-7 | Best hard-check pass rate |
| `qwen/qwen-2.5-7b-instruct` | OpenRouter budget | 32768 | 1e-7 / 2e-7 | Heavy prune/fallback |

**Excluded (examples):** `google/gemma-2-9b-it` and `anthropic/claude-3.5-haiku` ids were not present under those exact slugs in the 2026-11-03 catalog; newer Gemma 4 / Claude Haiku 4.5–5.5 ids appeared instead. We kept a fixed four-model shortlist plus baseline to limit spend.

**Data retention:** OpenRouter documents provider policies per model on the model detail pages; this run did not re-verify each provider’s retention text. Treat visitor text as leaving Ben’s infrastructure when `LLM_PRIMARY_*` points at OpenRouter.

## Summary table (99 eval turns each)

| Model | Reg fail | Conv fail | Guard fail | Gap `no_answer` | Prune | Retry | Fallback | mean s | p95 s |
|-------|----------|-----------|------------|-----------------|-------|-------|----------|--------|-------|
| benbot-llama (local) | 2 | 0 | 2 | 75% | 14 | 6 | 5 | 5.71 | 12.59 |
| llama-3.1-8b-instruct | 2 | 0 | 2 | 65% | 18 | 6 | 0 | 2.52 | 7.68 |
| llama-3.2-3b-instruct | 2 | 0 | 2 | 65% | 7 | 4 | 3 | 0.72 | 1.75 |
| **gpt-4o-mini** | **0** | **0** | **1** | **100%** | 11 | 0 | 0 | 1.51 | 3.29 |
| qwen-2.5-7b-instruct | 2 | 0 | 2 | 65% | 22 | 6 | 13 | 0.87 | 1.83 |

Raw JSON: `data/eval/compare_models_benbot31_20261103T234256Z/` (local; not required in git).

## Spend

OpenRouter key usage moved from **$0** to **~$0.072** for the four cloud candidates (baseline-local used Ollama only). Key monthly budget reported **$10** with **~$9.93** remaining after the run.

## Rerun command

```bash
python -m eval.compare_models --tag my-run
# Optional: --models openai/gpt-4o-mini meta-llama/llama-3.1-8b-instruct
# Skip local baseline: --skip-baseline
```

## False-prune notes (manual, report-only)

Verification was calibrated on `benbot-llama`. Examples flagged for human review in the baseline run:

- **Likely correct prunes:** Sun and off-topic sentences removed before the 4.4 line; unsupported coaching detail on “say more about that”.
- **Borderline / possible false prunes:** Leadership-coach and family one-liners on “Tell me about Ben” and “work for” — grounded in Q&A but removed when support scores were low; **gpt-4o-mini** pruned less aggressively on regression (1 prune vs 3 on baseline) but added conversation prunes.

No thresholds were changed in this issue.

## Opinion: default OpenRouter secondary

**Recommend `openai/gpt-4o-mini` for the secondary connection** when Ben wants cloud failover: only candidate with **zero regression failures**, **one** guardrail failure (vs two on others), **100%** `no_answer` on the gap set, and no repair fallbacks. Tradeoff: slightly higher token cost than Llama 3.1 8B on OpenRouter; still modest at measured ~750 prompt tokens per eval turn.

**Cost sketch (OpenRouter primary, gpt-4o-mini, ~750 prompt + ~20 completion tokens per turn):**

| Turns/day | ~USD/month (30d, rough) |
|-----------|-------------------------|
| 50 | ~$2–4 |
| 200 | ~$8–15 |
| 1000 | ~$40–75 |

Re-run `python -m eval.compare_models` if OpenRouter retires the model or pricing shifts materially.

## Proposed logging notice (not applied — for Ben)

> Conversations are logged and kept to improve the bot. Messages are processed by AI model providers (including OpenRouter when configured). Please do not share personal information.

## `.env.example`

See commented `LLM_SECONDARY_MODEL=openai/gpt-4o-mini` placeholder added in this change.

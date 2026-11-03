# Retrieve versus stuff for Q&A

**Status:** Superseded by the 2026-11-03 content model. `QA_MODE` is gone. Only `content/about.md` is pasted into the system prompt. Searchable files are retrieved.  
**Date:** 2026-10-19  
**Issue:** BENBOT-7

## Background

`QA_MODE=retrieve` pulls matching Q&A into the user message. `QA_MODE=stuff` appends every entry to the system prompt when it fits `CONTEXT_BUDGET_TOKENS`.

## Measurement (2026-10-20)

Guardrail advisory eval (18 cases, `benbot-llama`, `QA_EMBED_MODE=question_and_answer`, `RETRIEVAL_MIN_SCORE` cleared for the run). Stuff fitted: 21 entries under budget 7000 (~3784 estimated tokens).

| Condition | Flagged cases |
|-----------|---------------|
| `sources=none` (facts only) | 10 |
| `sources=qa` retrieve | 7 |
| `sources=blog,qa` retrieve | 5 |
| `sources=qa` stuff | **4** |

Raw: `data/eval/guardrail_{none,qa,blogqa,stuff}_20261020T004*.json`. Compare table via `python -m eval.compare_runs …`.

## Decision

**Keep default `QA_MODE=retrieve`.** Stuff scores better on knowledge-use cases in this run, but retrieve matches the long-term design (stable system prefix, selective context) and scales if the Q&A file grows. Stuff remains available for ablation and demos. Revisit after Ben reviews the raw answers.

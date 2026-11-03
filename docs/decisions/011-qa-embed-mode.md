# Q&A embedding mode

**Status:** Accepted  
**Date:** 2026-10-19  
**Issue:** BENBOT-7

## Background

Q&A entries can be embedded as question-only (closest to visitor wording) or question+answer. Prefixes from BENBOT-5 still apply.

## Measurement (2026-10-20)

Eval: `python -m eval.run_qa_retrieval_eval` (47 cases, k=4, `source_types=qa`).

| Mode | Hit@4 | MRR |
|------|-------|-----|
| `question_and_answer` | **0.979** (46/47) | **0.892** |
| `question_only` | 0.894 (42/47) | 0.805 |

Raw: `data/eval/qa_retrieval_20261020T003732Z.json`.

## Decision

**Default: `QA_EMBED_MODE=question_and_answer`.**

Rationale: higher hit rate and MRR on paraphrases and hard cases. Mode is stored in index metadata; changing it re-embeds Q&A rows only. Re-run `python -m src.qa` (optional) and `python -m src.index_chunks` after a mode change.

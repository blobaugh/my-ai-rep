# Folder cleanup, no archive

**Status:** Accepted
**Date:** 2026-11-02
**Issue:** BENBOT-34

## Decision

Learning-phase leftovers were removed from the working folder. No archive and no backup were kept. The deletions are permanent. The working pipeline, its tests and eval cases, the spec and decision records, private `content/`, `.env`, and the current index stay where they are.

## What was removed

- `data/backups/` (copies of earlier trees)
- `data/audit/` (BENBOT-11 audit scripts and outputs)
- `data/reports/short_articles.txt` (recreated by `python -m src.convert_articles`)
- `data/vectors.npy` (scratch file from the retrieval prototype, not `data/index/vectors.npy`)
- `scripts/prototypes/` (embed, retrieve, and context-window probes)
- root `chat.py` (the implementation is `src/chat.py`)
- `.pytest_cache/` and `.ruff_cache/`
- older `regression_*.json`, `guardrail_*.json`, and `qa_retrieval_*.json` files under `data/eval/`
- saved notes under `data/eval/` that are not the kept baseline for a kind (acceptance transcripts, review sheets, comment dumps, and experiment logs)
- `prompts/variants/`
- root `hello_llm.py`

The newest saved file of each eval kind was kept, along with result files that a decision record still cites. `.cursor/` was not removed.

## Why

The folder was built while learning the pipeline (BENBOT-1 to BENBOT-15). On 2026-10-30 Ben decided that scaffolding was not worth keeping and that no archive was wanted. Later web issues call the code that stayed.

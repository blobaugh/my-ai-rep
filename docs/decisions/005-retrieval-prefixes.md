# Query / document prefixes for nomic-embed-text

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-5

## Background

`nomic-embed-text` is commonly used with task prefixes:

- `search_query: ` before questions
- `search_document: ` before corpus passages

The Ollama library page does not document these clearly. We measured both settings on the BenBot corpus.

## Measurement (2026-10-15)

Eval: `python -m eval.run_retrieval_eval --compare-prefixes` (15 cases, k=5).

| Variant | Hit rate@5 | Notes |
|---------|------------|-------|
| no_prefix | **1.000** (13/13) | nginx top1 ≈ 0.721; off-topic “Sun” ≈ 0.565 |
| nomic_prefixes | **1.000** (13/13) | nginx top1 ≈ 0.771; off-topic “Sun” ≈ 0.561; “quantum” off-topic rose to ≈ 0.690 |

Raw compare output: `data/eval/prefix_compare_20261015T172355Z.json`.

## Decision

**Chosen default: nomic task prefixes** (`EMBED_QUERY_PREFIX=search_query: `, `EMBED_DOC_PREFIX=search_document: `).

Rationale: hit rate tied, but on-topic top-1 scores generally improved (e.g. nginx +0.05). Prefix settings are stored in `index.json`; changing them requires `--rebuild`.

Caveat: one off-topic question scored higher with prefixes — do not treat scores as probabilities; pick a relevance threshold later from eval distributions.

**Dotenv note:** quote prefix values in `.env` (`EMBED_QUERY_PREFIX="search_query: "`) so the trailing space is preserved.

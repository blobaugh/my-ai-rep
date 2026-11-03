# Per-article cap and exact-duplicate removal

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-5

## Decision

In `retrieve()`:

1. **Per-article cap** — default `max_per_article=2`. After scoring, keep at most N chunks per `slug`.
2. **Exact-duplicate removal** — if multiple chunks share the same `content_hash`, keep only the highest-scoring copy.

Do **not** attempt near-duplicate detection.

## Why

Prototype runs showed “What’s your leadership philosophy?” returning 4/5 chunks from one article, and near-identical posts (`introducing-sailing-to-a-new-friend` vs `-2`) tying on score. Caps improve diversity; exact hash dedupe removes true duplicates without fuzzy matching complexity.

## Non-goals

- No hardcoded relevance threshold (chosen later from eval top-1 score distributions).
- No MMR / re-ranking in this issue.

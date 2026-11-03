# Chunk size, word measurement, and overlap

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-4

## Decision

- Default sizes: **target 300 / max 450 / min 60** words per chunk (configurable via `ChunkConfig`).
- Measure size in **words** (whitespace-separated), not tokens. No tokenizer dependency in v1.
- When a section must be split, following chunks start with ~**40 words** of overlap (about 1–2 trailing sentences) from the previous chunk’s core text. **No overlap across heading boundaries.**
- Fenced code blocks are **opaque**: never split inside a fence; an oversize fence stays one chunk and is flagged.

## Why words (not tokens)

Words are simple, deterministic, and good enough to ship retrieval scaffolding. They **undercount tokens**, especially for code and dense punctuation, so a “450 word” chunk can be larger than 450 tokens for the embedder. The eval suite (later) can retune `ChunkConfig` once we measure retrieval quality.

## Tradeoffs

| Choice | Upside | Downside |
|--------|--------|----------|
| ~300-word target | One idea per chunk; prompt stays small | Risk of cutting mid-argument on long essays |
| Overlap inside a section | Continuity when a section is sliced | Slight duplication in the vector store |
| No cross-heading overlap | Sections stay topically clean | Boundary sentences may lose prior-section context (mitigated by `embed_text` title/section prefix) |
| Opaque code fences | Snippets stay runnable/readable | A huge fence can exceed max words (flagged, not split) |
| Keep short posts as one chunk | No empty padding; tiny posts stay whole | Very short chunks may embed weakly |

## Related

- BENBOT-3: do not repair fenced-code whitespace in migrated posts.
- `updated_at` on migrated posts is the migration date — chunk metadata uses `published_at` only.

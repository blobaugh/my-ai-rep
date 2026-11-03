# NumPy file vector store (not Chroma / LanceDB)

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-5

## Decision

Persist embeddings as `data/index/vectors.npy` plus `data/index/index.json`, behind a `VectorStore` Protocol. Do **not** adopt Chroma, LanceDB, SQLite-vec, or pgvector for v1.

## Rationale

- Corpus size is ~1,400 × 768 ≈ 4 MB — a full scan is one matrix multiply (`vecs @ q`).
- A pair of files is easy to inspect, clone, and reason about while learning retrieval.
- The Protocol keeps a later backend swap to one module change.

## When to revisit

Revisit the file store when any of these become true (rules of thumb, not measured here):

- Corpus grows past roughly **100,000** chunks.
- More than one process must **write** the index concurrently.
- Approximate nearest neighbor latency becomes necessary.
- Server-side filtering / managed persistence features are required.

# Embedding input limit and truncation

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-5

## Findings

- Ollama’s `nomic-embed-text` model card lists a **2K context window**.
- The two largest BenBot chunks by word count are well under 6k characters:
  - `c-virtual-token-ring-network#1` — 722 words / **4977** chars
  - `2009-fluxbox-keys-file#1` — 662 words / **3980** chars
- Live embed experiment (OpenAI-compatible `/embeddings` via the configured endpoint): both oversize chunks embed successfully without truncation at `EMBED_MAX_CHARS=8000`.

## Decision

- Default `EMBED_MAX_CHARS=8000` as a safety net (configurable).
- Truncate prefixed text when longer; never crash the index run.
- Log every truncated chunk id in the `index_chunks` report.
- Do not “repair” or specially split oversize code fences here (see BENBOT-3 / BENBOT-4).

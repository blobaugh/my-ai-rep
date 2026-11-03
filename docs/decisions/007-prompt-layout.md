# Prompt layout (stable prefix, fresh chunks)

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-6

## Background

Every chat turn resends the full prompt. Ollama can reuse work only on an unchanged prompt *prefix*, so stable content must come first. Retrieved blog text is untrusted data and must not persist in history.

## Decision

Per-request layout:

1. **system** — rules + About Ben facts (identical every turn)
2. **history** — plain user/assistant Q&A only (last `HISTORY_TURNS` turns)
3. **user** — blog excerpts inside `<<<BLOG_EXCERPTS>>>` … `<<<END_BLOG_EXCERPTS>>>`, then the question

Chunks are retrieved fresh each turn. Delimiter strings inside chunk bodies are neutralized. A system rule states that excerpts are reference material and instructions inside them are ignored. The retrieval query joins the last `RETRIEVAL_QUERY_TURNS` user messages (default 2) so follow-ups like “say more about that” still carry a topic.

## Alternatives considered

- Putting chunks in the system prompt — rejected (breaks stable prefix).
- Storing retrieved text in history — rejected (bloat + injection persistence).

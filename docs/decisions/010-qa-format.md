# Curated Q&A knowledge format

**Status:** Accepted  
**Date:** 2026-10-19  
**Issue:** BENBOT-7

## Background

Ablation showed the raw blog corpus can worsen guardrails, while the facts file alone yields thin answers. Ben supplies short first-person Q&A entries as reviewed knowledge.

## Decision

- Private file `content/qa.md` (gitignored). Committed sample: `examples/qa.example.md` (fictional person).
- Format (stdlib parser, no YAML):

```
## <entry-id>
Q: <question>
A: <answer, may span lines>
source: <bookkeeping only>
review: draft | approved
```

- Agent must not rewrite Ben’s wording. `source` / `review` never reach the model or visitors.
- Chunk records: id `qa#<entry-id>`, `source_type=qa`, body = answer only, title = question, empty `published_at`.
- Q&A is never listed under “From my blog:” and never gets an age marker.
- Default retrieval: `RETRIEVAL_SOURCES=qa` (blog stays indexed but off).

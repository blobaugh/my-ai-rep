# Multi-vector Q&A and the question-vector prefix

**Status:** Accepted
**Date:** 2026-10-22
**Issue:** BENBOT-14

## Decision

`QA_EMBED_MODE` defaults to `multi`. Each Q&A and facts entry is one vector per question phrasing plus one question-plus-answer vector. Retrieval keeps the best vector per entry. Ties keep the `qa` vector.

Question phrasing vectors (`kind=q`) are embedded with the **document** prefix (`search_document: `), not the query prefix.

## Measurement

161 cases, k=4, sources `qa,facts`. Raw files:

- `data/eval/qa_retrieval_20261022T132440Z.json` (question_and_answer, question_only, multi with the query prefix)
- `data/eval/qa_retrieval_20261022T132725Z.json` (multi with the document prefix)

| Mode | q prefix | Hit@4 | MRR | All expected in top 4 |
|---|---|---:|---:|---:|
| question_and_answer | n/a | 0.981 (158/161) | 0.923 | 2/7 |
| question_only | n/a | 0.932 (150/161) | 0.903 | 4/7 |
| multi | query | 0.975 (157/161) | 0.945 | 3/7 |
| multi | document | **0.994 (160/161)** | **0.949** | 3/7 |

Document prefix beats query prefix on hit rate and MRR with the same all-expected count. Multi with that prefix beats `question_and_answer` on hit rate, MRR, and all-expected.

The one miss under the chosen index is `hard-retention-managing-devs` (same miss as BENBOT-15).

## Why the document prefix

A question phrasing is stored as a document, same as the question-plus-answer vector. Matching a visitor question to that phrasing worked better with `search_document:` than with `search_query:` on both sides (the query still uses `search_query:`).

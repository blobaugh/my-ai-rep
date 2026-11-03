# The weak-retrieval flag stays off

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-19

## Decision

`WEAK_RETRIEVAL_SCORE` stays unset. The `weak_retrieval` flag is disabled until a later measurement shows a stable gap between questions the content answers and questions it does not.

A blank value means unset. A set value is a float from 0 to 1. The flag is raised only when the best score among passages actually sent to the model is strictly below that value. Equality is not weak. Passages that were retrieved and then dropped are not part of the score.

## What was measured

The embedder is `nomic-embed-text` and `QA_EMBED_MODE` is `multi`. Scores are cosine similarities. They are bunched, and they are not probabilities.

Current index, top score from `retrieve()` at `k=4`, 2026-11-03. These are the questions in `eval/gap_cases.json`.

| Group | n | min | median | max |
|---|---:|---:|---:|---:|
| gap | 20 | 0.5622 | 0.6249 | 0.7057 |
| off-topic | 10 | 0.5612 | 0.6144 | 0.7199 |
| answerable | 15 | 0.7131 | 0.8109 | 0.9101 |

Older retrieval eval `data/eval/qa_retrieval_20261022T132725Z.json`, `multi` mode, top-1 score of the 160 hits out of 161 cases: min 0.5734, median 0.8266, max 0.9390. That file predates the all-content index, so those numbers are not the same distribution. The one miss was `hard-retention-managing-devs`.

## Why there is no default

The gap group's highest score (0.7057) sits 0.007 below the lowest answerable score (0.7131). That margin is one question wide.

Off-topic overlaps the answerable band. One off-topic question scored 0.7199, above two answerable questions (0.7131 and 0.7135).

Historical hits start at 0.5734, inside today's gap band. A threshold that flagged every gap question in this set would have flagged real hits on the older index.

A default would look clean on these 45 questions and miss the next loosely worded question the content does answer. Recalibrate if the embedder or `QA_EMBED_MODE` changes.

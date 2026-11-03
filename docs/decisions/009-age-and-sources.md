# Age notes and harness-owned source links

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-6

## Background

Language models are unreliable at date arithmetic and invent URLs. Migration left many posts with an `updated_at` that reflects import time, not editorial freshness.

## Decision

- The harness attaches links and decides age; the model never writes URLs or decides what is old.
- Age uses `published_at` only (never `updated_at`).
- Calendar-year math: a post is “older than N years” when `published + N years <= today`. Exactly N years counts as older. Feb 29 rolls to Feb 28 in non-leap target years. Future publish dates are never stale.
- Post-answer block heading: `From my blog:` (not “Sources”). Facts file is never listed.
- One entry per post (dedupe by slug), score order, cap `max_sources` (default 3). Stale suffix: `older than N years, may be out of date`.
- Flat age rule for all posts (not only technical). Revisit if it looks wrong in practice.
- Chunk labels in the prompt use `Blog post: <title> | Published: YYYY-MM-DD` and, when stale, ` | Older than N years`.

## Alternatives considered

- Model-emitted markdown links — rejected (hallucinated URLs).
- Using `updated_at` — rejected (migration artifact).
- Different age rules for technical vs non-technical posts — deferred.

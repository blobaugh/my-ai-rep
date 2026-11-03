# Fenced code whitespace is opaque

**Status:** Accepted  
**Date:** 2026-10-15  
**Issue:** BENBOT-3

## Decision

Do **not** repair or reformat whitespace inside fenced code blocks produced from HTML `<pre>` / Lexical `code` nodes.

## Context

Migrated WordPress posts often have unreliable code formatting from older editors. A concrete example is the nginx config in “How to Make a Domain Proxy for Digital Ocean Spaces”, where directives run together on one line (e.g. `use_temp_path=off;server {`).

## Consequences

- Converter tests assert collapsed code whitespace is preserved as-is.
- Readers may see messy fences; fixing that is a separate editorial/migration task, not ingest normalization.

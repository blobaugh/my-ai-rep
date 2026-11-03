# Public repository, private files

**Status:** Accepted
**Date:** 2026-11-02
**Issue:** BENBOT-17

## Decision

The code is published from a public git repository. The biography is not. `content/`, `data/` (including the index and saved eval results), `.env`, database files, `prompts/voice_samples.md`, and `tests/fixtures/qa_answers.json` stay off the remote. `.gitignore` is deny-by-default for those paths. Nothing private is deleted; it is only ignored.

`prompts/ben_system.md` is public on purpose. Hiding the system prompt is not the protection. Guards and verification are.

A checkout with no private files still runs. `CONTENT_DIR` defaults to `content`. When that file is missing, the loader uses `{stem}.example.md` in the same directory. `examples/` holds a fictional person (Avery Quinn), not Ben. The checkout directory name is not part of the program.

`scripts/check_public_safe.sh` and `.githooks/pre-commit` refuse a staged private path or a high-confidence secret pattern. `gitleaks` is not installed in this environment, so the script uses those patterns directly. Enable the hook with `git config core.hooksPath .githooks`.

No license was chosen. The README says the license is to be decided before publishing.

## Why

The repository is public (architecture D16). Family details, the blog corpus, eval transcripts, the vector index, and API settings must not be in git history. A fresh clone still needs a way to exercise the pipeline, so the sample files are fictional and committed.

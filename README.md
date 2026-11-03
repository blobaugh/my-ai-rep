# BenBot

An AI that speaks as the person who runs it. Their facts come from the content files. Extra instructions go in `prompts/system.md`. `BOT_NAME` and `HUMAN_NAME` in `.env` fill the greeting and the fixed replies.

## Requirements

- **Python 3.9+** (the current Mac/Xcode toolchain ships 3.9.6; that is the floor this repo targets)
- A `.env` file (see `.env.example`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# or: pip install python-dotenv openai pytest ruff
```

## Knowledge

```bash
python -m src.qa                  # → data/chunks/qa_chunks.jsonl and facts_chunks.jsonl
python -m src.index_chunks        # → data/index/{vectors.npy,index.json}
python -m src.retrieve "What does AI-first mean to you?" --sources qa
python -m eval.run_retrieval_eval
python -m eval.run_qa_retrieval_eval
python -m src.chat
python -m src.chat --debug
python -m eval.run_guardrail_eval --sources qa
python -m eval.compare_runs data/eval/guardrail_*.json
```

`content/` and `data/` are gitignored (private local corpus). Set the embedding vars in `.env` (see `.env.example`). Put a link in a Q&A or facts entry when you want the bot to be able to repeat that exact URL.

### Q&A knowledge file

Curated first-person answers live in private `content/qa.md` (not committed). Format:

```md
## entry-id
Q: Visitor-facing question
A: First-person answer (may span lines)
source: bookkeeping only — never shown to the model
review: draft | approved
```

Fictional samples are committed under `examples/` (`about-ben.example.md`, `facts.example.md`, `qa.example.md`). They describe Avery Quinn. Copy them to `content/` without the `.example` suffix, replace with your own entries, then `python -m src.qa && python -m src.index_chunks`. A facts file may be named `about.md` or `about-ben.md`.

A checkout that has no `content/` directory can run against the samples:

```bash
CONTENT_DIR=examples QA_MODE=stuff RETRIEVAL_SOURCES=none python -m src.chat --ask "Who are you?"
```

`CONTENT_DIR` defaults to `content`. The loader uses `{name}.md` in that directory, then `{name}.example.md`.

`RETRIEVAL_SOURCES` selects which indexed source types are searched (`qa` and `facts`). `QA_MODE=stuff` puts every Q&A entry in the system prompt instead of retrieving them.

### Chat context window

Stock `llama3.1:8b` under Ollama effectively runs at **~2048** tokens and can truncate the *start* of the prompt (dropping rules). The measurement is in `docs/decisions/008-context-window.md`.

Create a derived model (repo-root `Modelfile`, `num_ctx 8192`) and point `LLM_MODEL` at it:

```bash
ollama create rep-llama -f Modelfile
# LLM_MODEL=rep-llama in .env
```

Verify the effective context. `ollama show rep-llama` should list `num_ctx 8192`.

Chat, retrieval, indexing, and evals all read settings from `src/config.py` (the only reader of `.env`). `python -m src.chat` prints them at startup. Commands: `/reset`, `/quit`, `/help`. `python -m src.chat --ask "question"` answers once with no history. `--debug` adds the retrieval list.

`CONTEXT_BUDGET_TOKENS` (default 7000) keeps each request under the measured window (history drops first, then lowest-ranked chunks).

## Tests

```bash
pytest
```

`pyproject.toml` sets `pythonpath = ["."]` so plain `pytest` works without `python -m`. Integration tests that hit Ollama: `RUN_INTEGRATION=1 pytest -m integration`.

Tests that need private `content/` files or `prompts/voice_samples.md` skip when those files are absent.

## Public git

Private paths (`.env`, `content/`, `data/`, voice samples, the Q&A answer fixture) are gitignored. They are not deleted. Before the first push, run `scripts/check_public_safe.sh`. Enable the hook in a clone:

```bash
git config core.hooksPath .githooks
```

`gitleaks` is not part of this check. The script matches private paths and high-confidence secret patterns.

## License

MIT. See `LICENSE`.

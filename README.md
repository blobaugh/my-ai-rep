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
python -m src.retrieve "What does AI-first mean to you?"
python -m eval.run_retrieval_eval
python -m eval.run_qa_retrieval_eval
python -m src.chat
python -m src.chat --debug
python -m eval.run_guardrail_eval
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

Fictional samples are committed under `examples/` (`about.example.md`, `hobby.example.md`, `facts.example.md`, `qa.example.md`). They describe Avery Quinn. Copy `about.example.md` to `content/about.md` and the other samples to `content/` without the `.example` suffix, replace them with your own writing, then `python -m src.qa && python -m src.index_chunks`.

`content/about.md` is sent on every turn. Every other markdown file under `content/` is searched. A file with `##` entry ids and `Q:` lines is optional Q&A. Any other file is split on headings and searched as prose. The closest `RETRIEVAL_K` passages (default 4) go in the user message.

A checkout that has no `content/` directory can run against the samples:

```bash
CONTENT_DIR=examples python -m src.chat --ask "Who are you?"
```

`CONTENT_DIR` defaults to `content`. The about file is `{dir}/about.md`, then `{dir}/about.example.md`.

### Chat context window

Stock `llama3.1:8b` under Ollama effectively runs at **~2048** tokens and can truncate the *start* of the prompt (dropping rules). The measurement is in `docs/decisions/008-context-window.md`.

Create a derived model (repo-root `Modelfile`, `num_ctx 8192`) and point `LLM_MODEL` at it:

```bash
ollama create rep-llama -f Modelfile
# LLM_MODEL=rep-llama in .env
```

Verify the effective context. `ollama show rep-llama` should list `num_ctx 8192`.

Chat, retrieval, indexing, and evals all read settings from `src/config.py` (the only reader of `.env`). `python -m src.chat` prints them at startup. Commands: `/reset`, `/quit`, `/help`. `python -m src.chat --ask "question"` answers once with no history. `--debug` adds the retrieval list, `category`, `flags`, `top_score`, `connection_used`, and `failover_active`.

### Chat connections

| Name | Default | Meaning |
|---|---|---|
| LLM_BASE_URL | http://localhost:11434/v1 | primary chat endpoint when `LLM_PRIMARY_*` is unset |
| LLM_API_KEY | ollama | primary key; masked when printed |
| LLM_MODEL | llama3.1:8b | primary model |
| LLM_PRIMARY_BASE_URL, LLM_PRIMARY_API_KEY, LLM_PRIMARY_MODEL | unset | optional group that replaces the three names above |
| LLM_PRIMARY_TIMEOUT_SECONDS | 120 | total time for one primary call |
| LLM_SECONDARY_BASE_URL, LLM_SECONDARY_API_KEY, LLM_SECONDARY_MODEL | unset | optional backup connection; set all three or none |
| LLM_SECONDARY_TIMEOUT_SECONDS | 120 | total time for one secondary call |
| FAILOVER_RETRY_SECONDS | 300 | how long to stay on the secondary before trying the primary once |
| FAILOVER_ON_HTTP_STATUS | unset | extra HTTP statuses that fail over. 429 and every 5xx already fail over |
| WEAK_RETRIEVAL_SCORE | unset | flag `weak_retrieval` when the best sent passage scores below this. Unset disables the flag |

A blank value means unset. The connect timeout is 5 seconds and is not a setting. Failover runs on a connection failure, a timeout, HTTP 429, or any 5xx. Other HTTP errors stay on the connection that returned them unless their status is listed. The embedder does not fail over. See `docs/decisions/016-llm-failover.md`.

`CONTEXT_BUDGET_TOKENS` (default 7000) keeps each request under the measured window (history drops first, then lowest-ranked chunks).

### Session log

| Name | Default | Meaning |
|---|---|---|
| DB_PATH | data/benbot.sqlite | SQLite file for sessions and the exchange log |
| SESSION_IDLE_MINUTES | 60 | after this long with no accepted message, the next one starts a new session |
| SESSION_MAX_MESSAGES | 50 | visitor messages accepted into one session. The next one is stored as `session_full` |

The cap counts visitor messages that were accepted for an answer. Deleting a session removes it from this file only. Copies already in backups stay. See `docs/decisions/018-sqlite-store.md`.

The HTTP API is `python -m src.api` (one worker, routes under `/api`). See `docs/web/api.md`.

The chat page is static files in `web/`. For UI work without a model:

```bash
python web/dev/mock_api.py
```

Open `http://127.0.0.1:8765/` and `http://127.0.0.1:8765/embed`. Magic messages such as `!full` and `!down` show the error states. See `docs/decisions/020-plain-chat-ui.md`.

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

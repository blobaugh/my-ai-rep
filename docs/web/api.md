# HTTP API

The process serves every route under `/api`. A proxy in front must forward that prefix unchanged. Start one worker:

```bash
python -m src.api
```

It listens on `127.0.0.1:8000`. One worker because failover state lives in the process. The model call runs in a thread so `/api/health` can still answer while a chat turn is in progress.

`answer_turn` is the only answer path. The client sends a message and, after the first reply, a session id. It does not send history.

## POST /api/chat

```bash
curl -s -X POST localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"Who is Avery?"}'
```

```json
{
  "session_id": "server-generated",
  "reply": "...",
  "status": "ok",
  "session": {"messages_used": 1, "messages_max": 50}
}
```

A second message uses the returned id:

```bash
curl -s -X POST localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"session_id":"SERVER_ID","message":"Say more about that"}'
```

An unknown or expired id is not an error. The response carries a new server id. A client-supplied unknown string is never stored as the id.

| status | HTTP | When |
|---|---|---|
| ok | 200 | The reply is the pipeline reply |
| session_full | 409 | The session already has `SESSION_MAX_MESSAGES` accepted visitor messages |
| unavailable | 503 | The chat model or the embedder did not answer |
| invalid | 400 | Empty, longer than `MESSAGE_MAX_CHARS`, or a body that cannot be read |
| error | 500 | The turn failed for another reason |
| busy | 429 | `MAX_CONCURRENT_TURNS` slots are full (`src/api/limits.py`) |
| daily_limit | 429 | UTC-day cap reached (`DAILY_MESSAGE_CAP`; persisted in SQLite) |

`session_full` asks the visitor to start a new chat. `unavailable` says the model is not available right now. Extra JSON fields, including any `history` field, are ignored.

## GET /api/config

Public and cacheable for 60 seconds.

```bash
curl -s localhost:8000/api/config
```

```json
{
  "ai_label": "Bot is an AI that speaks for the person I represent.",
  "opening_message": "Hi, I'm Bot, an AI that speaks for the person I represent. Ask me anything about them.",
  "logging_notice": "Conversations are logged and kept to improve the bot, and messages are processed by AI model providers. Please don't share personal information.",
  "max_message_chars": 1000,
  "session_max_messages": 50,
  "contact_url": ""
}
```

The label and opening are built from `BOT_NAME` and `HUMAN_NAME` unless `AI_LABEL` or `OPENING_MESSAGE` is set. The notice is the sentence above unless `LOGGING_NOTICE` is set. The wording always says this is an AI.

## GET /api/health

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/health
```

`200` and `{"status":"ok"}` when the process, the database, and the index files are present. Otherwise `503` and `{"status":"unavailable"}`. This route does not call a model and does not describe infrastructure.

`python -m src.health` prints the detailed report: database, index entry count, embed model, content files, each connection, and `failover_active`.

## CORS

Off unless `CORS_ALLOWED_ORIGINS` lists origins such as `https://example.com`. `*` is rejected at startup.

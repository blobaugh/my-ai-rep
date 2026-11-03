"""Stand-alone mock of /api/config and /api/chat. Standard library only.

Magic messages, matched after the same control-character strip as the API:

- !full  session_full 409
- !down  unavailable 503
- !busy  busy 429
- !limit daily_limit 429
- !error error 500
- !bad   invalid 400
- !expire a new session id
- !xss  a reply that must be shown as text
- anything else  ok 200
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
XSS_REPLY = "<img src=x onerror=alert(1)><script>alert(1)</script>"

CONFIG: dict[str, Any] = {
    "ai_label": "Bot is an AI that speaks for the person I represent.",
    "opening_message": (
        "Hi, I'm Bot, an AI that speaks for the person I represent. "
        "Ask me anything about them."
    ),
    "logging_notice": (
        "Conversations are logged and kept to improve the bot, and messages "
        "are processed by AI model providers. Please don't share personal information."
    ),
    "max_message_chars": 1000,
    "session_max_messages": 50,
    "contact_url": "https://example.com/contact",
}

PAGES = {"/": "index.html", "/embed": "embed.html"}


def strip_controls(text: str) -> str:
    kept: list[str] = []
    for char in text:
        code = ord(char)
        if (code in {9, 10, 13} or code >= 32) and code != 127:
            kept.append(char)
    return "".join(kept)


def chat_result(message: str, session_id: str | None) -> tuple[int, dict[str, Any]]:
    """Return the HTTP status and the JSON body for one mock turn."""
    cleaned = strip_controls(message)
    current = session_id or ""
    if not cleaned.strip():
        return _body(400, "invalid", "Please enter a message.", current or None)
    if len(cleaned) > int(CONFIG["max_message_chars"]):
        return _body(400, "invalid", "That message is too long. Please shorten it.", current or None)
    if cleaned == "!full":
        return _body(409, "session_full", "This chat is full. Start a new chat to keep going.", current or "full-session")
    if cleaned == "!down":
        return _body(503, "unavailable", "The model is not available right now. Please try again in a moment.", current or "down-session")
    if cleaned == "!busy":
        return _body(429, "busy", "BenBot is busy right now. Please try again in a moment.", current or "busy-session")
    if cleaned == "!limit":
        return _body(429, "daily_limit", "BenBot has reached today's message limit. Please try again tomorrow.", current or "limit-session")
    if cleaned == "!error":
        return _body(500, "error", "Something went wrong. Please try again in a moment.", current or "error-session")
    if cleaned == "!bad":
        return _body(400, "invalid", "That request could not be read.", current or None)
    if cleaned == "!xss":
        return _body(200, "ok", XSS_REPLY, current or "xss-session")
    if cleaned == "!expire":
        nxt = "minted-session-b" if current == "minted-session-a" else "minted-session-a"
        if nxt == current:
            nxt = "minted-session-b"
        return _body(200, "ok", "This reply is in a new conversation.", nxt)
    return _body(200, "ok", "This is a mock reply.", current or "mock-session")


def _body(
    http_status: int,
    status: str,
    reply: str,
    session_id: str | None,
) -> tuple[int, dict[str, Any]]:
    usage = None
    if session_id:
        usage = {"messages_used": 1, "messages_max": int(CONFIG["session_max_messages"])}
    return http_status, {
        "session_id": session_id,
        "reply": reply,
        "status": status,
        "session": usage,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "BenBotMock/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s\n" % (fmt % args))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            self._json(200, CONFIG)
            return
        if path == "/api/health":
            self._json(200, {"status": "ok"})
            return
        name = PAGES.get(path)
        if name is None and path.startswith("/") and path != "/":
            name = path.lstrip("/")
        self._file(name)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._json(404, {"status": "invalid", "reply": "Not found.", "session_id": None, "session": None})
            return
        length = int(self.headers.get("content-length") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
            status, body = _body(400, "invalid", "That request could not be read.", None)
            self._json(status, body)
            return
        supplied = payload.get("session_id")
        session_id = supplied if isinstance(supplied, str) else None
        status, body = chat_result(payload["message"], session_id)
        self._json(status, body)

    def _file(self, name: str | None) -> None:
        if not name:
            self.send_error(404)
            return
        candidate = (ROOT / name).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        data = candidate.read_bytes()
        kind = "text/plain; charset=utf-8"
        if candidate.suffix == ".html":
            kind = "text/html; charset=utf-8"
        elif candidate.suffix == ".css":
            kind = "text/css; charset=utf-8"
        elif candidate.suffix == ".js":
            kind = "text/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock chat http://127.0.0.1:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()

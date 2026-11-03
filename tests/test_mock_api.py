"""The development mock returns each chat status without a model."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mock_api", ROOT / "web" / "dev" / "mock_api.py")
assert SPEC and SPEC.loader
mock_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mock_api)


def test_magic_messages_cover_each_status() -> None:
    cases = {
        "!full": (409, "session_full"),
        "!down": (503, "unavailable"),
        "!busy": (429, "busy"),
        "!limit": (429, "daily_limit"),
        "!error": (500, "error"),
        "!bad": (400, "invalid"),
        "Hello": (200, "ok"),
    }
    for message, expected in cases.items():
        status, body = mock_api.chat_result(message, "sess")
        assert (status, body["status"]) == expected
        assert body["session_id"] == "sess"
        assert isinstance(body["reply"], str) and body["reply"]


def test_expire_mints_a_different_id() -> None:
    status, body = mock_api.chat_result("!expire", "sess")
    assert status == 200
    assert body["status"] == "ok"
    assert body["session_id"] != "sess"
    again, second = mock_api.chat_result("!expire", body["session_id"])
    assert again == 200
    assert second["session_id"] != body["session_id"]


def test_xss_reply_is_literal_text() -> None:
    status, body = mock_api.chat_result("!xss", None)
    assert status == 200
    assert "<script>" in body["reply"]
    assert "<img" in body["reply"]


def test_mock_source_stays_on_the_standard_library() -> None:
    tree = ast.parse((ROOT / "web" / "dev" / "mock_api.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= {"__future__", "json", "sys", "http", "pathlib", "typing", "urllib"}

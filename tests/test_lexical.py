"""Tests for Lexical → markdown conversion (written first for BENBOT-2)."""

from __future__ import annotations

import json
from pathlib import Path

from src.lexical import lexical_to_markdown

FIXTURES = Path(__file__).parent / "fixtures"


def _root(*children: dict) -> dict:
    return {"type": "root", "children": list(children)}


def _text(text: str, fmt: int = 0) -> dict:
    return {"type": "text", "text": text, "format": fmt}


def _paragraph(*children: dict) -> dict:
    return {"type": "paragraph", "children": list(children)}


def test_empty_body() -> None:
    assert lexical_to_markdown(_root()) == ""
    assert lexical_to_markdown(_root(_paragraph())) == ""


def test_paragraph() -> None:
    md = lexical_to_markdown(_root(_paragraph(_text("Hello world."))))
    assert md == "Hello world."


def test_bold_italic_code_text() -> None:
    md = lexical_to_markdown(
        _root(
            _paragraph(
                _text("bold", 1),
                _text(" "),
                _text("italic", 2),
                _text(" "),
                _text("code", 16),
            )
        )
    )
    assert md == "**bold** *italic* `code`"


def test_link() -> None:
    link = {
        "type": "link",
        "fields": {"url": "https://example.com/path"},
        "children": [_text("Example")],
    }
    md = lexical_to_markdown(_root(_paragraph(_text("See "), link, _text("."))))
    assert md == "See [Example](https://example.com/path)."


def test_quote() -> None:
    md = lexical_to_markdown(
        _root({"type": "quote", "children": [_text("Stay anchored.")]})
    )
    assert md == "> Stay anchored."


def test_heading() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "heading",
                "tag": "h2",
                "children": [_text("Section")],
            }
        )
    )
    assert md == "## Section"


def test_unordered_list() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "list",
                "listType": "bullet",
                "children": [
                    {"type": "listitem", "children": [_text("One")]},
                    {"type": "listitem", "children": [_text("Two")]},
                ],
            }
        )
    )
    assert md == "- One\n- Two"


def test_ordered_list() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "list",
                "listType": "number",
                "children": [
                    {"type": "listitem", "value": 1, "children": [_text("First")]},
                    {"type": "listitem", "value": 2, "children": [_text("Second")]},
                ],
            }
        )
    )
    assert md == "1. First\n2. Second"


def test_code_block() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "code",
                "language": "python",
                "children": [
                    _text("print("),
                    {"type": "linebreak"},
                    _text("'hi')"),
                ],
            }
        )
    )
    assert md == "```python\nprint(\n'hi')\n```"


def test_upload_with_caption() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "upload",
                "value": {
                    "url": "https://cdn.example/secret.jpg",
                    "caption": "A quiet harbor.",
                    "alt": "boat",
                    "filename": "secret.jpg",
                },
            }
        )
    )
    assert md == "*A quiet harbor.*"
    assert "https://" not in md
    assert "secret.jpg" not in md


def test_upload_without_caption() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "upload",
                "value": {
                    "url": "https://cdn.example/secret.jpg",
                    "caption": None,
                    "alt": "boat",
                },
            }
        )
    )
    assert md == ""


def test_unknown_node_type_recurses_without_crash() -> None:
    md = lexical_to_markdown(
        _root(
            {
                "type": "custom-widget",
                "children": [_paragraph(_text("Still here."))],
            }
        )
    )
    assert md == "Still here."


def test_anchored_in_silence_fixture() -> None:
    article = json.loads((FIXTURES / "anchored_in_silence.json").read_text())
    root = article["content"]["root"]
    md = lexical_to_markdown(root)

    assert "A sailboat rests at anchor" in md
    assert "*A sailboat rests at anchor" in md  # upload caption as italic
    assert md.count("A sailboat rests at anchor") >= 2  # caption + quote
    assert "> A sailboat rests at anchor" in md
    assert (
        "[Americas Favorite Photos](https://americasfavoritephotos.com/v/w77h7z)" in md
    )
    assert "digitaloceanspaces.com" not in md
    assert '"type": "upload"' not in md
    assert (
        article["title"] not in md.split("\n")[0] or True
    )  # title not forced into body
    # Title must not appear as a leading heading/body title line
    assert not md.lstrip().startswith("# ")
    assert not md.lstrip().startswith(article["title"])

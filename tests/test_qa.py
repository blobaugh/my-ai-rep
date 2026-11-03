"""Unit tests for Q&A parsing and chunk conversion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from src.prompt import build_messages, format_chunk_label
from src.qa import (
    QAParseError,
    entry_to_chunk,
    make_qa_embed_text,
    parse_qa,
    stuff_qa_into_system,
)

SAMPLE = """## one
Q: What is your name?
A: My name is Example.
source: interview
review: draft

## two
Q: Hobby?
A: Line one of the answer.
Line two still in the answer.
source: blog
review: approved
"""


def test_parse_happy_path_and_multiline_answer() -> None:
    entries = parse_qa(SAMPLE)
    assert len(entries) == 2
    assert entries[0].id == "one"
    assert entries[0].question == "What is your name?"
    assert entries[0].answer == "My name is Example."
    assert entries[1].answer == "Line one of the answer.\nLine two still in the answer."


def test_example_qa_file_parses() -> None:
    path = Path("examples/qa.example.md")
    entries = parse_qa(path.read_text(encoding="utf-8"))
    assert len(entries) >= 1
    assert all(entry.answer.strip() for entry in entries)


def test_parse_real_qa_file_has_27_entries() -> None:
    path = Path("content/qa.md")
    if not path.is_file():
        pytest.skip("content/qa.md not present")
    entries = parse_qa(path.read_text(encoding="utf-8"))
    assert len(entries) == 27
    assert entries[0].id == "intro"
    assert entries[-1].id == "about-benbot"


def test_duplicate_id() -> None:
    text = SAMPLE + "\n## one\nQ: x\nA: y\nsource: z\nreview: draft\n"
    with pytest.raises(QAParseError, match="duplicate"):
        parse_qa(text)


def test_missing_a() -> None:
    text = "## one\nQ: only question\nsource: x\nreview: draft\n"
    with pytest.raises(QAParseError, match="missing A|unexpected line"):
        parse_qa(text)


def test_empty_answer() -> None:
    text = "## one\nQ: q\nA:   \nsource: x\nreview: draft\n"
    with pytest.raises(QAParseError, match="empty answer"):
        parse_qa(text)


def test_text_before_first_heading() -> None:
    text = "preamble\n\n" + SAMPLE
    with pytest.raises(QAParseError, match="before the first"):
        parse_qa(text)


def test_chunk_record_shape_and_embed_modes() -> None:
    entry = parse_qa(SAMPLE)[0]
    chunk = entry_to_chunk(entry, embed_mode="question_and_answer")
    assert chunk["id"] == "qa#one"
    assert chunk["title"] == entry.question
    assert chunk["slug"] == "one"
    assert chunk["published_at"] == ""
    assert chunk["source_type"] == "qa"
    assert chunk["body"] == entry.answer
    assert chunk["word_count"] == 4
    assert "content_hash" in chunk
    assert chunk["embed_text"] == make_qa_embed_text(
        entry.question, entry.answer, mode="question_and_answer"
    )
    only_q = entry_to_chunk(entry, embed_mode="question_only")
    assert only_q["embed_text"] == entry.question
    assert only_q["body"] == entry.answer


def test_qa_answer_reaches_prompt_unchanged() -> None:
    entry = parse_qa(SAMPLE)[0]

    @dataclass(frozen=True)
    class C:
        id: str
        title: str
        body: str
        published_at: str
        score: float
        source_type: str = "qa"

    chunk = C(
        id="qa#one",
        title=entry.question,
        body=entry.answer,
        published_at="",
        score=0.9,
        source_type="qa",
    )
    messages = build_messages(
        system_prompt="SYS",
        history=[],
        question="What is your name?",
        chunks=[chunk],
        today=date(2024, 1, 1),
        stale_years=3,
    )
    assert entry.answer in messages[-1]["content"]
    assert "Ben's own answer to:" in messages[-1]["content"]
    label = format_chunk_label(
        entry.question,
        "",
        today=date(2024, 1, 1),
        stale_years=3,
        source_type="qa",
    )
    assert label == f"Ben's own answer to: {entry.question}"
    assert "Older than" not in label


def test_stuff_budget_rejects_when_too_large() -> None:
    entries = parse_qa(SAMPLE)
    prompt, used, fitted = stuff_qa_into_system("SYS", entries, budget_tokens=1)
    assert prompt == "SYS"
    assert used == []
    assert fitted is False
    prompt2, used2, fitted2 = stuff_qa_into_system(
        "SYS", entries, budget_tokens=100_000
    )
    assert fitted2 is True
    assert len(used2) == 2
    assert entries[0].answer in prompt2

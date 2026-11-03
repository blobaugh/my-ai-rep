"""Parse curated Q&A knowledge and convert entries to chunk records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.chunking import word_count

QA_PATH = Path("content/qa.md")
FACTS_PATH = Path("content/facts.md")
QA_CHUNKS_PATH = Path("data/chunks/qa_chunks.jsonl")
FACTS_CHUNKS_PATH = Path("data/chunks/facts_chunks.jsonl")
QA_EMBED_MODES = ("question_and_answer", "question_only", "multi")
QaEmbedMode = Literal["question_and_answer", "question_only", "multi"]
# Question vectors use the document prefix. BENBOT-14 measured query vs
# document; document won. See docs/decisions/013-multi-vector-qa.md.
Q_VECTOR_PREFIX_KIND = "document"
REVIEW_VALUES = frozenset({"draft", "approved"})
ENTRY_SOURCE_TYPES = frozenset({"qa", "facts"})

ENTRY_HEADING_RE = re.compile(r"^##\s+(\S+)\s*$")
FIELD_Q_RE = re.compile(r"^Q:\s*(.*)$")
FIELD_A_RE = re.compile(r"^A:\s*(.*)$")
FIELD_SOURCE_RE = re.compile(r"^source:\s*(.*)$")
FIELD_REVIEW_RE = re.compile(r"^review:\s*(.*)$")


class QAParseError(ValueError):
    """Malformed Q&A file; includes a 1-based line number when known."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        if line is not None:
            super().__init__(f"line {line}: {message}")
        else:
            super().__init__(message)


@dataclass(frozen=True)
class QAEntry:
    """One curated question/answer pair."""

    id: str
    question: str
    answer: str
    source: str
    review: str


def content_hash(text: str) -> str:
    """Stable hash for change detection (answer body for Q&A chunks)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_qa_embed_text(
    question: str, answer: str, *, mode: QaEmbedMode
) -> str:
    """Build the single-vector text embedded for a Q&A or facts entry.

    ``multi`` still stores the question-plus-answer string on the chunk row.
    Indexing expands that row into one vector per phrasing plus this text.
    """
    if mode == "question_only":
        return question
    if mode in {"question_and_answer", "multi"}:
        return f"Q: {question}\nA: {answer}"
    raise ValueError(f"unknown QA_EMBED_MODE: {mode!r}")


def split_phrasings(question: str) -> list[str]:
    """Split a Q line on `` / `` and on ``? `` boundaries.

    The question mark stays on the phrasing it belongs to.
    """
    phrasings: list[str] = []
    for part in question.split(" / "):
        part = part.strip()
        if not part:
            continue
        for piece in re.split(r"(?<=\?)\s+", part):
            piece = piece.strip()
            if piece:
                phrasings.append(piece)
    if not phrasings:
        raise ValueError(f"question has no phrasings: {question!r}")
    return phrasings


def entry_to_chunk(
    entry: QAEntry,
    *,
    embed_mode: QaEmbedMode = "question_and_answer",
    source_type: str = "qa",
) -> dict[str, Any]:
    """Convert one entry to the shared chunk JSONL shape."""
    if source_type not in ENTRY_SOURCE_TYPES:
        raise ValueError(f"source_type must be qa or facts, got {source_type!r}")
    body = entry.answer
    return {
        "id": f"{source_type}#{entry.id}",
        "content_hash": content_hash(f"{entry.question}\n{body}"),
        "title": entry.question,
        "slug": entry.id,
        "published_at": "",
        "section": "",
        "url": "",
        "source_type": source_type,
        "body": body,
        "embed_text": make_qa_embed_text(
            entry.question, entry.answer, mode=embed_mode
        ),
        "word_count": word_count(body),
    }


def expand_multi_vectors(
    chunks: list[dict[str, Any]], *, q_embed_kind: str
) -> list[dict[str, Any]]:
    """One vector per phrasing plus one question-plus-answer vector.

    Blog rows pass through. Each new row keeps the entry body and stores
    ``entry_id``, ``kind`` (``q`` or ``qa``), the phrasing, and its hash.
    """
    if q_embed_kind not in {"query", "document"}:
        raise ValueError(f"q_embed_kind must be query or document, got {q_embed_kind!r}")
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if str(chunk.get("source_type", "")) not in ENTRY_SOURCE_TYPES:
            out.append(chunk)
            continue
        question = str(chunk.get("title") or "")
        answer = str(chunk.get("body") or "")
        entry_id = str(chunk["id"])
        entry_hash = content_hash(f"{question}\n{answer}")
        for index, phrasing in enumerate(split_phrasings(question)):
            row = dict(chunk)
            row["id"] = f"{entry_id}#q{index}"
            row["entry_id"] = entry_id
            row["kind"] = "q"
            row["phrasing"] = phrasing
            row["content_hash"] = content_hash(phrasing)
            row["entry_content_hash"] = entry_hash
            row["embed_text"] = phrasing
            row["embed_kind"] = q_embed_kind
            out.append(row)
        qa_text = make_qa_embed_text(question, answer, mode="question_and_answer")
        qa_row = dict(chunk)
        qa_row["id"] = f"{entry_id}#qa"
        qa_row["entry_id"] = entry_id
        qa_row["kind"] = "qa"
        qa_row["phrasing"] = qa_text
        qa_row["content_hash"] = content_hash(qa_text)
        qa_row["entry_content_hash"] = entry_hash
        qa_row["embed_text"] = qa_text
        qa_row["embed_kind"] = "document"
        out.append(qa_row)
    return out


def parse_qa(text: str) -> list[QAEntry]:
    """Parse a Q&A markdown file into entries. Raises QAParseError on bad input."""
    lines = text.splitlines()
    # Find first heading; reject preamble.
    first_heading: int | None = None
    for i, line in enumerate(lines):
        if ENTRY_HEADING_RE.match(line):
            first_heading = i
            break
        if line.strip():
            raise QAParseError(
                "text before the first ## entry heading is not allowed",
                line=i + 1,
            )
    if first_heading is None:
        raise QAParseError("no ## entry headings found")

    entries: list[QAEntry] = []
    seen_ids: set[str] = set()
    i = first_heading
    while i < len(lines):
        heading = ENTRY_HEADING_RE.match(lines[i])
        if not heading:
            raise QAParseError(
                "expected ## <entry-id> heading", line=i + 1
            )
        entry_id = heading.group(1)
        entry_start = i + 1
        if entry_id in seen_ids:
            raise QAParseError(f"duplicate entry id {entry_id!r}", line=i + 1)
        seen_ids.add(entry_id)
        i += 1

        question: str | None = None
        answer_parts: list[str] = []
        in_answer = False
        source: str | None = None
        review: str | None = None
        saw_a = False

        while i < len(lines) and not ENTRY_HEADING_RE.match(lines[i]):
            line = lines[i]
            q_match = FIELD_Q_RE.match(line)
            a_match = FIELD_A_RE.match(line)
            src_match = FIELD_SOURCE_RE.match(line)
            rev_match = FIELD_REVIEW_RE.match(line)

            if q_match and not in_answer and source is None and review is None:
                question = q_match.group(1).strip()
                in_answer = False
            elif a_match and question is not None and source is None and review is None:
                saw_a = True
                in_answer = True
                first = a_match.group(1)
                answer_parts = [first] if first else []
            elif src_match and saw_a:
                in_answer = False
                source = src_match.group(1).strip()
            elif rev_match and saw_a and source is not None:
                in_answer = False
                review = rev_match.group(1).strip()
            elif in_answer:
                answer_parts.append(line)
            elif line.strip() == "":
                pass
            else:
                raise QAParseError(
                    f"unexpected line in entry {entry_id!r}", line=i + 1
                )
            i += 1

        if question is None or not question.strip():
            raise QAParseError(
                f"entry {entry_id!r} missing non-empty Q:", line=entry_start
            )
        if not saw_a:
            raise QAParseError(
                f"entry {entry_id!r} missing A:", line=entry_start
            )
        answer = "\n".join(answer_parts).strip()
        if not answer:
            raise QAParseError(
                f"entry {entry_id!r} has empty answer", line=entry_start
            )
        if source is None:
            raise QAParseError(
                f"entry {entry_id!r} missing source:", line=entry_start
            )
        if review is None:
            raise QAParseError(
                f"entry {entry_id!r} missing review:", line=entry_start
            )
        if review not in REVIEW_VALUES:
            raise QAParseError(
                f"entry {entry_id!r} review must be draft|approved, got {review!r}",
                line=entry_start,
            )
        entries.append(
            QAEntry(
                id=entry_id,
                question=question.strip(),
                answer=answer,
                source=source,
                review=review,
            )
        )

    return entries


def format_stuffed_qa_section(entries: list[QAEntry]) -> str:
    """Format all Q&A answers for the system prompt (stuff mode)."""
    parts = ["Ben's own Q&A answers (use these directly in the first person):"]
    for entry in entries:
        parts.append(f"Q: {entry.question}\nA: {entry.answer}")
    return "\n\n".join(parts)


def stuff_qa_into_system(
    system_prompt: str,
    entries: list[QAEntry],
    *,
    budget_tokens: int,
    chars_per_token: int = 4,
) -> tuple[str, list[QAEntry], bool]:
    """Append Q&A to the system prompt while respecting a token budget.

    Returns (system_prompt, entries_included, fitted).
    If the full set does not fit, includes none and fitted=False.
    """
    if not entries:
        return system_prompt, [], True
    block = format_stuffed_qa_section(entries)
    combined = f"{system_prompt.rstrip()}\n\n{block}\n"
    est = (len(combined) + chars_per_token - 1) // chars_per_token
    if budget_tokens > 0 and est > budget_tokens:
        return system_prompt, [], False
    return combined, list(entries), True


def write_qa_chunks(
    entries: list[QAEntry],
    path: Path = QA_CHUNKS_PATH,
    *,
    embed_mode: QaEmbedMode = "question_and_answer",
    source_type: str = "qa",
) -> int:
    """Write entry chunk records to JSONL. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            entry_to_chunk(e, embed_mode=embed_mode, source_type=source_type),
            ensure_ascii=False,
        )
        for e in entries
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def write_knowledge_chunks(embed_mode: QaEmbedMode | str) -> tuple[int, int]:
    """Write ``qa_chunks.jsonl`` and, when present, ``facts_chunks.jsonl``."""
    if embed_mode not in QA_EMBED_MODES:
        raise ValueError(f"QA_EMBED_MODE must be one of {QA_EMBED_MODES}, got {embed_mode!r}")
    mode: QaEmbedMode = embed_mode  # type: ignore[assignment]
    from src.config import load_settings, select_content_path

    settings = load_settings()
    qa_path = select_content_path(QA_PATH, "qa", settings)
    facts_path = select_content_path(FACTS_PATH, "facts", settings)
    qa_entries = parse_qa(qa_path.read_text(encoding="utf-8"))
    qa_count = write_qa_chunks(qa_entries, embed_mode=mode, source_type="qa")
    facts_count = 0
    if facts_path.is_file():
        facts_entries = parse_qa(facts_path.read_text(encoding="utf-8"))
        facts_count = write_qa_chunks(
            facts_entries,
            FACTS_CHUNKS_PATH,
            embed_mode=mode,
            source_type="facts",
        )
    return qa_count, facts_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse Q&A file into chunk JSONL")
    parser.add_argument(
        "--input",
        type=Path,
        default=QA_PATH,
        help="Path to qa.md (default: content/qa.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=QA_CHUNKS_PATH,
        help="Output JSONL path (default: data/chunks/qa_chunks.jsonl)",
    )
    args = parser.parse_args(argv)
    try:
        from src.config import load_settings

        mode = load_settings().qa_embed_mode
        if args.input != QA_PATH or args.output != QA_CHUNKS_PATH:
            text = args.input.read_text(encoding="utf-8")
            entries = parse_qa(text)
            n = write_qa_chunks(entries, args.output, embed_mode=mode)  # type: ignore[arg-type]
            facts_n = 0
        else:
            n, facts_n = write_knowledge_chunks(mode)
    except (OSError, QAParseError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {n} Q&A chunks to {args.output} (embed_mode={mode})")
    if facts_n:
        print(f"Wrote {facts_n} facts chunks to {FACTS_CHUNKS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

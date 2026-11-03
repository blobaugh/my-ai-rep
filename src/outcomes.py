"""Classify a finished turn in code. No model call and no marker from the model.

Categories are exactly one of answered, no_answer, off_topic, guard_identity,
or guard_override. The HTTP API may add unavailable and error later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.guards import match_guard, match_instruction_guard, persona_lines

MISSING_PREFIX = "I don't have that detail"
CATEGORIES = frozenset(
    {"answered", "no_answer", "off_topic", "guard_identity", "guard_override"}
)


@dataclass(frozen=True)
class RetrievedEntry:
    """One retrieved passage, whether or not it was sent to the model."""

    id: str
    source_type: str
    score: float
    phrasing: str
    sent: bool


@dataclass(frozen=True)
class TurnResult:
    """What the code decided about one turn. Callers still receive Answer."""

    reply: str
    category: str
    flags: tuple[str, ...]
    finish_reason: str | None
    guard_name: str | None
    guard_pattern: str | None
    repair: str
    verification_outcome: str
    retrieved: tuple[RetrievedEntry, ...]
    top_score: float | None
    connection_used: str | None
    failover_active: bool
    timings_ms: dict[str, int]
    prompt_tokens: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "category": self.category,
            "flags": list(self.flags),
            "finish_reason": self.finish_reason,
            "guard_name": self.guard_name,
            "guard_pattern": self.guard_pattern,
            "repair": self.repair,
            "verification_outcome": self.verification_outcome,
            "retrieved": [
                {
                    "id": entry.id,
                    "source_type": entry.source_type,
                    "score": entry.score,
                    "phrasing": entry.phrasing,
                    "sent": entry.sent,
                }
                for entry in self.retrieved
            ],
            "top_score": self.top_score,
            "connection_used": self.connection_used,
            "failover_active": self.failover_active,
            "timings_ms": dict(self.timings_ms),
            "prompt_tokens": self.prompt_tokens,
        }


def classify_turn(
    question: str,
    reply: str,
    *,
    human_name: str = "",
    bot_name: str = "",
    finish_reason: str | None = None,
    repair: str = "none",
    failover_active: bool = False,
    retrieved: list[dict[str, Any]] | None = None,
    weak_retrieval_score: float | None = None,
    verification: dict[str, Any] | None = None,
    timings: dict[str, Any] | None = None,
    prompt_tokens: int | None = None,
    connection_used: str | None = None,
) -> TurnResult:
    """Assign one category and any number of flags from the reply and the question."""
    lines = persona_lines(human_name, bot_name)
    guard = match_guard(question, human_name=human_name)
    text = reply.strip()
    if guard and guard[0] == "identity":
        category = "guard_identity"
        guard_name, guard_pattern = "identity", guard[1]
    elif guard and guard[0] == "override":
        category = "guard_override"
        guard_name, guard_pattern = "override", guard[1]
    elif text == lines.off_topic:
        category = "off_topic"
        guard_name, guard_pattern = None, None
    elif text == lines.missing or text.startswith(MISSING_PREFIX):
        category = "no_answer"
        guard_name, guard_pattern = None, None
    else:
        category = "answered"
        guard_name, guard_pattern = None, None

    entries = _entries(retrieved or [])
    sent_scores = [entry.score for entry in entries if entry.sent]
    top_score = max(sent_scores) if sent_scores else None
    flags: list[str] = []
    if (
        weak_retrieval_score is not None
        and top_score is not None
        and top_score < weak_retrieval_score
    ):
        flags.append("weak_retrieval")
    if repair == "prune":
        flags.append("repair_prune")
    elif repair == "retry":
        flags.append("repair_retry")
    elif repair == "fallback":
        flags.append("repair_fallback")
    if failover_active:
        flags.append("failover_used")
    if finish_reason == "length":
        flags.append("truncated")
    if category == "guard_override" or match_instruction_guard(question):
        flags.append("injection_suspect")

    if verification is None:
        verification_outcome = "none"
    elif verification.get("ok") is True:
        verification_outcome = "ok"
    else:
        verification_outcome = "failed"

    return TurnResult(
        reply=reply,
        category=category,
        flags=tuple(flags),
        finish_reason=finish_reason,
        guard_name=guard_name,
        guard_pattern=guard_pattern,
        repair=repair or "none",
        verification_outcome=verification_outcome,
        retrieved=tuple(entries),
        top_score=top_score,
        connection_used=connection_used,
        failover_active=failover_active,
        timings_ms=_timings_ms(timings or {}),
        prompt_tokens=prompt_tokens,
    )


def _entries(rows: list[dict[str, Any]]) -> list[RetrievedEntry]:
    entries: list[RetrievedEntry] = []
    for row in rows:
        entries.append(
            RetrievedEntry(
                id=str(row.get("id") or ""),
                source_type=str(row.get("source_type") or ""),
                score=float(row.get("score") or 0.0),
                phrasing=str(row.get("phrasing") or ""),
                sent=bool(row.get("sent")),
            )
        )
    return entries


def _timings_ms(timings: dict[str, Any]) -> dict[str, int]:
    def ms(key: str) -> int:
        value = timings.get(key)
        if not isinstance(value, (int, float)):
            return 0
        return round(float(value) * 1000)

    return {
        "embed": ms("embed"),
        "search": ms("search"),
        "model": ms("first_token"),
        "total": ms("total"),
    }

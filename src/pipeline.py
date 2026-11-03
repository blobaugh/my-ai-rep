"""One answer pipeline for chat, --ask, and every answer-producing eval."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.config import (
    Settings,
    indexed_source_types,
    prompt_hash,
    select_content_path,
    settings_hash,
    voice_samples_enabled,
)
from src.faithfulness import name_stopwords
from src.guards import exempt_replies, match_guard, persona_lines
from src.prompt import (
    ABOUT_PATH,
    apply_budget_guard,
    compose_retrieval_query,
    estimate_tokens,
    facts_for_prompt,
    filter_chunks_by_min_score,
    load_system_prompt,
    trim_history,
)
from src.qa import QA_PATH, parse_qa, stuff_qa_into_system
from src.retrieve import RetrievedChunk, retrieve_timed
from src.verify import (
    ENTRY_BREAK,
    corrective_note,
    minimum_kept,
    prune_flagged_sentences,
    split_sentences,
    starts_complete,
    verify_answer,
)

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
TOO_LONG = "That's a bit long for me. Could you shorten it?"
TROUBLE = "I'm having trouble thinking right now. Please try again in a moment."
TURN_LOG = Path("data/logs/turns.jsonl")
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class Answer:
    text: str
    sources_block: str
    debug: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None


def make_chat_client(settings: Settings) -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


def append_turn(
    history: Sequence[dict[str, str]],
    question: str,
    answer: str,
    history_turns: int,
) -> list[dict[str, str]]:
    """Store the plain question and answer. Never store chunks or sources."""
    updated = list(history)
    updated.append({"role": "user", "content": question})
    updated.append({"role": "assistant", "content": answer})
    return trim_history(updated, history_turns)


def answer_turn(
    question: str,
    history: Sequence[dict[str, str]],
    settings: Settings,
    *,
    clients: Any = None,
    retrieve_fn: Callable[..., list[RetrievedChunk]] | None = None,
    system_prompt: str | None = None,
    on_delta: Callable[[str], None] | None = None,
    qa_path: Path = QA_PATH,
) -> Answer:
    """Validate, retrieve, assemble, and call the model once."""
    started = time.perf_counter()
    if len(question) > MAX_MESSAGE_CHARS:
        answer = _skipped(settings, TOO_LONG, "invalid", question, started, reason="too_long")
        _log_turn(settings, question, answer)
        return answer
    cleaned = question.strip()
    if not cleaned:
        answer = _skipped(settings, "", "invalid", question, started, reason="empty")
        return answer
    lines = persona_lines(settings.human_name, settings.bot_name)
    guard = match_guard(cleaned, human_name=settings.human_name)
    if guard:
        kind, pattern = guard
        reply = lines.identity if kind == "identity" else lines.off_topic
        answer = _guarded(settings, started, pattern, reply)
        _log_turn(settings, cleaned, answer)
        return answer

    about_path = select_content_path(ABOUT_PATH, "about-ben", settings)
    qa_path = select_content_path(qa_path, "qa", settings)
    prompt_facts = ""
    if system_prompt is None and about_path.is_file():
        prompt_facts = facts_for_prompt(
            about_path.read_text(encoding="utf-8"), settings.facts_in_prompt
        )
    active_system, stuffed_knowledge, stuff_note = _maybe_stuff(
        settings, system_prompt, qa_path, about_path
    )
    query = compose_retrieval_query(
        history,
        cleaned,
        query_turns=settings.retrieval_query_turns,
        mode=settings.retrieval_query_mode,
    )
    source_types = indexed_source_types(settings)
    embed_s = 0.0
    search_s = 0.0
    chunks: list[RetrievedChunk] = []
    if source_types:
        chunks, embed_s, search_s = _search(
            query,
            settings,
            source_types,
            retrieve_fn=retrieve_fn,
        )
    chunks = filter_chunks_by_min_score(chunks, settings.retrieval_min_score)
    messages, used_chunks, budget_actions = apply_budget_guard(
        system_prompt=active_system,
        history=list(history),
        question=cleaned,
        chunks=chunks,
        budget_tokens=settings.context_budget_tokens,
        announce_no_match=settings.qa_mode != "stuff",
    )
    sent_ids = {c.id for c in used_chunks}
    retrieved = [
        {
            "id": c.id,
            "slug": c.slug,
            "score": c.score,
            "source_type": c.source_type,
            "sent": c.id in sent_ids,
            "kind": c.match_kind,
            "phrasing": c.match_phrasing,
        }
        for c in chunks
    ]
    if source_types and not chunks:
        logger.warning("zero entries were retrieved")

    model_error = ""
    usage: dict[str, Any] | None = None
    finish: str | None = None
    first_token = 0.0
    streamed = False
    try:
        text, usage, finish, first_token, streamed = _call_model(
            settings,
            messages,
            clients=clients,
            on_delta=on_delta,
        )
    except Exception as exc:  # noqa: BLE001 — visitor gets a fixed sentence
        logger.warning("model call failed: %s", exc)
        text = TROUBLE
        finish = "error"
        model_error = str(exc)

    if finish == "length":
        logger.warning(
            "finish_reason=length; reply may be truncated (LLM_MAX_TOKENS=%s)",
            settings.llm_max_tokens,
        )

    knowledge_text = _knowledge_text(prompt_facts, stuffed_knowledge, used_chunks)
    retry_used = False
    fallback_used = False
    retry_text = ""
    repair = "none"
    removed: list[str] = []
    model_calls = 1
    verification: dict[str, Any] | None = None
    # Streaming is unverified and only used when the caller passes on_delta.
    if on_delta is None and finish != "error":
        checked = _verify_or_fallback(
            text,
            knowledge_text,
            messages,
            chunks,
            settings,
            clients=clients,
            usage=usage,
            finish=finish,
            first_token=first_token,
        )
        text = checked.text
        usage = checked.usage
        finish = checked.finish
        first_token = checked.first_token
        verification = checked.verification
        retry_used = checked.retry_used
        fallback_used = checked.fallback_used
        retry_text = checked.retry_text
        repair = checked.repair
        removed = checked.removed
        model_calls = checked.model_calls

    debug = {
        "query_used": query,
        "retrieved": retrieved,
        "prompt_token_estimate": estimate_tokens(messages),
        "usage": usage,
        "finish_reason": finish,
        "timings": {
            "embed": embed_s,
            "search": search_s,
            "first_token": first_token,
            "total": time.perf_counter() - started,
        },
        "settings_hash": settings_hash(settings),
        "prompt_hash": prompt_hash(active_system),
        "streamed": streamed,
        "grounding_text": "\n\n".join(str(m.get("content", "")) for m in messages),
        "knowledge_text": knowledge_text,
        "budget_actions": budget_actions,
        "stuff_note": stuff_note,
        "error": model_error or None,
        "zero_retrieved": bool(source_types) and not chunks,
        "verification": verification,
        "retry_used": retry_used,
        "fallback_used": fallback_used,
        "retry_text": retry_text,
        "repair": repair,
        "removed_sentences": removed,
        "model_calls": model_calls,
    }
    answer = Answer(text=text, sources_block="", debug=debug, finish_reason=finish)
    _log_turn(settings, cleaned, answer)
    return answer


def _skipped(
    settings: Settings,
    text: str,
    finish: str,
    question: str,
    started: float,
    *,
    reason: str,
) -> Answer:
    debug = {
        "query_used": "",
        "retrieved": [],
        "prompt_token_estimate": 0,
        "usage": None,
        "finish_reason": finish,
        "timings": {
            "embed": 0.0,
            "search": 0.0,
            "first_token": 0.0,
            "total": time.perf_counter() - started,
        },
        "settings_hash": settings_hash(settings),
        "prompt_hash": "",
        "streamed": False,
        "grounding_text": "",
        "knowledge_text": "",
        "budget_actions": [],
        "error": reason,
        "zero_retrieved": False,
        "repair": "none",
        "removed_sentences": [],
        "model_calls": 0,
    }
    return Answer(text=text, sources_block="", debug=debug, finish_reason=finish)


def _guarded(settings: Settings, started: float, pattern: str, text: str) -> Answer:
    """Fixed line for a guard. No retrieval and no model call."""
    answer = _skipped(settings, text, "guard", "", started, reason="guard")
    answer.debug["error"] = None
    answer.debug["guard_pattern"] = pattern
    return answer


def _knowledge_text(
    prompt_facts: str,
    stuffed_knowledge: str,
    used_chunks: Sequence[RetrievedChunk],
) -> str:
    """Facts text actually placed in the prompt, plus entries actually sent.

    Windows stay inside one unit. Under ``FACTS_IN_PROMPT=summary`` the bullets
    are absent unless a facts entry was retrieved and sent.
    """
    units: list[str] = []
    if prompt_facts.strip():
        units.append(prompt_facts.strip())
    if stuffed_knowledge.strip():
        for block in stuffed_knowledge.strip().split("\n\n"):
            if block.strip():
                units.append(block.strip())
    else:
        for chunk in used_chunks:
            body = (chunk.body or "").strip()
            if body:
                units.append(body)
    return ENTRY_BREAK.join(units)


def _append_note(messages: Sequence[dict[str, str]], note: str) -> list[dict[str, str]]:
    copied = [dict(message) for message in messages]
    copied[-1]["content"] = copied[-1]["content"] + "\n\n" + note
    return copied


def _best_entry_text(chunks: Sequence[RetrievedChunk], missing: str) -> str:
    """Verbatim body of the highest-scoring retrieved entry, or the 4.3 line."""
    if not chunks:
        return missing
    best = max(chunks, key=lambda chunk: chunk.score)
    body = (best.body or "").strip()
    return body or missing


@dataclass
class _Checked:
    text: str
    usage: dict[str, Any] | None
    finish: str | None
    first_token: float
    verification: dict[str, Any]
    retry_used: bool
    fallback_used: bool
    retry_text: str
    repair: str
    removed: list[str]
    model_calls: int


def _verify(text: str, knowledge_text: str, settings: Settings) -> Any:
    return verify_answer(
        text,
        knowledge_text,
        exempt=exempt_replies(settings.human_name, settings.bot_name),
        name_stopwords=name_stopwords(settings.human_name, settings.bot_name),
    )


def _verify_or_fallback(
    text: str,
    knowledge_text: str,
    messages: Sequence[dict[str, str]],
    chunks: Sequence[RetrievedChunk],
    settings: Settings,
    *,
    clients: Any,
    usage: dict[str, Any] | None,
    finish: str | None,
    first_token: float,
) -> _Checked:
    """Check the answer. Prune flagged sentences, then one retry, then fallback."""
    verdict = _verify(text, knowledge_text, settings)
    if verdict.ok:
        return _Checked(
            text, usage, finish, first_token, verdict.as_dict(), False, False, "", "none", [], 1
        )

    flagged = verdict.flagged_sentences()
    usable = _prune_if_usable(text, flagged, knowledge_text, settings)
    if usable is not None:
        pruned_text, pruned_verdict = usable
        payload = pruned_verdict.as_dict()
        _remember_first_pass(payload, text, verdict)
        return _Checked(
            pruned_text,
            usage,
            finish,
            first_token,
            payload,
            False,
            False,
            "",
            "prune",
            flagged,
            1,
        )

    retry_text = ""
    retry_verdict = verdict
    try:
        retry_text, usage2, finish2, first2, _streamed = _call_model(
            settings,
            _append_note(messages, corrective_note(verdict)),
            clients=clients,
            on_delta=None,
        )
        retry_verdict = _verify(retry_text, knowledge_text, settings)
        if retry_verdict.ok:
            payload = retry_verdict.as_dict()
            _remember_first_pass(payload, text, verdict)
            return _Checked(
                retry_text,
                usage2,
                finish2,
                first2,
                payload,
                True,
                False,
                retry_text,
                "retry",
                flagged,
                2,
            )
        usage, finish, first_token = usage2, finish2, first2
    except Exception as exc:  # noqa: BLE001 — fall back to a known entry
        logger.warning("verification retry failed: %s", exc)

    payload = retry_verdict.as_dict()
    payload["retry_failed"] = True
    _remember_first_pass(payload, text, verdict)
    return _Checked(
        _best_entry_text(
            chunks,
            persona_lines(settings.human_name, settings.bot_name).missing,
        ),
        usage,
        "fallback",
        first_token,
        payload,
        True,
        True,
        retry_text,
        "fallback",
        flagged,
        2,
    )


def _prune_if_usable(
    text: str,
    flagged: list[str],
    knowledge_text: str,
    settings: Settings,
) -> tuple[str, Any] | None:
    """Return the pruned text when deleting flagged sentences is enough."""
    pruned = prune_flagged_sentences(text, flagged)
    if not pruned or not starts_complete(pruned):
        return None
    original_count = len(split_sentences(text))
    needed = minimum_kept(original_count, settings.verify_prune_min_sentences)
    if len(split_sentences(pruned)) < needed:
        return None
    verdict = _verify(pruned, knowledge_text, settings)
    if not verdict.ok:
        return None
    return pruned, verdict


def _remember_first_pass(payload: dict[str, Any], original: str, verdict: Any) -> None:
    """Keep the first answer's failures so a passing retry does not hide them."""
    payload["original_text"] = original
    payload["first_flagged_sentences"] = verdict.flagged_sentences()
    payload["first_characterizations"] = list(verdict.unsupported_characterizations)
    payload["first_claims"] = list(verdict.unsupported_claims)


def _maybe_stuff(
    settings: Settings,
    system_prompt: str | None,
    qa_path: Path,
    about_path: Path,
) -> tuple[str, str, str]:
    base = system_prompt
    if base is None:
        base = load_system_prompt(
            voice_samples=voice_samples_enabled(settings.voice_samples),
            facts_in_prompt=settings.facts_in_prompt,
            about_path=about_path,
            bot_name=settings.bot_name,
            human_name=settings.human_name,
        )
    if settings.qa_mode != "stuff":
        return base, "", ""
    if not qa_path.is_file():
        note = f"QA_MODE=stuff but {qa_path} missing; skipping stuff."
        logger.warning(note)
        return base, "", note
    entries = parse_qa(qa_path.read_text(encoding="utf-8"))
    active, used, fitted = stuff_qa_into_system(
        base, entries, budget_tokens=settings.context_budget_tokens
    )
    if not fitted:
        note = (
            "QA_MODE=stuff: Q&A entries did not fit CONTEXT_BUDGET_TOKENS; "
            "continuing without stuffing."
        )
        logger.warning(note)
        return base, "", note
    knowledge = "\n\n".join(f"Q: {e.question}\nA: {e.answer}" for e in used)
    return active, knowledge, ""


def _search(
    query: str,
    settings: Settings,
    source_types: set[str],
    *,
    retrieve_fn: Callable[..., list[RetrievedChunk]] | None,
) -> tuple[list[RetrievedChunk], float, float]:
    kwargs = {
        "k": settings.retrieval_k,
        "max_per_article": settings.retrieval_max_per_article,
        "min_score": settings.retrieval_min_score,
        "source_types": source_types,
        "config": settings.to_embed_config(),
    }
    if retrieve_fn is not None:
        started = time.perf_counter()
        return list(retrieve_fn(query, **kwargs)), 0.0, time.perf_counter() - started
    return retrieve_timed(query, **kwargs)


def _call_model(
    settings: Settings,
    messages: Sequence[dict[str, str]],
    *,
    clients: Any,
    on_delta: Callable[[str], None] | None,
) -> tuple[str, dict[str, Any] | None, str | None, float, bool]:
    client = clients if clients is not None else make_chat_client(settings)
    delay = 0.4
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            started = time.perf_counter()
            if on_delta is None:
                completion = client.chat.completions.create(
                    model=settings.llm_model,
                    messages=list(messages),
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                    stream=False,
                )
                choice = completion.choices[0]
                text = choice.message.content or ""
                finish = getattr(choice, "finish_reason", None)
                elapsed = time.perf_counter() - started
                return text, _usage(getattr(completion, "usage", None)), finish, elapsed, False
            return _stream(client, settings, messages, on_delta, started)
        except Exception as exc:
            last_error = exc
            if not _retryable(exc) or attempt >= 2:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(str(last_error) if last_error else "model call failed")


def _stream(
    client: Any,
    settings: Settings,
    messages: Sequence[dict[str, str]],
    on_delta: Callable[[str], None],
    started: float,
) -> tuple[str, dict[str, Any] | None, str | None, float, bool]:
    stream = client.chat.completions.create(
        model=settings.llm_model,
        messages=list(messages),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    reply = ""
    usage: dict[str, Any] | None = None
    finish: str | None = None
    first_token = 0.0
    emitted = False
    for chunk in stream:
        if getattr(chunk, "usage", None) is not None:
            usage = _usage(chunk.usage)
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        reason = getattr(choice, "finish_reason", None)
        if reason:
            finish = reason
        piece = getattr(getattr(choice, "delta", None), "content", None)
        if piece:
            if not emitted:
                first_token = time.perf_counter() - started
                emitted = True
            on_delta(piece)
            reply += piece
    if not emitted:
        first_token = time.perf_counter() - started
    return reply, usage, finish, first_token, emitted


def _usage(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    return {
        "prompt_tokens": getattr(raw, "prompt_tokens", None),
        "completion_tokens": getattr(raw, "completion_tokens", None),
        "total_tokens": getattr(raw, "total_tokens", None),
    }


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(exc, APIStatusError) and status in _RETRYABLE_STATUS:
        return True
    return status in _RETRYABLE_STATUS


def _log_turn(settings: Settings, question: str, answer: Answer) -> None:
    if settings.log_turns != "on":
        return
    TURN_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "question": question,
        "answer": answer.text,
        "finish_reason": answer.finish_reason,
        "retrieved": answer.debug.get("retrieved", []),
    }
    with TURN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

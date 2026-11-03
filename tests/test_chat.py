"""Unit tests for chat wiring with fake LLM and fake retriever."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.chat import main
from src.config import load_settings
from src.pipeline import answer_turn, append_turn, make_chat_client
from src.prompt import load_system_prompt
from src.retrieve import RetrievedChunk


@dataclass
class _Delta:
    content: str | None


@dataclass
class _Choice:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list[_Choice]
    usage: Any = None


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class FakeCompletions:
    def __init__(self, reply: str = "I work at Mindsize.") -> None:
        self.reply = reply
        self.last_messages: list[dict[str, str]] | None = None
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.last_kwargs = kwargs
        self.last_messages = list(kwargs["messages"])
        if kwargs.get("stream"):
            pieces = list(self.reply)
            chunks = [
                _Chunk(choices=[_Choice(_Delta(p))]) for p in pieces
            ]
            chunks.append(
                _Chunk(
                    choices=[],
                    usage=_Usage(prompt_tokens=123, completion_tokens=10, total_tokens=133),
                )
            )
            return iter(chunks)

        class _Msg:
            content = self.reply

        class _Ch:
            message = _Msg()

        class _Resp:
            def __init__(self) -> None:
                self.choices = [_Ch()]
                self.usage = _Usage(50, 5, 55)

        return _Resp()


class FakeChat:
    def __init__(self, reply: str = "I work at Mindsize.") -> None:
        self.completions = FakeCompletions(reply)


class FakeClient:
    def __init__(self, reply: str = "I work at Mindsize.") -> None:
        self.chat = FakeChat(reply)


def _settings(**env: str):
    base = {
        "LLM_MODEL": "fake",
        "LLM_BASE_URL": "http://example",
        "LLM_API_KEY": "x",
        "RETRIEVAL_SOURCES": "qa,blog",
        "CONTEXT_BUDGET_TOKENS": "100000",
    }
    base.update(env)
    return load_settings(environ=base)


def _chunk(
    id_: str,
    slug: str,
    score: float,
    published: str = "2021-03-01T00:00:00Z",
) -> RetrievedChunk:
    return RetrievedChunk(
        id=id_,
        title=slug.replace("-", " ").title(),
        slug=slug,
        url=f"https://example.com/{slug}",
        published_at=published,
        section="",
        body=f"Body of {slug}",
        source_type="blog",
        score=score,
        content_hash=id_,
    )


def test_answer_includes_sources_and_plain_history() -> None:
    client = FakeClient("Use a reverse proxy.")
    chunks = [_chunk("proxy#0", "how-to-make-a-domain-proxy", 0.85)]

    def fake_retrieve(query: str, **kwargs: Any) -> list[RetrievedChunk]:
        assert "nginx" in query.lower() or "proxy" in query.lower()
        return chunks

    reply_answer = answer_turn(
        "How do I set up an nginx proxy?",
        [],
        _settings(),
        clients=client,
        retrieve_fn=fake_retrieve,
        today=date(2024, 6, 1),
        system_prompt="SYS",
    )
    reply = reply_answer.text
    sources = reply_answer.sources_block
    history = append_turn([], "How do I set up an nginx proxy?", reply, 6)
    assert "reverse proxy" in reply.lower() or reply
    assert sources.startswith("From my blog:")
    assert "older than 3 years" in sources
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "How do I set up an nginx proxy?"
    assert "Body of" not in history[0]["content"]
    # Prompt had excerpts for the model, not in stored history.
    assert client.chat.completions.last_messages is not None
    assert "BLOG_EXCERPTS" in client.chat.completions.last_messages[-1]["content"]


def test_follow_up_retrieval_query_includes_prior_topic() -> None:
    seen: list[str] = []

    def fake_retrieve(query: str, **kwargs: Any) -> list[RetrievedChunk]:
        seen.append(query)
        return [_chunk("p#0", "proxy", 0.8)]

    client = FakeClient("More detail.")
    history = [
        {"role": "user", "content": "nginx proxy setup"},
        {"role": "assistant", "content": "here is a tip"},
    ]
    answer_turn(
        "say more about that",
        history,
        _settings(RETRIEVAL_QUERY_TURNS="2"),
        clients=client,
        retrieve_fn=fake_retrieve,
        today=date(2024, 1, 1),
        system_prompt="S",
    )
    assert "nginx proxy setup" in seen[0]
    assert "say more about that" in seen[0]


def test_min_score_filters_chunks_no_sources() -> None:
    def fake_retrieve(query: str, **kwargs: Any) -> list[RetrievedChunk]:
        return [_chunk("low", "irrelevant", 0.2)]

    client = FakeClient("I led engineering at Mindsize.")
    reply_answer = answer_turn(
        "What did you do at Mindsize?",
        [],
        _settings(RETRIEVAL_MIN_SCORE="0.5"),
        clients=client,
        retrieve_fn=fake_retrieve,
        today=date(2024, 1, 1),
        system_prompt="S",
    )
    reply = reply_answer.text
    sources = reply_answer.sources_block
    assert sources == ""
    assert "Mindsize" in reply
    user_content = client.chat.completions.last_messages[-1]["content"]
    assert "No matching entries were found" in user_content


class _ScriptedCompletions:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    def create(self, **kwargs: Any) -> Any:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        self.messages.append(list(kwargs["messages"]))

        class _Msg:
            content = reply

        class _Ch:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            def __init__(self) -> None:
                self.choices = [_Ch()]
                self.usage = _Usage(50, 5, 55)

        return _Resp()


class _ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.chat = type("C", (), {})()
        self.chat.completions = _ScriptedCompletions(replies)


def test_prune_drops_the_invented_sentence_without_a_retry() -> None:
    if not Path("content/about-ben.md").is_file():
        pytest.skip("content/about-ben.md not present")
    draft = (
        "I was Director of Engineering at Mindsize from June 2019 to September 2026. "
        "I've got a sweet spot for my bees. "
        "My team at Mindsize spanned the USA, Canada, and the Philippines."
    )
    client = _ScriptedClient([draft])
    answer = answer_turn(
        "What did you do at Mindsize?",
        [],
        _settings(RETRIEVAL_SOURCES="none"),
        clients=client,
    )
    assert client.chat.completions.calls == 1
    assert answer.debug["repair"] == "prune"
    assert "sweet spot" not in answer.text
    assert "Director of Engineering" in answer.text
    assert "Philippines" in answer.text
    assert answer.text.startswith("I was Director")
    assert any("sweet spot" in sentence for sentence in answer.debug["removed_sentences"])


def test_short_prune_retries_once_then_can_fall_back() -> None:
    if not Path("content/about-ben.md").is_file():
        pytest.skip("content/about-ben.md not present")
    bad = "I've got a sweet spot for my bees."
    kept = (
        "I was Director of Engineering at Mindsize from June 2019 to September 2026. "
        "My team at Mindsize spanned the USA, Canada, and the Philippines."
    )
    client = _ScriptedClient([bad, kept])
    answer = answer_turn(
        "What did you do at Mindsize?",
        [],
        _settings(RETRIEVAL_SOURCES="none"),
        clients=client,
    )
    assert client.chat.completions.calls == 2
    assert answer.debug["repair"] == "retry"
    assert "Philippines" in answer.text
    note = client.chat.completions.messages[1][-1]["content"]
    assert "Keep every supported sentence unchanged." in note

    falling = _ScriptedClient([bad, bad])

    def fake_retrieve(query: str, **kwargs: Any) -> list[RetrievedChunk]:
        return [_chunk("mindsize", "mindsize-role", 0.9)]

    answer = answer_turn(
        "What did you do at Mindsize?",
        [],
        _settings(),
        clients=falling,
        retrieve_fn=fake_retrieve,
        system_prompt="S",
    )
    assert falling.chat.completions.calls == 2
    assert answer.debug["repair"] == "fallback"
    assert answer.text == "Body of mindsize-role"


def test_empty_ask_exits_with_code_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--ask", ""])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == "Ask me something about Ben."


def test_stuff_mode_omits_the_no_match_notice(tmp_path) -> None:
    qa = tmp_path / "qa.md"
    qa.write_text(
        "## one\nQ: Who are you?\nA: My name is Example.\n"
        "source: example\nreview: draft\n",
        encoding="utf-8",
    )
    client = FakeClient("I coach teams.")
    answer_turn(
        "Who are you?",
        [],
        _settings(QA_MODE="stuff", RETRIEVAL_SOURCES="qa"),
        clients=client,
        qa_path=qa,
        system_prompt="SYS",
        retrieve_fn=lambda *_args, **_kwargs: [],
    )
    assert client.chat.completions.last_messages is not None
    user = client.chat.completions.last_messages[-1]["content"]
    assert "No matching entries were found" not in user
    system = client.chat.completions.last_messages[0]["content"]
    assert "My name is Example." in system


@pytest.mark.integration
def test_integration_ollama_one_turn() -> None:
    import os

    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to hit live Ollama")
    settings = load_settings()
    client = make_chat_client(settings)
    system = load_system_prompt(
        stale_years=settings.source_stale_years,
        voice_samples=settings.voice_samples == "on",
        include_blog="blog" in settings.retrieval_sources,
    )
    answer = answer_turn(
        "What's your background?",
        [],
        settings,
        clients=client,
        today=date.today(),
        system_prompt=system,
    )
    assert answer.text.strip()
    history = append_turn([], "What's your background?", answer.text, settings.history_turns)
    assert history[-1]["role"] == "assistant"

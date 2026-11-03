"""BENBOT-14: phrasings, follow-ups, multi-vector collapse, facts knowledge."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.index_chunks import IndexCompatibilityError, build_or_update_index
from src.pipeline import answer_turn
from src.prompt import compose_retrieval_query, facts_for_prompt, is_followup
from src.qa import expand_multi_vectors, parse_qa, split_phrasings
from src.retrieve import collapse_to_entries
from src.vector_store import SearchHit
from tests.fake_embeddings import fake_embed_texts
from tests.test_index_multi import _cfg

FOLLOWUPS = (
    "say more about that",
    "tell me more",
    "more about that",
    "go on",
    "elaborate",
    "can you elaborate",
    "expand on that",
    "such as",
    "like what",
    "for example",
    "really",
    "and the notes",
    "but why",
    "also the docs",
    "so what happened",
    "then what",
    "what about coaching",
    "how about that",
    "why",
    "how so",
    "what about them",
    "say more",
    "tell me more about it",
    "more about this",
    "and how did that go",
)
STANDALONE = (
    "Do you coach?",
    "What do you do at work?",
    "Who is Ben?",
    "Tell me about your toolkit",
    "Do you work remotely?",
    "What's your background?",
    "What are you like to work for?",
    "How did you start coaching?",
    "Do you write playbooks?",
    "What tools do you keep nearby?",
    "Tell me about your week",
    "Do you use SQLite?",
    "Do you use TypeScript?",
    "What's your leadership style?",
    "What do you do for fun?",
    "Where do you coach?",
    "Can you lead without being the expert?",
    "How do you run one-on-ones?",
    "What is BenBot?",
    "Have you written a book?",
    "What kind of role do you want?",
    "How is coaching different from mentoring?",
    "Do you facilitate retros?",
    "What happened when the notes ran out?",
    "Tell me about coaching",
)


def test_followup_labels_match_the_rule() -> None:
    assert len(FOLLOWUPS) >= 25
    assert len(STANDALONE) >= 25
    missed = [text for text in FOLLOWUPS if not is_followup(text)]
    false = [text for text in STANDALONE if is_followup(text)]
    assert missed == []
    assert false == []


def test_auto_query_keeps_a_new_question_and_joins_a_followup() -> None:
    history = [
        {"role": "user", "content": "Tell me about coaching"},
        {"role": "assistant", "content": "I sail."},
    ]
    alone = compose_retrieval_query(
        history, "What do you do at work?", query_turns=2, mode="auto"
    )
    assert alone == "What do you do at work?"
    joined = compose_retrieval_query(
        history, "say more about that", query_turns=1, mode="auto"
    )
    assert joined == "Tell me about coaching\nsay more about that"
    turns = compose_retrieval_query(
        history, "What do you do at work?", query_turns=2, mode="turns"
    )
    assert "Tell me about coaching" in turns
    assert "What do you do at work?" in turns


def test_split_phrasings_keeps_the_question_mark() -> None:
    question = "What's your management style? Do you micromanage? / How do you manage your team?"
    assert split_phrasings(question) == [
        "What's your management style?",
        "Do you micromanage?",
        "How do you manage your team?",
    ]


def test_collapse_takes_max_score_and_qa_on_a_tie() -> None:
    hits = [
        SearchHit("qa#intro#q0", 0.5, "h-q", {"entry_id": "qa#intro", "kind": "q", "phrasing": "Who?", "slug": "intro", "entry_content_hash": "entry"}),
        SearchHit("qa#intro#qa", 0.5, "h-qa", {"entry_id": "qa#intro", "kind": "qa", "phrasing": "Q+A", "slug": "intro", "entry_content_hash": "entry"}),
        SearchHit("qa#other#q0", 0.9, "h-o", {"entry_id": "qa#other", "kind": "q", "phrasing": "Other?", "slug": "other", "entry_content_hash": "other"}),
    ]
    collapsed = collapse_to_entries(hits)
    by_id = {hit.id: hit for hit in collapsed}
    assert set(by_id) == {"qa#intro", "qa#other"}
    assert by_id["qa#intro"].metadata["match_kind"] == "qa"
    assert by_id["qa#intro"].metadata["match_phrasing"] == "Q+A"
    assert collapsed[0].id == "qa#other"


def test_multi_index_is_incremental_and_mode_change_requires_rebuild(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    blog = {
        "id": "blog#0",
        "content_hash": "h-blog",
        "title": "Blog",
        "slug": "blog",
        "published_at": "",
        "section": "",
        "url": "",
        "source_type": "blog",
        "body": "blog body",
        "embed_text": "blog body",
        "word_count": 2,
    }
    entry = parse_qa(
        "## intro\nQ: Who are you? / Who is Ben?\nA: I am Example.\nsource: x\nreview: approved\n"
    )[0]
    import json

    from src.qa import entry_to_chunk

    (chunks_dir / "chunks.jsonl").write_text(json.dumps(blog) + "\n", encoding="utf-8")
    (chunks_dir / "qa_chunks.jsonl").write_text(
        json.dumps(entry_to_chunk(entry, embed_mode="multi")) + "\n", encoding="utf-8"
    )
    index_dir = tmp_path / "index"
    first = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="multi",
        q_vector_prefix="query",
        rebuild=True,
    )
    # two phrasings + one qa vector + the blog row
    assert first["embedded"] == 4
    assert first["qa_vector_mode"] == "multi"
    second = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="multi",
        q_vector_prefix="query",
    )
    assert second["embedded"] == 0
    with pytest.raises(IndexCompatibilityError, match="rebuild"):
        build_or_update_index(
            chunks_dir=chunks_dir,
            index_dir=index_dir,
            config=_cfg(),
            embed_fn=fake_embed_texts,
            qa_embed_mode="question_and_answer",
        )


def test_expand_stores_kind_phrasing_and_hash() -> None:
    entry = parse_qa(
        "## intro\nQ: Who are you?\nA: I am Example.\nsource: x\nreview: approved\n"
    )[0]
    from src.qa import entry_to_chunk

    rows = expand_multi_vectors(
        [entry_to_chunk(entry, embed_mode="multi")], q_embed_kind="query"
    )
    kinds = [row["kind"] for row in rows]
    assert kinds == ["q", "qa"]
    assert rows[0]["phrasing"] == "Who are you?"
    assert rows[0]["entry_id"] == "qa#intro"
    assert rows[0]["embed_kind"] == "query"
    assert rows[1]["embed_kind"] == "document"
    assert rows[0]["content_hash"] != rows[1]["content_hash"]


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self) -> None:
        self.message = _Msg("I lead.")
        self.finish_reason = "stop"


class _Resp:
    def __init__(self) -> None:
        self.choices = [_Choice()]
        self.usage = None


_COMPLETION_CALLS: list[object] = []


class _Completions:
    def create(self, **kwargs: object) -> _Resp:
        _COMPLETION_CALLS.append(kwargs.get("messages"))
        return _Resp()


class _Chat:
    completions = _Completions()


class _Client:
    chat = _Chat()


def _chunk(entry_id: str, body: str, source: str) -> object:
    from src.retrieve import RetrievedChunk

    return RetrievedChunk(
        id=entry_id,
        title="Question",
        slug=entry_id.split("#", 1)[-1],
        url="",
        published_at="",
        section="",
        body=body,
        source_type=source,
        score=0.8,
        content_hash="h",
    )


def test_knowledge_text_matches_full_and_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    about = tmp_path / "about.md"
    about.write_text(
        "# About\n\nOpening paragraph about Ben.\n\n## Work\n- Secret studio bullet.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.pipeline.ABOUT_PATH", about)
    from src.config import load_settings

    def retrieve(query: str, **kwargs: object) -> list:
        return [
            _chunk("facts#retreats", "I've run four coaching retreats with small teams.", "facts"),
            _chunk("qa#intro", "I am a leadership consultant.", "qa"),
        ]

    _COMPLETION_CALLS.clear()
    summary = answer_turn(
        "Tell me about retreats",
        [],
        load_settings(environ={"FACTS_IN_PROMPT": "summary", "RETRIEVAL_SOURCES": "qa,facts"}),
        clients=_Client(),
        retrieve_fn=retrieve,
        today=__import__("datetime").date(2026, 10, 22),
    )
    knowledge = summary.debug["knowledge_text"]
    assert "Opening paragraph about Ben." in knowledge
    assert "Secret studio bullet." not in knowledge
    assert "four coaching retreats" in knowledge
    assert "leadership consultant" in knowledge
    summary_system = str(_COMPLETION_CALLS[0][0]["content"])  # type: ignore[index]
    assert "Opening paragraph about Ben." in summary_system
    assert "Secret studio bullet." not in summary_system

    _COMPLETION_CALLS.clear()
    full = answer_turn(
        "Tell me about retreats",
        [],
        load_settings(environ={"FACTS_IN_PROMPT": "full", "RETRIEVAL_SOURCES": "qa,facts"}),
        clients=_Client(),
        retrieve_fn=retrieve,
        today=__import__("datetime").date(2026, 10, 22),
    )
    full_knowledge = full.debug["knowledge_text"]
    assert "Secret studio bullet." in full_knowledge
    assert "four coaching retreats" in full_knowledge
    full_system = str(_COMPLETION_CALLS[0][0]["content"])  # type: ignore[index]
    assert "Secret studio bullet." in full_system
    assert "Opening paragraph" in facts_for_prompt(about.read_text(), "summary")
    assert "Secret" not in facts_for_prompt(about.read_text(), "summary")

"""BENBOT-10: one settings path, health messages, pipeline wiring, Q-line edits."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.properties import (
    equals_fixed_line,
    first_person,
    no_quoted_prompt,
    no_rule_text,
    rule_ngrams,
)
from eval.run_regression_eval import build_run_settings
from src.config import load_settings, min_score_warning
from src.guards import persona_lines
from src.health import (
    INDEX_DIR,
    STALE_WARNING,
    Probe,
    live_probe,
    missing_embed_message,
    missing_llm_message,
    run_health_checks,
    unreachable_message,
)
from src.pipeline import answer_turn
from src.retrieve import main as retrieve_main

ROOT = Path(__file__).resolve().parents[1]
QA_SAMPLE = """## one
Q: What is your name?
A: My name is Example.
source: interview
review: draft
"""


def _settings(**env: str):
    return load_settings(environ=env)


def _probe(**overrides: object) -> Probe:
    base = Probe(
        reachable={"http://localhost:11434/v1": True},
        models={
            "http://localhost:11434/v1": ["llama3.1:8b", "nomic-embed-text"],
        },
        index={
            "embed_model": "nomic-embed-text",
            "dimension": 768,
            "query_prefix": "search_query: ",
            "doc_prefix": "search_document: ",
            "qa_embed_mode": "question_and_answer",
            "max_chars": 8000,
            "qa_entries": 4,
            "facts_entries": 2,
        },
        texts={"prompt": "rules", "about": "facts", "qa": QA_SAMPLE},
        index_mtime=100.0,
        source_mtimes=[50.0],
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_blank_env_values_are_unset() -> None:
    settings = load_settings(
        environ={
            "LLM_BASE_URL": "",
            "LLM_API_KEY": "   ",
            "LLM_TEMPERATURE": "",
            "LLM_MAX_TOKENS": "",
            "EMBED_QUERY_PREFIX": "",
            "LOG_LEVEL": "",
            "LOG_TURNS": "",
            "RETRIEVAL_K": "",
        }
    )
    assert settings.llm_base_url == "http://localhost:11434/v1"
    assert settings.llm_api_key == "ollama"
    assert settings.llm_temperature == 0.0
    assert settings.llm_max_tokens == 600
    assert settings.embed_query_prefix == "search_query: "
    assert settings.log_level == "WARNING"
    assert settings.log_turns == "off"
    assert settings.retrieval_k == 4


def test_live_probe_reports_unreachable_on_a_bad_url() -> None:
    settings = load_settings(environ={"LLM_BASE_URL": "not a url"})
    probe = live_probe(settings)
    assert probe.reachable.get("not a url") is False


def test_defaults_match_spec() -> None:
    settings = _settings()
    assert settings.llm_temperature == 0
    assert settings.llm_max_tokens == 600
    assert settings.retrieval_k == 4
    assert settings.retrieval_max_per_article == 2
    assert settings.retrieval_query_turns == 2
    assert settings.retrieval_query_mode == "auto"
    assert settings.qa_embed_mode == "multi"
    assert settings.voice_samples == "off"
    assert settings.retrieval_min_score is None
    assert settings.embed_query_prefix == "search_query: "
    assert settings.embed_doc_prefix == "search_document: "


def test_parse_error_names_the_variable() -> None:
    with pytest.raises(ValueError, match="RETRIEVAL_K"):
        _settings(RETRIEVAL_K="nope")
    with pytest.raises(ValueError, match="RETRIEVAL_MIN_SCORE"):
        _settings(RETRIEVAL_MIN_SCORE="2")


def test_min_score_warning_above_0_85() -> None:
    assert min_score_warning(_settings()) is None
    assert min_score_warning(_settings(RETRIEVAL_MIN_SCORE="0.85")) is None
    warning = min_score_warning(_settings(RETRIEVAL_MIN_SCORE="0.99"))
    assert warning is not None
    assert "RETRIEVAL_MIN_SCORE=0.99" in warning
    assert "above 0.85" in warning
    assert "drop all results" in warning


def test_prefix_trailing_space_is_kept() -> None:
    settings = _settings(EMBED_QUERY_PREFIX="search_query: ")
    assert settings.embed_query_prefix == "search_query: "


def test_health_failure_messages() -> None:
    settings = _settings()
    down = _probe(reachable={"http://localhost:11434/v1": False})
    report = run_health_checks(settings, probe=down)
    assert unreachable_message("http://localhost:11434/v1") in report.errors

    missing_llm = _probe(
        models={"http://localhost:11434/v1": ["nomic-embed-text"]}
    )
    report = run_health_checks(settings, probe=missing_llm)
    assert missing_llm_message("llama3.1:8b", "http://localhost:11434/v1") in report.errors

    missing_embed = _probe(models={"http://localhost:11434/v1": ["llama3.1:8b"]})
    report = run_health_checks(settings, probe=missing_embed)
    assert (
        missing_embed_message("nomic-embed-text", "http://localhost:11434/v1")
        in report.errors
    )

    missing_prompt = _probe(texts={"prompt": None, "about": "facts", "qa": QA_SAMPLE})
    report = run_health_checks(settings, probe=missing_prompt)
    assert any("Prompt template not found" in line for line in report.errors)

    missing_about = _probe(texts={"prompt": "rules", "about": None, "qa": QA_SAMPLE})
    report = run_health_checks(settings, probe=missing_about)
    assert any("Facts file not found" in line for line in report.errors)

    bad_qa = _probe(
        texts={
            "prompt": "rules",
            "about": "facts",
            "qa": (
                "## broken\nQ: Hello\nA: Hi\nsource: x\nreview: draft\n"
                "not an answer\n"
            ),
        }
    )
    report = run_health_checks(settings, probe=bad_qa)
    assert any(line.startswith("qa.md parse error:") for line in report.errors)

    report = run_health_checks(settings, probe=_probe(index=None))
    assert any(f"Index not found at {INDEX_DIR}" in line for line in report.errors)
    assert any("python -m src.index_chunks --rebuild" in line for line in report.errors)

    mismatch = _probe(
        index={
            "embed_model": "other",
            "dimension": 0,
            "query_prefix": "",
            "doc_prefix": "",
            "qa_embed_mode": "question_only",
            "max_chars": 1,
            "qa_entries": 0,
        }
    )
    report = run_health_checks(settings, probe=mismatch)
    joined = " ".join(report.errors)
    assert "embed model" in joined
    assert "dimension" in joined
    assert "query prefix" in joined
    assert "doc prefix" in joined
    assert "QA_EMBED_MODE" in joined
    assert "python -m src.index_chunks --rebuild" in joined

    no_qa = _probe(
        index={
            "embed_model": "nomic-embed-text",
            "dimension": 768,
            "query_prefix": "search_query: ",
            "doc_prefix": "search_document: ",
            "qa_embed_mode": "question_and_answer",
            "max_chars": 8000,
            "qa_entries": 0,
        }
    )
    report = run_health_checks(settings, probe=no_qa)
    assert any("no entries" in line for line in report.errors)

    stale = _probe(index_mtime=1.0, source_mtimes=[5.0])
    report = run_health_checks(settings, probe=stale)
    assert STALE_WARNING in report.warnings
    assert report.ready_line.startswith("Ready: model=llama3.1:8b")


def test_retrieval_k_reaches_the_pipeline() -> None:
    seen: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs: object) -> list:
        seen["k"] = kwargs["k"]
        seen["query"] = query
        return []

    class _Msg:
        content = "ok"

    class _Choice:
        def __init__(self) -> None:
            self.message = _Msg()
            self.finish_reason = "stop"

    class _Resp:
        def __init__(self) -> None:
            self.choices = [_Choice()]
            self.usage = None

    class _Completions:
        def create(self, **kwargs: object) -> _Resp:
            seen["temperature"] = kwargs["temperature"]
            seen["max_tokens"] = kwargs["max_tokens"]
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    settings = _settings(RETRIEVAL_K="7", LLM_TEMPERATURE="0", LLM_MAX_TOKENS="600")
    answer = answer_turn(
        "Who is Ben?",
        [{"role": "user", "content": "sailing"}, {"role": "assistant", "content": "boats"}],
        settings,
        clients=_Client(),
        retrieve_fn=fake_retrieve,
        system_prompt="RULES",
    )
    assert seen["k"] == 7
    assert seen["temperature"] == 0
    assert seen["max_tokens"] == 600
    assert seen["query"] == "Who is Ben?"
    assert answer.text == "ok"
    assert "RULES" in str(answer.debug["prompt_hash"]) or answer.debug["prompt_hash"]


def test_too_long_skips_the_model() -> None:
    class _Completions:
        calls = 0

        def create(self, **kwargs: object) -> object:
            self.calls += 1
            raise AssertionError("model should not be called")

    class _Client:
        def __init__(self) -> None:
            self.chat = type("C", (), {"completions": _Completions()})()

    client = _Client()
    answer = answer_turn("x" * 2001, [], _settings(), clients=client, system_prompt="S")
    assert answer.text == "That's a bit long for me. Could you shorten it?"
    assert answer.finish_reason == "invalid"


def test_retrieve_cli_uses_settings(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    settings = _settings(EMBED_MODEL="embed-x")
    monkeypatch.setattr("src.config.load_settings", lambda: settings)
    monkeypatch.setattr("src.retrieve.retrieve_timed", lambda *args, **kwargs: ([], 0.0, 0.0))
    code = retrieve_main(["what is a boat", "-k", "3"])
    captured = capsys.readouterr()
    assert code == 0
    assert "RETRIEVAL_K=3" in captured.out
    assert "EMBED_MODEL=embed-x" in captured.out


def test_retrieve_help_is_not_blog_only(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        retrieve_main(["--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "same settings as the chat" in text


def test_eval_runner_uses_config_settings() -> None:
    settings = build_run_settings(
        retrieval_k=8,
        query_turns=1,
        base=_settings(LLM_MODEL="from-config"),
    )
    assert settings.llm_model == "from-config"
    assert settings.retrieval_k == 8
    assert settings.retrieval_query_turns == 1
    source = (ROOT / "eval" / "run_guardrail_eval.py").read_text(encoding="utf-8")
    assert "answer_turn" in source
    assert "os.environ" not in source
    assert "load_dotenv" not in source


def test_only_config_reads_the_environment() -> None:
    needles = ("os.environ", "os.getenv", "load_dotenv")
    offenders: list[str] = []
    paths = list((ROOT / "src").rglob("*.py"))
    paths.extend((ROOT / "eval").rglob("*.py"))
    paths.extend((ROOT / "scripts").rglob("*.py"))
    for path in paths:
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}:{needle}")
    assert offenders == []


def test_property_checks_cover_fixed_lines_and_rule_numbers() -> None:
    line = persona_lines("Ada", "AdaBot").off_topic
    assert equals_fixed_line(line, "4.4", human_name="Ada", bot_name="AdaBot").ok
    assert not equals_fixed_line(line + " Sure.", "4.4", human_name="Ada").ok
    assert not first_person("Ada is a coach.", human_name="Ada").ok
    assert first_person("I coach.").ok
    assert first_person("Ada is a coach.").ok
    assert not first_person("He's a coach.").ok
    assert not first_person("To her, the work matters.").ok
    assert not first_person("She mentions the work.").ok
    ngrams = rule_ngrams("Never cite rule numbers in an answer to a visitor please thanks.")
    assert not no_rule_text("See rule 2 for why.", ngrams).ok
    quoted = '"' + " ".join(["word"] * 13) + '"'
    assert not no_quoted_prompt(quoted).ok
    assert no_quoted_prompt("no quotes here").ok

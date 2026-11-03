"""Primary and secondary chat connections. No live model."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx
import pytest
from openai import APITimeoutError

from src.chat import UNAVAILABLE, format_debug, main
from src.config import format_settings, load_settings
from src.health import HealthReport, Probe, run_health_checks
from src.llm_pool import (
    CONNECT_TIMEOUT_SECONDS,
    LlmPool,
    ModelUnavailable,
    chat_timeout,
    pool_for,
    reset_pool,
)
from src.pipeline import answer_turn
from src.retrieve import RetrievedChunk


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Completions:
    def __init__(self, behavior: Callable[[int], Any]) -> None:
        self.behavior = behavior
        self.calls = 0
        self.models: list[str] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.models.append(str(kwargs.get("model")))
        result = self.behavior(self.calls)
        if isinstance(result, Exception):
            raise result
        return _response(str(result))


class _Client:
    def __init__(self, behavior: Callable[[int], Any]) -> None:
        self.completions = _Completions(behavior)
        self.chat = self


def _response(text: str) -> Any:
    message = type("Msg", (), {"content": text})()
    choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
    return type("Resp", (), {"choices": [choice], "usage": None})()


def _settings(**env: str):
    base = {
        "LLM_BASE_URL": "http://primary.invalid/v1",
        "LLM_API_KEY": "primary-secret",
        "LLM_MODEL": "primary-model",
        "EMBED_BASE_URL": "http://embed.invalid/v1",
        "EMBED_API_KEY": "embed-secret",
    }
    base.update(env)
    return load_settings(environ=base)


def _pool(settings, primary: _Client, secondary: _Client | None, clock: _Clock) -> LlmPool:
    clients = {"primary": primary}
    if secondary is not None:
        clients["secondary"] = secondary
    return LlmPool(settings, clients=clients, clock=clock, sleeper=lambda _seconds: None)


def _run(pool: LlmPool) -> tuple[Any, str, bool]:
    def attempt(client: _Client, model: str) -> Any:
        return client.chat.completions.create(model=model, messages=[])

    return pool.call(attempt)


def _down() -> ConnectionError:
    return ConnectionError("connection refused")


def _timeout() -> APITimeoutError:
    request = httpx.Request("POST", "http://primary.invalid/v1/chat/completions")
    return APITimeoutError(request)


class _Status(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"http {code}")
        self.status_code = code


def test_blank_primary_group_keeps_legacy_variables() -> None:
    settings = load_settings(
        environ={
            "LLM_BASE_URL": "http://legacy.invalid/v1",
            "LLM_API_KEY": "legacy-secret",
            "LLM_MODEL": "legacy-model",
            "LLM_PRIMARY_BASE_URL": "",
            "LLM_PRIMARY_API_KEY": "   ",
            "LLM_PRIMARY_MODEL": "",
            "LLM_SECONDARY_BASE_URL": "",
            "FAILOVER_ON_HTTP_STATUS": "",
            "FAILOVER_RETRY_SECONDS": "",
        }
    )
    assert settings.llm_base_url == "http://legacy.invalid/v1"
    assert settings.llm_api_key == "legacy-secret"
    assert settings.llm_model == "legacy-model"
    assert settings.llm_secondary_base_url == ""
    assert settings.failover_retry_seconds == 300
    assert settings.failover_on_http_status == ()
    assert settings.llm_primary_timeout_seconds == 120


def test_primary_group_overrides_legacy_names() -> None:
    settings = _settings(
        LLM_PRIMARY_BASE_URL="http://override.invalid/v1",
        LLM_PRIMARY_API_KEY="override-secret",
        LLM_PRIMARY_MODEL="override-model",
    )
    assert settings.llm_base_url == "http://override.invalid/v1"
    assert settings.llm_api_key == "override-secret"
    assert settings.llm_model == "override-model"


def test_partial_connection_group_names_the_variable() -> None:
    with pytest.raises(ValueError, match="LLM_SECONDARY_API_KEY"):
        _settings(LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1")
    with pytest.raises(ValueError, match="FAILOVER_ON_HTTP_STATUS"):
        _settings(FAILOVER_ON_HTTP_STATUS="nope")
    with pytest.raises(ValueError, match="FAILOVER_RETRY_SECONDS"):
        _settings(FAILOVER_RETRY_SECONDS="-1")


def test_keys_are_masked() -> None:
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    text = format_settings(settings)
    assert "primary-secret" not in text
    assert "secondary-secret" not in text
    assert "embed-secret" not in text
    assert "LLM_API_KEY=***" in text
    assert "LLM_SECONDARY_API_KEY=***" in text
    assert "LLM_SECONDARY_BASE_URL=http://secondary.invalid/v1" in text


def test_timeout_defaults() -> None:
    total = chat_timeout(120)
    assert total.connect == CONNECT_TIMEOUT_SECONDS
    assert total.read == 120
    short = chat_timeout(3)
    assert short.connect == 3
    assert short.read == 3


def test_connection_error_uses_secondary_once() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    value, used, active = _run(pool)
    assert value.choices[0].message.content == "from-secondary"
    assert used == "secondary"
    assert active is True
    assert primary.completions.calls == 1
    assert secondary.completions.models == ["secondary-model"]

    value, used, active = _run(pool)
    assert used == "secondary"
    assert active is True
    assert primary.completions.calls == 1


def test_timeout_uses_secondary(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="src.llm_pool")
    clock = _Clock()
    primary = _Client(lambda _call: _timeout())
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    _value, used, active = _run(pool)
    assert used == "secondary"
    assert active is True
    assert len(caplog.records) == 1
    assert "primary is down" in caplog.records[0].message


def test_primary_recovers_after_the_retry_interval() -> None:
    clock = _Clock()
    calls = {"n": 0}

    def primary_behavior(_call: int) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return _down()
        return "from-primary"

    primary = _Client(primary_behavior)
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        FAILOVER_RETRY_SECONDS="300",
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    _value, used, _active = _run(pool)
    assert used == "secondary"
    clock.now = 299
    _value, used, _active = _run(pool)
    assert used == "secondary"
    assert primary.completions.calls == 1
    clock.now = 300
    value, used, active = _run(pool)
    assert used == "primary"
    assert active is False
    assert value.choices[0].message.content == "from-primary"


def test_failed_probe_restarts_the_timer(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="src.llm_pool")
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        FAILOVER_RETRY_SECONDS="300",
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    _run(pool)
    clock.now = 300
    _run(pool)
    assert primary.completions.calls == 2
    clock.now = 599
    value, used, _active = _run(pool)
    assert used == "secondary"
    assert value.choices[0].message.content == "from-secondary"
    assert primary.completions.calls == 2
    messages = [record.message for record in caplog.records]
    assert any("primary is down" in message for message in messages)
    assert any("timer restarted" in message for message in messages)
    assert sum("timer restarted" in message for message in messages) == 1


def test_both_connections_down_raise_model_unavailable() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: _timeout())
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    with pytest.raises(ModelUnavailable, match="Neither chat connection"):
        _run(pool)


def test_single_connection_has_no_secondary() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    settings = _settings()
    pool = _pool(settings, primary, None, clock)
    with pytest.raises(ModelUnavailable, match="not available"):
        _run(pool)
    assert primary.completions.calls == 1


def test_http_status_does_not_fail_over_unless_listed() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _Status(500))
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    with pytest.raises(_Status):
        _run(pool)
    assert primary.completions.calls == 3
    assert secondary.completions.calls == 0

    listed = _settings(
        FAILOVER_ON_HTTP_STATUS="500, 502",
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    assert listed.failover_on_http_status == (500, 502)
    primary = _Client(lambda _call: _Status(500))
    secondary = _Client(lambda _call: "from-secondary")
    pool = _pool(listed, primary, secondary, clock)
    _value, used, active = _run(pool)
    assert used == "secondary"
    assert active is True


def test_matching_secondary_warns(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="src.llm_pool")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://primary.invalid/v1",
        LLM_SECONDARY_API_KEY="primary-secret",
        LLM_SECONDARY_MODEL="primary-model",
        LLM_SECONDARY_TIMEOUT_SECONDS="30",
    )
    LlmPool(settings, clients={"primary": _Client(lambda _call: "ok"), "secondary": _Client(lambda _call: "ok")})
    assert any("will not change hosts" in record.message for record in caplog.records)


def test_concurrent_failover_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="src.llm_pool")
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: "from-secondary")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)

    def once() -> str:
        value, used, _active = _run(pool)
        assert used == "secondary"
        return str(value.choices[0].message.content)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _n: once(), range(8)))
    assert results == ["from-secondary"] * 8
    downs = [record for record in caplog.records if "primary is down" in record.message]
    assert len(downs) == 1


def test_pool_for_keeps_state_until_the_config_changes() -> None:
    reset_pool()
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    first = pool_for(settings)
    assert pool_for(settings) is first
    changed = _settings(
        LLM_MODEL="other-model",
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    assert pool_for(changed) is not first
    reset_pool()


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id="work",
        title="Work",
        slug="work-role",
        url="https://example.com/work",
        published_at="2021-03-01T00:00:00Z",
        section="",
        body="Body of work-role",
        source_type="qa",
        score=0.9,
        content_hash="work",
    )


def test_answer_turn_reports_the_secondary_connection() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: "Body of work-role")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    answer = answer_turn(
        "What kind of work do you do?",
        [],
        settings,
        clients=pool,
        system_prompt="S",
        retrieve_fn=lambda *_args, **_kwargs: [_chunk()],
    )
    assert answer.text == "Body of work-role"
    assert answer.debug["connection_used"] == "secondary"
    assert answer.debug["failover_active"] is True
    debug = format_debug(answer)
    assert "connection_used=secondary" in debug
    assert "failover_active=true" in debug


def test_verification_retry_can_use_the_other_connection() -> None:
    clock = _Clock()
    primary_results = iter(["I've got a sweet spot for tidy backlogs.", _down()])

    def primary_behavior(_call: int) -> Any:
        return next(primary_results)

    primary = _Client(primary_behavior)
    secondary = _Client(lambda _call: "Body of work-role")
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    answer = answer_turn(
        "What kind of work do you do?",
        [],
        settings,
        clients=pool,
        system_prompt="S",
        retrieve_fn=lambda *_args, **_kwargs: [_chunk()],
    )
    assert answer.debug["repair"] == "retry"
    assert answer.debug["connection_used"] == "secondary"
    assert answer.debug["failover_active"] is True
    assert answer.text == "Body of work-role"
    assert primary.completions.calls == 2
    assert secondary.completions.calls == 1


def test_both_down_propagates_from_answer_turn() -> None:
    clock = _Clock()
    primary = _Client(lambda _call: _down())
    secondary = _Client(lambda _call: _down())
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    pool = _pool(settings, primary, secondary, clock)
    with pytest.raises(ModelUnavailable):
        answer_turn(
            "Hello",
            [],
            settings,
            clients=pool,
            system_prompt="S",
            retrieve_fn=lambda *_args, **_kwargs: [],
        )


def test_injected_client_stays_on_one_connection() -> None:
    calls = {"n": 0}

    def behavior(_call: int) -> Any:
        calls["n"] += 1
        if calls["n"] < 3:
            return _timeout()
        return "Body of work-role"

    client = _Client(behavior)
    answer = answer_turn(
        "What kind of work do you do?",
        [],
        _settings(),
        clients=client,
        system_prompt="S",
        retrieve_fn=lambda *_args, **_kwargs: [_chunk()],
    )
    assert client.completions.calls == 3
    assert answer.debug["connection_used"] == "primary"
    assert answer.debug["failover_active"] is False
    assert answer.text == "Body of work-role"


def test_unreachable_primary_is_a_warning_when_embedder_is_up() -> None:
    settings = _settings(
        LLM_SECONDARY_BASE_URL="http://secondary.invalid/v1",
        LLM_SECONDARY_API_KEY="secondary-secret",
        LLM_SECONDARY_MODEL="secondary-model",
    )
    probe = Probe(
        reachable={
            "http://primary.invalid/v1": False,
            "http://secondary.invalid/v1": True,
            "http://embed.invalid/v1": True,
        },
        models={
            "http://secondary.invalid/v1": ["secondary-model"],
            "http://embed.invalid/v1": ["nomic-embed-text"],
        },
        index={
            "embed_model": "nomic-embed-text",
            "dimension": 768,
            "query_prefix": "search_query: ",
            "doc_prefix": "search_document: ",
            "qa_embed_mode": "multi",
            "qa_vector_mode": "multi",
            "q_vector_prefix": "document",
            "max_chars": 8000,
            "qa_entries": 1,
            "entry_count": 1,
        },
        texts={"prompt": "rules", "about": "facts", "qa": None},
        index_mtime=10.0,
        source_mtimes=[],
    )
    report = run_health_checks(settings, probe=probe)
    assert report.errors == []
    assert any("chat primary is not reachable" in line for line in report.warnings)
    assert "chat_primary=unreachable" in report.ready_line
    assert "chat_secondary=reachable" in report.ready_line


def test_ask_exits_nonzero_without_a_traceback(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.chat.load_settings", lambda: _settings())
    monkeypatch.setattr(
        "src.chat.run_health_checks",
        lambda _settings: HealthReport(errors=[], warnings=[], ready_line="Ready", qa_entries=0),
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise ModelUnavailable("secret-internal")

    monkeypatch.setattr("src.chat.answer_turn", boom)
    code = main(["--ask", "Hello"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == UNAVAILABLE
    assert "secret-internal" not in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out

"""compare_models settings wiring (no live OpenRouter)."""

from __future__ import annotations

from eval.compare_models import settings_for_model
from src.config import load_settings


def test_openrouter_candidate_uses_primary_connection(monkeypatch) -> None:
    base = load_settings(
        environ={
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_MODEL": "benbot-llama",
            "LLM_SECONDARY_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_SECONDARY_API_KEY": "test-key",
            "LLM_SECONDARY_MODEL": "meta-llama/llama-3.1-8b-instruct",
        }
    )
    settings = settings_for_model(
        base, "or-test", "openai/gpt-4o-mini"
    )
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "openai/gpt-4o-mini"
    assert settings.llm_secondary_base_url == ""
    assert settings.llm_temperature == 0.0


def test_baseline_keeps_local_model(monkeypatch) -> None:
    base = load_settings(
        environ={
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_MODEL": "benbot-llama",
            "LLM_SECONDARY_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_SECONDARY_API_KEY": "test-key",
            "LLM_SECONDARY_MODEL": "meta-llama/llama-3.1-8b-instruct",
        }
    )
    settings = settings_for_model(base, "baseline-local", None)
    assert settings.llm_model == "benbot-llama"
    assert settings.llm_base_url == "http://localhost:11434/v1"

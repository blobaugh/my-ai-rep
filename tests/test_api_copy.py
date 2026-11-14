"""Visitor copy built from settings."""

from __future__ import annotations

from src.api.copy import daily_limit_message, public_config
from src.config import load_settings
from tests.test_api import _settings


def test_public_config_exposes_starters_and_short_greeting() -> None:
    settings = load_settings(
        environ={
            "BOT_NAME": "AdaBot",
            "HUMAN_NAME": "Ada",
            "STARTER_QUESTIONS": "What do you do?|What tools do you use?|What do you do?",
        }
    )
    payload = public_config(settings)
    assert payload["bot_name"] == "AdaBot"
    assert "AdaBot" in str(payload["opening_message"])
    assert "an AI that speaks for" not in str(payload["opening_message"])
    assert "AI" in str(payload["ai_label"])
    assert payload["starter_questions"] == ["What do you do?", "What tools do you use?"]
    assert payload["logging_notice_short"]
    assert str(payload["logging_notice_short"]) != str(payload["logging_notice"])


def test_blank_starter_questions_means_none() -> None:
    settings = load_settings(environ={"STARTER_QUESTIONS": ""})
    assert settings.starter_questions == ()
    assert public_config(settings)["starter_questions"] == []


def test_daily_limit_uses_configured_human_name() -> None:
    settings = _settings(HUMAN_NAME="Jordan", CONTACT_URL="https://example.com/contact")
    text = daily_limit_message(settings)
    assert "Jordan" in text
    assert "Ben" not in text
    assert "https://example.com/contact" in text


def test_daily_limit_blank_human_name_matches_public_config_fallback() -> None:
    settings = _settings(HUMAN_NAME="", CONTACT_URL="mailto:hello@example.com")
    text = daily_limit_message(settings)
    assert "the person I represent" in text
    assert "Ben" not in text
    assert "mailto:hello@example.com" in text


def test_daily_limit_without_contact_url() -> None:
    settings = _settings(HUMAN_NAME="Jordan", CONTACT_URL="")
    text = daily_limit_message(settings)
    assert text == "I've reached today's message limit. Please try again tomorrow."
    assert "Ben" not in text

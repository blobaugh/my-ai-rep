"""Visitor copy built from settings."""

from __future__ import annotations

from src.api.copy import daily_limit_message
from tests.test_api import _settings


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

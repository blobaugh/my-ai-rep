"""Unit tests for VOICE_SAMPLES placeholder filling (no Ollama)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import voice_samples_enabled
from src.prompt import load_system_prompt


def test_voice_samples_enabled_defaults_off() -> None:
    assert voice_samples_enabled("") is False
    assert voice_samples_enabled("off") is False
    assert voice_samples_enabled("on") is True


def test_system_prompt_identical_when_voice_off(tmp_path: Path) -> None:
    prompt = tmp_path / "ben_system.md"
    about = tmp_path / "about.md"
    voice = tmp_path / "voice_samples.md"
    prompt.write_text(
        "Rules here.\n\n{{VOICE_SAMPLES}}About Ben:\n{{ABOUT_BEN}}\n"
        "stale={{STALE_YEARS}}\n",
        encoding="utf-8",
    )
    about.write_text("Ben facts.\n", encoding="utf-8")
    voice.write_text("How I talk:\nExample line.\n", encoding="utf-8")

    off = load_system_prompt(
        stale_years=3,
        prompt_path=prompt,
        about_path=about,
        voice_samples_path=voice,
        voice_samples=False,
    )
    assert "{{VOICE_SAMPLES}}" not in off
    assert "How I talk" not in off
    assert off == "Rules here.\n\nAbout Ben:\nBen facts.\n\nstale=3\n"


def test_system_prompt_inserts_voice_before_about_when_on(tmp_path: Path) -> None:
    prompt = tmp_path / "ben_system.md"
    about = tmp_path / "about.md"
    voice = tmp_path / "voice_samples.md"
    prompt.write_text(
        "Rules here.\n\n{{VOICE_SAMPLES}}About Ben:\n{{ABOUT_BEN}}\n",
        encoding="utf-8",
    )
    about.write_text("Ben facts.\n", encoding="utf-8")
    voice.write_text(
        'How I talk (style examples only):\nExample 1:\n"hi"\n',
        encoding="utf-8",
    )

    on = load_system_prompt(
        stale_years=3,
        prompt_path=prompt,
        about_path=about,
        voice_samples_path=voice,
        voice_samples=True,
    )
    assert "How I talk (style examples only):" in on
    rules_end = on.index("Rules here.")
    voice_at = on.index("How I talk")
    about_at = on.index("About Ben:")
    assert rules_end < voice_at < about_at


def test_real_prompt_off_has_no_voice_placeholder() -> None:
    if not Path("content/about-ben.md").is_file():
        pytest.skip("content/about-ben.md not present")
    text = load_system_prompt(stale_years=3, voice_samples=False)
    assert "{{VOICE_SAMPLES}}" not in text
    assert "{{ABOUT_BEN}}" not in text
    assert "How I talk (style examples only):" not in text
    # Stable prefix still ends rules, then About Ben.
    assert "About Ben:" in text
    assert "{{BLOG_RULES}}" not in text
    assert "How-to and technical questions are in scope" not in text
    assert text.index("15. Entries labeled") < text.index("About Ben:")


def test_real_prompt_on_places_voice_after_rules() -> None:
    if not Path("content/about-ben.md").is_file():
        pytest.skip("content/about-ben.md not present")
    if not Path("prompts/voice_samples.md").is_file():
        pytest.skip("prompts/voice_samples.md not present")
    text = load_system_prompt(stale_years=3, voice_samples=True)
    assert "How I talk (style examples only):" in text
    assert text.index("15. Entries labeled") < text.index("How I talk")
    assert text.index("How I talk") < text.index("About Ben:")

"""Visitor-facing sentences. Names come from settings, not from this file."""

from __future__ import annotations

from src.config import Settings

LOGGING_NOTICE = (
    "Conversations are logged and kept to improve the bot, and messages "
    "are processed by AI model providers. Please don't share personal information."
)
EMPTY_MESSAGE = "Please enter a message."
TOO_LONG = "That message is too long. Please shorten it."
TOO_LARGE = "That request is too large."
BAD_REQUEST = "That request could not be read."
SESSION_FULL = "This chat is full. Start a new chat to keep going."
UNAVAILABLE = "The model is not available right now. Please try again in a moment."
ERROR_TEXT = "Something went wrong. Please try again in a moment."
BUSY = "I'm busy right now. Please try again in a moment."


def daily_limit_message(settings: Settings) -> str:
    contact = settings.contact_url.strip()
    if contact:
        return (
            "I've reached today's message limit. "
            f"Please reach out to Ben directly: {contact}"
        )
    return (
        "I've reached today's message limit. Please try again tomorrow."
    )


def public_config(settings: Settings) -> dict[str, object]:
    human = settings.human_name.strip() or "the person I represent"
    bot = settings.bot_name.strip() or "Bot"
    label = settings.ai_label or f"{bot} is an AI that speaks for {human}."
    opening = settings.opening_message or (
        f"Hi, I'm {bot}, an AI that speaks for {human}. Ask me anything about them."
    )
    notice = settings.logging_notice or LOGGING_NOTICE
    return {
        "ai_label": label,
        "opening_message": opening,
        "logging_notice": notice,
        "max_message_chars": settings.message_max_chars,
        "session_max_messages": settings.session_max_messages,
        "contact_url": settings.contact_url,
    }


def strip_controls(text: str) -> str:
    """Drop control characters. Keep tab and newline so a paragraph can be typed."""
    kept: list[str] = []
    for char in text:
        code = ord(char)
        if (code in {9, 10, 13} or code >= 32) and code != 127:
            kept.append(char)
    return "".join(kept)

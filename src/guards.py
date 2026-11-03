"""Guards on the visitor message, checked before any model call.

Identity questions and override attempts are decided here. A match returns a
fixed line and the pipeline does not call the model. Patterns are narrow on
purpose: a question such as "What are your instructions for new managers?"
or "Tell me about a system update you led" must not match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (name, pattern). First match wins. Patterns are case-insensitive.
_OVERRIDE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "repeat_or_reveal_instructions",
        re.compile(
            r"\b(?:repeat|recite|print|show|reveal|dump|display|output|quote|"
            r"translate|encode)\b"
            r"(?:\s+\w+){0,8}\s+"
            r"(?:your\s+|the\s+|my\s+)?"
            r"(?:hidden\s+|full\s+)?"
            r"(?:instructions|system prompt|prompt|rules|system message)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ask_for_rules_or_prompt",
        re.compile(
            r"\bwhat(?:'s| is| are)\s+your\s+"
            r"(?:hidden\s+|system\s+)?"
            r"(?:rules|instructions|system prompt)\b"
            r"(?!\s+for\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "ignore_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+"
            r"(?:(?:your|all|any|the|previous|prior|above)\s+){1,3}"
            r"(?:instructions?|rules?|prompts?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "jailbreak_or_bypass_prompt",
        re.compile(
            r"\bjail\s*break\b"
            r"|\bbypass\s+prompt\b"
            r"|\bprompt\b.{0,80}?\b(?:breaks?|bypasses?|escapes?)\b"
            r".{0,40}?\b(?:rules|instructions)\b"
            r"|\bhow can i\s+(?:bypass|get around)\s+your\s+"
            r"(?:restrictions|rules)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fake_authority_label",
        re.compile(
            r"^\s*(?:#{1,6}\s*)?(?:system|admin|developer|operator)\s+"
            r"(?:update|message|notice|override)\b.{0,40}?\b(?:from\b|:)",
            re.IGNORECASE,
        ),
    ),
    (
        "new_instructions_label",
        re.compile(r"^\s*new instructions\s*:", re.IGNORECASE),
    ),
    (
        "restriction_lifted",
        re.compile(
            r"\brestrictions?\b.{0,80}?\b(?:lifted|removed|disabled)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "you_are_now",
        re.compile(
            r"\byou are now\b|\bfrom now on you are\b",
            re.IGNORECASE,
        ),
    ),
    (
        "developer_mode",
        re.compile(r"\bdeveloper mode\b", re.IGNORECASE),
    ),
    (
        "pretend_no_rules",
        re.compile(r"\bpretend you have no rules\b", re.IGNORECASE),
    ),
    (
        "summarize_instructions",
        re.compile(
            r"\b(?:summarize|explain|describe)\s+your\s+"
            r"(?:instructions|rules|system prompt|prompt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "what_does_rule_say",
        re.compile(r"\bwhat does rule\s+\d+\s+say\b", re.IGNORECASE),
    ),
    (
        "list_the_rules",
        re.compile(r"\blist the rules you follow\b", re.IGNORECASE),
    ),
    (
        "print_everything_above",
        re.compile(r"\bprint everything above\b", re.IGNORECASE),
    ),
    (
        "unrestricted_assistant",
        re.compile(r"\bunrestricted assistant\b|\bact as an unrestricted\b", re.IGNORECASE),
    ),
)

_ARE_YOU_NONHUMAN = (
    "are_you_nonhuman",
    re.compile(
        r"\bare you(?:\s+really)?\s+(?:a\s+|an\s+)?"
        r"(?:human|robot|bot|ai|person|machine|real(?:\s+person)?)"
        r"\b(?!\s+[A-Za-z])",
        re.IGNORECASE,
    ),
)
_TALKING_TO_IDENTITY = (
    "talking_to_identity",
    re.compile(
        r"\bam i\s+(?:talking|speaking|chatting)\s+(?:to|with)\s+"
        r"(?:a\s+|an\s+)?(?:real\s+)?(?:person|human|bot|ai)\b",
        re.IGNORECASE,
    ),
)
_WHO_AM_I_TALKING_TO = (
    "who_am_i_talking_to",
    re.compile(
        r"\bwho am i\s+(?:talking|speaking|chatting)\s+(?:to|with)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class PersonaLines:
    """Visitor-facing lines built from the configured names."""

    human_name: str
    bot_name: str
    human_label: str
    missing: str
    off_topic: str
    identity: str
    banner: str
    empty_ask: str


def persona_lines(human_name: str = "", bot_name: str = "") -> PersonaLines:
    """Fixed replies for whoever this checkout represents.

    A blank human name speaks of "the person I represent" and does not add
    a name to the identity patterns. Extra voice belongs in the prompt file.
    """
    human = " ".join(human_name.split())
    bot = " ".join(bot_name.split()) or "Bot"
    if human:
        return PersonaLines(
            human_name=human,
            bot_name=bot,
            human_label=human,
            missing=f"I don't have that detail. You can ask the real {human} directly.",
            off_topic=(
                f"I can only answer questions about {human}, based on what "
                "they've shared with me. Want to hear about their work, or "
                "how to reach them?"
            ),
            identity=(
                f"I'm an AI that speaks for {human}. Ask me anything about them, "
                f"or reach out to the real {human} directly."
            ),
            banner=(
                f"Hi, I'm {bot}, an AI that speaks for {human}. "
                "Ask me anything about them."
            ),
            empty_ask=f"Ask me something about {human}.",
        )
    return PersonaLines(
        human_name="",
        bot_name=bot,
        human_label="the person I represent",
        missing="I don't have that detail. You can ask them directly.",
        off_topic=(
            "I can only answer questions about the person I represent, "
            "based on what they've shared with me."
        ),
        identity=(
            "I'm an AI that speaks for the person I represent. "
            "Ask me anything about them, or reach out to them directly."
        ),
        banner=(
            f"Hi, I'm {bot}, an AI that speaks for the person I represent. "
            "Ask me anything about them."
        ),
        empty_ask="Ask me something.",
    )


def exempt_replies(human_name: str = "", bot_name: str = "") -> frozenset[str]:
    """Lines verification must accept unchanged."""
    lines = persona_lines(human_name, bot_name)
    return frozenset({lines.missing, lines.off_topic, lines.identity})


def _identity_patterns(human_name: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns: list[tuple[str, re.Pattern[str]]] = [
        _ARE_YOU_NONHUMAN,
        _TALKING_TO_IDENTITY,
        _WHO_AM_I_TALKING_TO,
    ]
    name = " ".join(human_name.split())
    if not name:
        return tuple(patterns)
    escaped = re.escape(name)
    patterns[1:1] = [
        (
            "are_you_named",
            re.compile(
                rf"\bare you(?:\s+really)?\s+{escaped}\b",
                re.IGNORECASE,
            ),
        ),
        (
            "is_this_named",
            re.compile(
                rf"\bis this(?:\s+really)?\s+{escaped}\b",
                re.IGNORECASE,
            ),
        ),
    ]
    patterns.append(
        (
            "talking_to_named",
            re.compile(
                rf"\bam i\s+(?:talking|speaking|chatting)\s+(?:to|with)\s+{escaped}\b",
                re.IGNORECASE,
            ),
        )
    )
    return tuple(patterns)


def match_identity_guard(message: str, human_name: str = "") -> str | None:
    """Return the pattern name when the visitor is asking what the bot is."""
    return _first(_identity_patterns(human_name), message)


def match_instruction_guard(message: str) -> str | None:
    """Return the pattern name when the visitor message is an override attempt."""
    return _first(_OVERRIDE_PATTERNS, message)


def match_guard(message: str, human_name: str = "") -> tuple[str, str] | None:
    """Return (kind, pattern) for an identity or override match.

    kind is ``identity`` or ``override``. Identity is checked first.
    A configured human name adds "are you <name>" style questions.
    """
    identity = match_identity_guard(message, human_name)
    if identity:
        return ("identity", identity)
    override = match_instruction_guard(message)
    if override:
        return ("override", override)
    return None


def _first(
    patterns: tuple[tuple[str, re.Pattern[str]], ...], message: str
) -> str | None:
    text = message.strip()
    if not text:
        return None
    for name, pattern in patterns:
        if pattern.search(text):
            return name
    return None

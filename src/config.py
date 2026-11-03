"""The only reader of .env and process environment variables.

Every entry point gets a Settings object from load_settings(). CLI flags may
override fields afterward. Nothing else in the product may call os.environ,
getenv, or load_dotenv.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.embeddings import EmbedConfig

QA_EMBED_MODES = frozenset({"question_and_answer", "question_only", "multi"})
QUERY_MODES = frozenset({"auto", "turns"})
ON_OFF = frozenset({"on", "off"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_ROOT = Path(__file__).resolve().parents[1]


def voice_samples_enabled(raw: str | None) -> bool:
    """True only when the value is 'on'. Blank means off. Other values error."""
    if raw is None:
        return False
    value = raw.strip().lower()
    if value == "":
        return False
    if value not in ON_OFF:
        raise ValueError(f"VOICE_SAMPLES must be on or off, got {raw!r}")
    return value == "on"


@dataclass(frozen=True)
class Settings:
    """Typed effective settings. Defaults match the behavior spec section 8."""

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "llama3.1:8b"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 600
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = "http://localhost:11434/v1"
    embed_api_key: str = "ollama"
    embed_batch_size: int = 32
    embed_max_chars: int = 8000
    embed_query_prefix: str = "search_query: "
    embed_doc_prefix: str = "search_document: "
    qa_embed_mode: str = "multi"
    retrieval_k: int = 4
    retrieval_max_per_article: int = 2
    retrieval_min_score: float | None = None
    weak_retrieval_score: float | None = None
    retrieval_query_mode: str = "auto"
    retrieval_query_turns: int = 2
    history_turns: int = 6
    context_budget_tokens: int = 7000
    voice_samples: str = "off"
    log_level: str = "WARNING"
    log_turns: str = "off"
    verify_prune_min_sentences: int = 2
    content_dir: str = "content"
    bot_name: str = "Bot"
    human_name: str = ""
    topic_leak_words: tuple[str, ...] = ()
    llm_primary_timeout_seconds: float = 120.0
    llm_secondary_base_url: str = ""
    llm_secondary_api_key: str = ""
    llm_secondary_model: str = ""
    llm_secondary_timeout_seconds: float = 120.0
    failover_retry_seconds: float = 300.0
    failover_on_http_status: tuple[int, ...] = ()
    db_path: str = "data/benbot.sqlite"
    session_idle_minutes: int = 60
    session_max_messages: int = 50

    def to_embed_config(self) -> EmbedConfig:
        return EmbedConfig(
            model=self.embed_model,
            base_url=self.embed_base_url,
            api_key=self.embed_api_key,
            batch_size=self.embed_batch_size,
            max_chars=self.embed_max_chars,
            query_prefix=self.embed_query_prefix,
            doc_prefix=self.embed_doc_prefix,
        )

    def with_overrides(self, **changes: Any) -> Settings:
        return replace(self, **changes)

    def masked_dict(self) -> dict[str, Any]:
        """Effective settings for printing and result files. Secrets are masked."""
        min_score: Any
        if self.retrieval_min_score is None:
            min_score = "unset"
        else:
            min_score = _format_float(self.retrieval_min_score)
        return {
            "LLM_BASE_URL": self.llm_base_url,
            "LLM_API_KEY": mask_secret(self.llm_api_key),
            "LLM_MODEL": self.llm_model,
            "LLM_PRIMARY_TIMEOUT_SECONDS": _format_float(self.llm_primary_timeout_seconds),
            "LLM_SECONDARY_BASE_URL": self.llm_secondary_base_url or "unset",
            "LLM_SECONDARY_API_KEY": (
                "unset" if not self.llm_secondary_base_url else mask_secret(self.llm_secondary_api_key)
            ),
            "LLM_SECONDARY_MODEL": self.llm_secondary_model or "unset",
            "LLM_SECONDARY_TIMEOUT_SECONDS": (
                "unset"
                if not self.llm_secondary_base_url
                else _format_float(self.llm_secondary_timeout_seconds)
            ),
            "FAILOVER_RETRY_SECONDS": _format_float(self.failover_retry_seconds),
            "FAILOVER_ON_HTTP_STATUS": (
                ",".join(str(code) for code in self.failover_on_http_status) or "unset"
            ),
            "LLM_TEMPERATURE": _format_float(self.llm_temperature),
            "LLM_MAX_TOKENS": self.llm_max_tokens,
            "EMBED_MODEL": self.embed_model,
            "EMBED_BASE_URL": self.embed_base_url,
            "EMBED_API_KEY": mask_secret(self.embed_api_key),
            "EMBED_BATCH_SIZE": self.embed_batch_size,
            "EMBED_MAX_CHARS": self.embed_max_chars,
            "EMBED_QUERY_PREFIX": self.embed_query_prefix,
            "EMBED_DOC_PREFIX": self.embed_doc_prefix,
            "QA_EMBED_MODE": self.qa_embed_mode,
            "RETRIEVAL_K": self.retrieval_k,
            "RETRIEVAL_MAX_PER_ARTICLE": self.retrieval_max_per_article,
            "RETRIEVAL_MIN_SCORE": min_score,
            "WEAK_RETRIEVAL_SCORE": (
                "unset"
                if self.weak_retrieval_score is None
                else _format_float(self.weak_retrieval_score)
            ),
            "RETRIEVAL_QUERY_MODE": self.retrieval_query_mode,
            "RETRIEVAL_QUERY_TURNS": self.retrieval_query_turns,
            "HISTORY_TURNS": self.history_turns,
            "CONTEXT_BUDGET_TOKENS": self.context_budget_tokens,
            "VOICE_SAMPLES": self.voice_samples,
            "LOG_LEVEL": self.log_level,
            "LOG_TURNS": self.log_turns,
            "VERIFY_PRUNE_MIN_SENTENCES": self.verify_prune_min_sentences,
            "CONTENT_DIR": self.content_dir,
            "DB_PATH": self.db_path,
            "SESSION_IDLE_MINUTES": self.session_idle_minutes,
            "SESSION_MAX_MESSAGES": self.session_max_messages,
            "BOT_NAME": self.bot_name,
            "HUMAN_NAME": self.human_name,
            "TOPIC_LEAK_WORDS": ",".join(self.topic_leak_words),
        }

    def hash_payload(self) -> dict[str, Any]:
        """Unmasked canonical values. Used only as hash input, never printed."""
        data = {field.name: getattr(self, field.name) for field in fields(self)}
        data["topic_leak_words"] = list(data["topic_leak_words"])
        data["failover_on_http_status"] = list(data["failover_on_http_status"])
        return data


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "***"


def format_settings(settings: Settings) -> str:
    rows = settings.masked_dict()
    lines = ["Effective settings:"]
    for key, value in rows.items():
        shown = value if isinstance(value, str) else str(value)
        lines.append(f"{key}={shown}")
    return "\n".join(lines)


def settings_hash(settings: Settings) -> str:
    raw = json.dumps(settings.hash_payload(), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_commit() -> str:
    """HEAD sha, or 'none' when this directory is not a git checkout.

    A dirty work tree appends ``-dirty`` so eval envelopes record that the
    SHA is not the exact tree that produced the run.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "none"
    if not out:
        return "none"
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return out
    if status.strip():
        return f"{out}-dirty"
    return out


# Historical defaults. Callers that pass one of these paths get CONTENT_DIR
# resolution. Any other path is used as given (tests monkeypatch these).
DEFAULT_CONTENT_FILES = {
    "about": Path("content/about.md"),
    "qa": Path("content/qa.md"),
    "facts": Path("content/facts.md"),
}


def resolve_content_file(stem: str, settings: Settings | None = None) -> Path:
    """Find ``{stem}.md`` under CONTENT_DIR, then ``{stem}.example.md``.

    Returns the preferred path when neither file exists, so callers can
    report the path they expected.
    """
    if settings is None:
        settings = load_settings()
    root = Path(settings.content_dir)
    if not root.is_absolute():
        root = _ROOT / root
    primary = root / f"{stem}.md"
    if primary.is_file():
        return _display_path(primary)
    example = root / f"{stem}.example.md"
    if example.is_file():
        return _display_path(example)
    return _display_path(primary)


def select_content_path(explicit: Path, stem: str, settings: Settings) -> Path:
    """Use a caller-supplied path. The historical default resolves via CONTENT_DIR."""
    default = DEFAULT_CONTENT_FILES.get(stem)
    if default is None or explicit != default:
        return explicit
    return resolve_content_file(stem, settings)


def _display_path(path: Path) -> Path:
    """Prefer a cwd-relative path so messages stay ``content/qa.md``."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def min_score_warning(settings: Settings) -> str | None:
    score = settings.retrieval_min_score
    if score is None or score <= 0.85:
        return None
    return (
        f"WARNING RETRIEVAL_MIN_SCORE={_format_float(score)} is above 0.85 "
        "and will likely drop all results"
    )


def load_embed_config() -> EmbedConfig:
    return load_settings().to_embed_config()


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    load_env_file: bool = True,
) -> Settings:
    """Read settings. Pass environ to skip the process environment and .env."""
    if environ is None:
        if load_env_file:
            load_dotenv()
        data: Mapping[str, str] = os.environ
    else:
        data = environ
    return _parse_settings(data)


def configure_logging(settings: Settings) -> None:
    """Console level from LOG_LEVEL. Third-party HTTP loggers stay at WARNING."""
    level = getattr(logging, settings.log_level, logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _parse_settings(data: Mapping[str, str]) -> Settings:
    llm_base = _str(data, "LLM_BASE_URL", "http://localhost:11434/v1")
    llm_key = _str(data, "LLM_API_KEY", "ollama")
    llm_model = _str(data, "LLM_MODEL", "llama3.1:8b")
    primary = _connection_group(data, "LLM_PRIMARY")
    if primary is not None:
        llm_base, llm_key, llm_model = primary
    secondary = _connection_group(data, "LLM_SECONDARY")
    if secondary is None:
        secondary_base, secondary_key, secondary_model = "", "", ""
        secondary_timeout = 120.0
    else:
        secondary_base, secondary_key, secondary_model = secondary
        secondary_timeout = _float(
            data, "LLM_SECONDARY_TIMEOUT_SECONDS", 120.0, minimum=1.0
        )
    embed_base = _optional_text(data, "EMBED_BASE_URL")
    embed_key = _optional_text(data, "EMBED_API_KEY")
    qa_embed = _choice(data, "QA_EMBED_MODE", "multi", QA_EMBED_MODES)
    voice_raw = data.get("VOICE_SAMPLES")
    if voice_raw is None or str(voice_raw).strip() == "":
        voice = "off"
    else:
        voice_samples_enabled(str(voice_raw))
        voice = str(voice_raw).strip().lower()
    log_turns = _choice(data, "LOG_TURNS", "off", ON_OFF)
    log_level = _str(data, "LOG_LEVEL", "WARNING").upper()
    if log_level not in LOG_LEVELS:
        raise ValueError(
            f"LOG_LEVEL must be one of {sorted(LOG_LEVELS)}, got {log_level!r}"
        )
    return Settings(
        llm_base_url=llm_base,
        llm_api_key=llm_key,
        llm_model=llm_model,
        llm_primary_timeout_seconds=_float(
            data, "LLM_PRIMARY_TIMEOUT_SECONDS", 120.0, minimum=1.0
        ),
        llm_secondary_base_url=secondary_base,
        llm_secondary_api_key=secondary_key,
        llm_secondary_model=secondary_model,
        llm_secondary_timeout_seconds=secondary_timeout,
        failover_retry_seconds=_float(data, "FAILOVER_RETRY_SECONDS", 300.0, minimum=0.0),
        failover_on_http_status=_http_statuses(data),
        llm_temperature=_float(data, "LLM_TEMPERATURE", 0.0, minimum=0.0),
        llm_max_tokens=_int(data, "LLM_MAX_TOKENS", 600, minimum=1),
        embed_model=_str(data, "EMBED_MODEL", "nomic-embed-text"),
        embed_base_url=embed_base if embed_base else llm_base,
        embed_api_key=embed_key if embed_key else llm_key,
        embed_batch_size=_int(data, "EMBED_BATCH_SIZE", 32, minimum=1),
        embed_max_chars=_int(data, "EMBED_MAX_CHARS", 8000, minimum=1),
        embed_query_prefix=_prefix(data, "EMBED_QUERY_PREFIX", "search_query: "),
        embed_doc_prefix=_prefix(data, "EMBED_DOC_PREFIX", "search_document: "),
        qa_embed_mode=qa_embed,
        retrieval_k=_int(data, "RETRIEVAL_K", 4, minimum=1),
        retrieval_max_per_article=_int(
            data, "RETRIEVAL_MAX_PER_ARTICLE", 2, minimum=1
        ),
        retrieval_min_score=_min_score(data),
        weak_retrieval_score=_unit_score(data, "WEAK_RETRIEVAL_SCORE"),
        retrieval_query_mode=_choice(data, "RETRIEVAL_QUERY_MODE", "auto", QUERY_MODES),
        retrieval_query_turns=_int(data, "RETRIEVAL_QUERY_TURNS", 2, minimum=1),
        history_turns=_int(data, "HISTORY_TURNS", 6, minimum=0),
        context_budget_tokens=_int(data, "CONTEXT_BUDGET_TOKENS", 7000, minimum=0),
        voice_samples=voice,
        bot_name=_str(data, "BOT_NAME", "Bot"),
        human_name=_str(data, "HUMAN_NAME", ""),
        topic_leak_words=_word_list(data, "TOPIC_LEAK_WORDS"),
        log_level=log_level,
        log_turns=log_turns,
        verify_prune_min_sentences=_int(
            data, "VERIFY_PRUNE_MIN_SENTENCES", 2, minimum=1
        ),
        content_dir=_str(data, "CONTENT_DIR", "content"),
        db_path=_str(data, "DB_PATH", "data/benbot.sqlite"),
        session_idle_minutes=_int(data, "SESSION_IDLE_MINUTES", 60, minimum=0),
        session_max_messages=_int(data, "SESSION_MAX_MESSAGES", 50, minimum=1),
    )


def _str(data: Mapping[str, str], name: str, default: str) -> str:
    if name not in data or str(data[name]).strip() == "":
        return default
    return str(data[name]).strip()


def _word_list(data: Mapping[str, str], name: str) -> tuple[str, ...]:
    """Comma-separated words. Blank means an empty list. Order is kept."""
    if name not in data or str(data[name]).strip() == "":
        return ()
    words: list[str] = []
    seen: set[str] = set()
    for part in str(data[name]).split(","):
        word = part.strip().lower()
        if not word or word in seen:
            continue
        seen.add(word)
        words.append(word)
    return tuple(words)


def _connection_group(
    data: Mapping[str, str], prefix: str
) -> tuple[str, str, str] | None:
    """Return base URL, key, and model when any of that group is set.

    Blank means unset. Setting one of the three requires all three.
    """
    names = (f"{prefix}_BASE_URL", f"{prefix}_API_KEY", f"{prefix}_MODEL")
    values = [_optional_text(data, name) for name in names]
    if not any(values):
        return None
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise ValueError(
            f"{missing[0]} is required when any {prefix}_* connection setting is set"
        )
    return values[0], values[1], values[2]


def _http_statuses(data: Mapping[str, str]) -> tuple[int, ...]:
    name = "FAILOVER_ON_HTTP_STATUS"
    if name not in data or str(data[name]).strip() == "":
        return ()
    found: list[int] = []
    seen: set[int] = set()
    for part in str(data[name]).split(","):
        raw = part.strip()
        if not raw:
            continue
        try:
            code = int(raw)
        except ValueError as exc:
            raise ValueError(
                f"{name} must be a comma-separated list of HTTP status codes, got {raw!r}"
            ) from exc
        if code < 100 or code > 599:
            raise ValueError(f"{name} must be an HTTP status code, got {raw!r}")
        if code in seen:
            continue
        seen.add(code)
        found.append(code)
    return tuple(found)


def _optional_text(data: Mapping[str, str], name: str) -> str:
    if name not in data:
        return ""
    return str(data[name]).strip()


def _prefix(data: Mapping[str, str], name: str, default: str) -> str:
    """Keep the raw value, including a trailing space. Blank or unset uses the default."""
    if name not in data or str(data[name]).strip() == "":
        return default
    return str(data[name])


def _int(data: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    if name not in data or str(data[name]).strip() == "":
        value = default
    else:
        raw = str(data[name]).strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float(
    data: Mapping[str, str], name: str, default: float, *, minimum: float
) -> float:
    if name not in data or str(data[name]).strip() == "":
        value = default
    else:
        raw = str(data[name]).strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _unit_score(data: Mapping[str, str], name: str) -> float | None:
    """A blank score is unset. A set score is a float from 0 to 1."""
    if name not in data or str(data[name]).strip() == "":
        return None
    raw = str(data[name]).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {raw!r}")
    return value


def _min_score(data: Mapping[str, str]) -> float | None:
    return _unit_score(data, "RETRIEVAL_MIN_SCORE")


def _choice(
    data: Mapping[str, str], name: str, default: str, allowed: frozenset[str]
) -> str:
    if name not in data or str(data[name]).strip() == "":
        return default
    raw = str(data[name]).strip().lower()
    if raw not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of {options}, got {raw!r}")
    return raw


def _format_float(value: float) -> str:
    return format(value, "g")

"""Startup health checks. One actionable line per failure."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import Settings, min_score_warning, resolve_content_file
from src.qa import QAParseError, parse_qa

PROMPT_PATH = Path("prompts/system.md")
ABOUT_PATH = Path("content/about.md")
QA_PATH = Path("content/qa.md")
INDEX_DIR = Path("data/index")
CHUNKS_DIR = Path("data/chunks")

REBUILD = "Run python -m src.index_chunks --rebuild"
STALE_WARNING = "WARNING index may be stale: run python -m src.index_chunks"


@dataclass
class Probe:
    """Inputs the checks read. Tests supply this; the CLI uses live_probe()."""

    reachable: dict[str, bool]
    models: dict[str, list[str]]
    index: dict[str, Any] | None
    texts: dict[str, str | None]
    index_mtime: float | None = None
    source_mtimes: list[float] = field(default_factory=list)
    about_path: Path = ABOUT_PATH
    qa_path: Path = QA_PATH


@dataclass
class HealthReport:
    errors: list[str]
    warnings: list[str]
    ready_line: str
    qa_entries: int


def run_health_checks(settings: Settings, *, probe: Probe | None = None) -> HealthReport:
    info = probe if probe is not None else live_probe(settings)
    errors: list[str] = []
    warnings: list[str] = []
    score_warning = min_score_warning(settings)
    if score_warning:
        warnings.append(score_warning)

    errors.extend(_embedder_errors(settings, info))
    warnings.extend(_chat_connection_warnings(settings, info))
    errors.extend(_missing_model_errors(settings, info))

    errors.extend(_file_errors(info))
    qa_entries = 0
    if info.index is None:
        errors.append(f"Index not found at {INDEX_DIR}. {REBUILD}")
    else:
        errors.extend(_index_mismatch_errors(settings, info.index))
        qa_entries = int(info.index.get("qa_entries") or 0)
        entry_count = int(info.index.get("entry_count") or 0)
        if entry_count < 1 and qa_entries < 1:
            errors.append(
                "The index has no entries. "
                "Run python -m src.qa && python -m src.index_chunks --rebuild"
            )
        if _index_is_stale(info):
            warnings.append(STALE_WARNING)

    ready = (
        f"Ready: model={settings.llm_model} "
        f"k={settings.retrieval_k} qa_entries={qa_entries} "
        f"temperature={_temp(settings.llm_temperature)} "
        f"voice_samples={settings.voice_samples} "
        f"query_turns={settings.retrieval_query_turns} "
        f"chat_primary={_reach_word(info, settings.llm_base_url)} "
        f"chat_secondary={_secondary_word(settings, info)}"
    )
    return HealthReport(
        errors=errors, warnings=warnings, ready_line=ready, qa_entries=qa_entries
    )


def unreachable_message(url: str) -> str:
    return f"Ollama is not reachable at {url}. Start Ollama, then try again."


def missing_llm_message(model: str, url: str) -> str:
    hint = (
        f"Pull it with: ollama pull {model} "
        f"or create a context-sized model with: ollama create {model} -f Modelfile"
    )
    return f"LLM_MODEL {model!r} was not found at {url}. {hint}"


def missing_embed_message(model: str, url: str) -> str:
    return (
        f"EMBED_MODEL {model!r} was not found at {url}. "
        f"Pull it with: ollama pull {model}"
    )


def live_probe(settings: Settings) -> Probe:
    urls = _endpoint_urls(settings)
    reachable: dict[str, bool] = {}
    models: dict[str, list[str]] = {}
    for url in urls:
        try:
            models[url] = _list_models(url)
            reachable[url] = True
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            ValueError,
        ):
            reachable[url] = False
            models[url] = []
    index, index_mtime = _read_index_summary()
    about_path = resolve_content_file("about", settings)
    qa_path = resolve_content_file("qa", settings)
    texts = {
        "prompt": _read(PROMPT_PATH),
        "about": _read(about_path),
        "qa": _read(qa_path),
    }
    source_mtimes: list[float] = []
    if qa_path.is_file():
        source_mtimes.append(qa_path.stat().st_mtime)
    if CHUNKS_DIR.is_dir():
        for path in CHUNKS_DIR.glob("*.jsonl"):
            if path.name == "chunks.jsonl":
                continue
            source_mtimes.append(path.stat().st_mtime)
    return Probe(
        reachable=reachable,
        models=models,
        index=index,
        texts=texts,
        index_mtime=index_mtime,
        source_mtimes=source_mtimes,
        about_path=about_path,
        qa_path=qa_path,
    )


def _endpoint_urls(settings: Settings) -> list[str]:
    urls = [settings.llm_base_url.rstrip("/")]
    if settings.llm_secondary_base_url:
        secondary = settings.llm_secondary_base_url.rstrip("/")
        if secondary not in urls:
            urls.append(secondary)
    embed = settings.embed_base_url.rstrip("/")
    if embed not in urls:
        urls.append(embed)
    return urls


def _embedder_errors(settings: Settings, info: Probe) -> list[str]:
    embed_url = settings.embed_base_url.rstrip("/")
    if info.reachable.get(embed_url, False):
        return []
    return [unreachable_message(embed_url)]


def _chat_connection_warnings(settings: Settings, info: Probe) -> list[str]:
    warnings: list[str] = []
    embed_url = settings.embed_base_url.rstrip("/")
    primary = settings.llm_base_url.rstrip("/")
    if not info.reachable.get(primary, False) and primary != embed_url:
        if settings.llm_secondary_base_url:
            warnings.append(
                f"WARNING chat primary is not reachable at {primary}. "
                "Requests will try the secondary connection."
            )
        else:
            warnings.append(
                f"WARNING chat primary is not reachable at {primary}. "
                "Answers will fail until it is up."
            )
    elif (
        not info.reachable.get(primary, False)
        and primary == embed_url
        and settings.llm_secondary_base_url
    ):
        warnings.append(
            "WARNING chat primary is not reachable. "
            "Requests will try the secondary connection."
        )
    secondary = settings.llm_secondary_base_url.rstrip("/")
    if secondary and not info.reachable.get(secondary, False) and secondary != embed_url:
        warnings.append(
            f"WARNING chat secondary is not reachable at {secondary}. "
            "Failover cannot use it until it is up."
        )
    if secondary and _same_chat_connection(settings):
        warnings.append(
            "WARNING LLM_SECONDARY_* matches the primary connection, "
            "so failover will not change hosts."
        )
    if (
        secondary
        and info.reachable.get(secondary, False)
        and not _model_present(settings.llm_secondary_model, info.models.get(secondary, []))
    ):
        warnings.append(
            f"WARNING secondary model {settings.llm_secondary_model!r} "
            f"was not found at {secondary}."
        )
    return warnings


def _same_chat_connection(settings: Settings) -> bool:
    return (
        settings.llm_secondary_base_url.rstrip("/") == settings.llm_base_url.rstrip("/")
        and settings.llm_secondary_api_key == settings.llm_api_key
        and settings.llm_secondary_model == settings.llm_model
    )


def _missing_model_errors(settings: Settings, info: Probe) -> list[str]:
    errors: list[str] = []
    llm_url = settings.llm_base_url.rstrip("/")
    if info.reachable.get(llm_url, False) and not _model_present(
        settings.llm_model, info.models.get(llm_url, [])
    ):
        errors.append(missing_llm_message(settings.llm_model, llm_url))
    embed_url = settings.embed_base_url.rstrip("/")
    if info.reachable.get(embed_url, False) and not _model_present(
        settings.embed_model, info.models.get(embed_url, [])
    ):
        errors.append(missing_embed_message(settings.embed_model, embed_url))
    return errors


def _reach_word(info: Probe, url: str) -> str:
    if info.reachable.get(url.rstrip("/"), False):
        return "reachable"
    return "unreachable"


def _secondary_word(settings: Settings, info: Probe) -> str:
    if not settings.llm_secondary_base_url:
        return "unset"
    return _reach_word(info, settings.llm_secondary_base_url)


def _model_present(name: str, ids: list[str]) -> bool:
    for model_id in ids:
        if model_id == name or model_id.split(":", 1)[0] == name:
            return True
    return False


def _file_errors(info: Probe) -> list[str]:
    errors: list[str] = []
    prompt = info.texts.get("prompt")
    about = info.texts.get("about")
    qa = info.texts.get("qa")
    if prompt is None:
        errors.append(f"Prompt template not found: {PROMPT_PATH}")
    elif not prompt.strip():
        errors.append(f"Prompt template is empty: {PROMPT_PATH}")
    if about is None:
        errors.append(f"Facts file not found: {info.about_path}")
    elif not about.strip():
        errors.append(f"Facts file is empty: {info.about_path}")
    if qa is not None:
        from src.knowledge import looks_like_qa

        if looks_like_qa(qa):
            try:
                parse_qa(qa)
            except QAParseError as exc:
                errors.append(f"qa.md parse error: {exc}")
    return errors


def _index_mismatch_errors(settings: Settings, index: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if str(index.get("embed_model", "")) != settings.embed_model:
        reasons.append("embed model")
    dimension = int(index.get("dimension") or 0)
    if dimension <= 0:
        reasons.append("dimension")
    if str(index.get("query_prefix", "")) != settings.embed_query_prefix:
        reasons.append("query prefix")
    if str(index.get("doc_prefix", "")) != settings.embed_doc_prefix:
        reasons.append("doc prefix")
    if str(index.get("qa_embed_mode", "")) != settings.qa_embed_mode:
        reasons.append("QA_EMBED_MODE")
    stored_vector_mode = str(index.get("qa_vector_mode") or "")
    if not stored_vector_mode:
        stored_vector_mode = (
            "multi" if str(index.get("qa_embed_mode", "")) == "multi" else "single"
        )
    expected_vector_mode = "multi" if settings.qa_embed_mode == "multi" else "single"
    if stored_vector_mode != expected_vector_mode:
        reasons.append("qa_vector_mode")
    if settings.qa_embed_mode == "multi":
        from src.qa import Q_VECTOR_PREFIX_KIND

        stored_prefix = str(index.get("q_vector_prefix") or "")
        if stored_prefix != Q_VECTOR_PREFIX_KIND:
            reasons.append("q vector prefix")
    if index.get("max_chars") not in (None, 0, settings.embed_max_chars):
        reasons.append("max_chars")
    if not reasons:
        return []
    joined = ", ".join(reasons)
    return [f"Index metadata does not match embed settings ({joined}). {REBUILD}"]


def _index_is_stale(info: Probe) -> bool:
    if info.index_mtime is None or not info.source_mtimes:
        return False
    return max(info.source_mtimes) > info.index_mtime


def _list_models(base_url: str) -> list[str]:
    url = base_url.rstrip("/") + "/models"
    with urllib.request.urlopen(url, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data") or []
    return [str(item.get("id", "")) for item in rows if isinstance(item, dict)]


def _read_index_summary() -> tuple[dict[str, Any] | None, float | None]:
    path = INDEX_DIR / "index.json"
    if not path.is_file():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or []
    ids = payload.get("ids") or []
    qa_entries = _count_source_entries(metadata, ids, "qa")
    facts_entries = _count_source_entries(metadata, ids, "facts")
    summary = {
        "embed_model": payload.get("embed_model", ""),
        "dimension": payload.get("dimension", 0),
        "query_prefix": payload.get("query_prefix", ""),
        "doc_prefix": payload.get("doc_prefix", ""),
        "qa_embed_mode": payload.get("qa_embed_mode", ""),
        "qa_vector_mode": payload.get("qa_vector_mode", ""),
        "q_vector_prefix": payload.get("q_vector_prefix", ""),
        "max_chars": payload.get("max_chars", 0),
        "qa_entries": qa_entries,
        "facts_entries": facts_entries,
        "entry_count": _count_entries(metadata, ids),
    }
    return summary, path.stat().st_mtime


def _count_entries(metadata: list[Any], ids: list[Any]) -> int:
    """Count entries of every kind. Multi-vector rows share one entry id."""
    seen: set[str] = set()
    for index, row in enumerate(metadata):
        if not isinstance(row, dict):
            continue
        entry = str(row.get("entry_id") or "")
        if not entry:
            entry = str(ids[index]) if index < len(ids) else ""
        if entry:
            seen.add(entry)
    return len(seen)


def _count_source_entries(
    metadata: list[Any], ids: list[Any], source: str
) -> int:
    """Count entries, not vectors. Multi-vector rows share one entry id."""
    seen: set[str] = set()
    for index, row in enumerate(metadata):
        if not isinstance(row, dict):
            continue
        if str(row.get("source_type", "")) != source:
            continue
        entry = str(row.get("entry_id") or "")
        if not entry:
            entry = str(ids[index]) if index < len(ids) else ""
        if entry:
            seen.add(entry)
    return len(seen)


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _temp(value: float) -> str:
    return format(value, "g")

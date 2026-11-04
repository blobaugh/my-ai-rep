"""README documents every setting exposed via src/config.py (BENBOT-33)."""

from __future__ import annotations

import re
from pathlib import Path

from src.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

ENV_KEYS = set(Settings.masked_dict(load_settings()).keys())
ENV_KEYS.update(
    {
        "LLM_PRIMARY_BASE_URL",
        "LLM_PRIMARY_API_KEY",
        "LLM_PRIMARY_MODEL",
        "LLM_PRIMARY_TIMEOUT_SECONDS",
    }
)


def test_readme_mentions_every_config_env_key() -> None:
    missing = [key for key in sorted(ENV_KEYS) if key not in README]
    assert not missing, f"README.md missing settings: {', '.join(missing)}"


def test_docs_internal_links_resolve() -> None:
    link_re = re.compile(r"\]\(([^)#]+)(?:#[^)]*)?\)")
    roots = [ROOT / "README.md", ROOT / "docs"]
    broken: list[str] = []
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.md"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        base = path.parent
        for match in link_re.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://")):
                continue
            resolved = (base / target).resolve()
            if not resolved.is_file() and not resolved.is_dir():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, "broken links:\n" + "\n".join(broken[:20])

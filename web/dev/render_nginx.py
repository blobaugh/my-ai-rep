"""Fill the nginx template from FRAME_ANCESTORS. No Dockerfile here."""

from __future__ import annotations

import sys
from pathlib import Path

from src.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "nginx.conf.template"


def render_nginx(template: str, ancestors: tuple[str, ...] | list[str]) -> str:
    if not ancestors:
        raise ValueError("FRAME_ANCESTORS is empty")
    for origin in ancestors:
        if any(mark in origin for mark in (" ", ";", "'", '"', "\n", "\r")):
            raise ValueError("FRAME_ANCESTORS entry is not safe for a header")
    if "${FRAME_ANCESTORS}" not in template:
        raise ValueError("nginx template is missing ${FRAME_ANCESTORS}")
    rendered = template.replace("${FRAME_ANCESTORS}", " ".join(ancestors))
    if "${" in rendered:
        raise ValueError("nginx template still has a placeholder")
    return rendered


def main() -> int:
    settings = load_settings()
    print(render_nginx(TEMPLATE.read_text(encoding="utf-8"), settings.frame_ancestors))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

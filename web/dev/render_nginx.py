"""Fill the nginx template from FRAME_ANCESTORS. No Dockerfile here."""

from __future__ import annotations

import sys
from pathlib import Path

from src.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "nginx.conf.template"

API_PROXY_BLOCK = """    location /api/ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
"""


def render_nginx(
    template: str,
    ancestors: tuple[str, ...] | list[str],
    *,
    dev_proxy_api: bool = False,
) -> str:
    if not ancestors:
        raise ValueError("FRAME_ANCESTORS is empty")
    for origin in ancestors:
        if any(mark in origin for mark in (" ", ";", "'", '"', "\n", "\r")):
            raise ValueError("FRAME_ANCESTORS entry is not safe for a header")
    if "__FRAME_ANCESTORS__" not in template:
        raise ValueError("nginx template is missing __FRAME_ANCESTORS__")
    if "__API_PROXY_BLOCK__" not in template:
        raise ValueError("nginx template is missing __API_PROXY_BLOCK__")
    rendered = template.replace("__FRAME_ANCESTORS__", " ".join(ancestors))
    rendered = rendered.replace(
        "__API_PROXY_BLOCK__",
        API_PROXY_BLOCK if dev_proxy_api else "",
    )
    if "__" in rendered:
        raise ValueError("nginx template still has a placeholder")
    return rendered


def main() -> int:
    settings = load_settings()
    dev = __import__("os").environ.get("DEV_PROXY_API", "").strip() == "1"
    print(render_nginx(TEMPLATE.read_text(encoding="utf-8"), settings.frame_ancestors, dev_proxy_api=dev))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

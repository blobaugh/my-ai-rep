"""FRAME_ANCESTORS defaults and the nginx template."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import load_settings
from web.dev.render_nginx import render_nginx

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "web" / "nginx.conf.template").read_text(encoding="utf-8")


def test_blank_uses_the_default_file() -> None:
    settings = load_settings(environ={})
    assert settings.frame_ancestors == (
        "https://benlobaugh.com",
        "https://www.benlobaugh.com",
        "https://ben.lobaugh.net",
    )


def test_setting_replaces_the_default() -> None:
    settings = load_settings(environ={"FRAME_ANCESTORS": "https://example.com"})
    assert settings.frame_ancestors == ("https://example.com",)


def test_star_and_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="FRAME_ANCESTORS"):
        load_settings(environ={"FRAME_ANCESTORS": "*"})
    with pytest.raises(ValueError, match="FRAME_ANCESTORS"):
        load_settings(environ={"FRAME_ANCESTORS": "https://example.com/embed"})


def test_template_pins_embed_and_locks_the_full_page() -> None:
    rendered = render_nginx(TEMPLATE, ("https://example.com", "https://www.example.com"))
    assert 'location = /embed' in rendered
    assert "frame-ancestors https://example.com https://www.example.com" in rendered
    assert "frame-ancestors 'none'" in rendered
    assert "max-age=300" in rendered
    assert "__" not in rendered
    assert "location /api/" not in rendered
    dev = render_nginx(TEMPLATE, ("https://example.com",), dev_proxy_api=True)
    assert "location /api/" in dev


def test_empty_list_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        render_nginx(TEMPLATE, ())

"""Tests for the HTML → markdown path used by Lexical raw-html nodes."""

from __future__ import annotations

from pathlib import Path

from src.lexical import html_to_markdown, lexical_to_markdown

FIXTURES = Path(__file__).parent / "fixtures"


def _raw_html_root(html: str) -> dict:
    return {
        "type": "root",
        "children": [{"type": "raw-html", "version": 1, "html": html}],
    }


def test_empty_and_whitespace_html() -> None:
    assert html_to_markdown("") == ""
    assert html_to_markdown("   \n\t  ") == ""
    assert lexical_to_markdown(_raw_html_root("  ")) == ""


def test_financing_dummies_headings_and_paragraphs() -> None:
    html = (FIXTURES / "financing_dummies.html").read_text(encoding="utf-8")
    md = html_to_markdown(html)

    assert "### ISBN:" in md
    assert "### Synopsis" in md
    assert "### Review" in md
    assert "978-0-470-42233-5" in md
    assert "practical guide to scoring cash" in md
    assert "<h3>" not in md
    assert "<p>" not in md

    # Same path via Lexical raw-html wrapper
    assert "### Synopsis" in lexical_to_markdown(_raw_html_root(html))


def test_domain_proxy_links_and_fenced_code() -> None:
    html = (FIXTURES / "domain_proxy_spaces.html").read_text(encoding="utf-8")
    md = html_to_markdown(html)

    assert "```" in md
    assert "proxy_cache_path" in md
    assert "Nginx has some powerful proxy capabilities" in md
    # .png hrefs are treated as media URLs: label kept, href dropped
    assert "https://assets.lobaugh.net/image.png" in md
    assert "](https://assets.lobaugh.net/image.png)" not in md
    assert "<pre" not in md
    assert "<a href" not in md


def test_fenced_code_collapsed_whitespace_preserved() -> None:
    """Decision: never reformat fenced code (see docs/decisions/001-...)."""
    html = (
        "<pre>proxy_cache_path /tmp/nginxcache "
        "use_temp_path=off;server {listen 80;}</pre>"
    )
    md = html_to_markdown(html)
    assert "```" in md
    assert "use_temp_path=off;server {listen 80;}" in md
    # Must not "fix" by inserting a newline between off; and server
    fence_body = md.split("```", 2)[1].removeprefix("\n")
    fence_body = fence_body.rsplit("```", 1)[0]
    assert "off;server" in fence_body
    assert "off;\nserver" not in fence_body


def test_unordered_list_html() -> None:
    md = html_to_markdown("<ul><li>Alpha</li><li>Beta</li></ul>")
    assert md == "- Alpha\n- Beta"


def test_ordered_list_html() -> None:
    md = html_to_markdown("<ol><li>First</li><li>Second</li></ol>")
    assert md == "1. First\n2. Second"


def test_html_images_dropped_without_media_urls() -> None:
    md = html_to_markdown(
        '<p>Before<img src="https://cdn.example/secret.jpg" alt="boat" />After</p>'
    )
    assert md == "BeforeAfter"
    assert "secret.jpg" not in md
    assert "https://" not in md
    assert "<img" not in md


def test_html_link() -> None:
    md = html_to_markdown('<p>See <a href="https://example.com/x">Example</a>.</p>')
    assert md == "See [Example](https://example.com/x)."

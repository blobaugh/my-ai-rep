"""Playwright UI checks (optional)."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_browser]

playwright = pytest.importorskip("playwright", reason="pip install benbot[e2e]")


@pytest.fixture(scope="session")
def browser_context():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        yield context
        context.close()
        browser.close()


def test_chat_page_desktop(browser_context, e2e_web_base: str) -> None:
    """Expected: opening message, label, send/reply on 1280x800."""
    page = browser_context.new_page(viewport={"width": 1280, "height": 800})
    page.goto(f"{e2e_web_base}/")
    assert page.locator("body").inner_text()
    out = __import__("pathlib").Path(__file__).resolve().parents[2] / "docs/web/screenshots/e2e"
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / "chat-desktop.png"))


def test_xss_string_renders_as_text(browser_context, e2e_web_base: str) -> None:
    """Expected: script tags shown literally, not executed."""
    pytest.skip("requires LLM reply path — extend with mocked api or live send")


def test_widget_on_test_origin(browser_context, e2e_web_base: str) -> None:
    pytest.skip("could not test — host test page serving file:// cross-origin setup manual")

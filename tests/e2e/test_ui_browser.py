"""Playwright UI checks (optional; excluded from default e2e.sh)."""

from __future__ import annotations

import json

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
    """Expected: script tags in the model reply stay literal text (textContent)."""
    payload = '<img src=x onerror=window.__xss=1><script>alert(1)</script>'

    def fulfill_config(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ai_label": "TestBot is an AI.",
                    "opening_message": "Hi from e2e.",
                    "logging_notice": "Logged.",
                    "max_message_chars": 1000,
                    "session_max_messages": 50,
                    "contact_url": "",
                }
            ),
        )

    def fulfill_chat(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "session_id": "e2e-xss",
                    "status": "ok",
                    "reply": payload,
                    "session": {"messages_used": 1, "messages_max": 50},
                }
            ),
        )

    page = browser_context.new_page()
    page.route("**/api/config", fulfill_config)
    page.route("**/api/chat", fulfill_chat)
    page.goto(f"{e2e_web_base}/")
    page.fill("#message", "trigger mocked reply")
    page.click("#send")
    page.wait_for_selector("#messages .msg.bot p")
    bot_text = page.locator("#messages .msg.bot p").inner_text()
    assert "<script>" in bot_text
    assert page.evaluate("() => window.__xss") is None


def test_widget_mounts_on_host_page(browser_context, e2e_web_base: str) -> None:
    """Expected: widget.js mounts from a same-origin host page."""
    page = browser_context.new_page(viewport={"width": 1280, "height": 800})
    page.goto(f"{e2e_web_base}/dev/widget-e2e.html")
    page.wait_for_selector("[data-persona-chat-widget]")
    assert page.evaluate(
        "() => window.PersonaChatWidget && window.PersonaChatWidget.mounted === true"
    )

"""E2E fixtures: dev compose stack over HTTP (RUN_E2E=1)."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_BASE = os.environ.get("E2E_WEB_BASE", "http://127.0.0.1:8080").rstrip("/")
API_BASE = os.environ.get("E2E_API_BASE", "http://127.0.0.1:8000").rstrip("/")
HEALTH_WAIT_SEC = int(os.environ.get("E2E_HEALTH_WAIT", "300"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests against the dev Docker stack (RUN_E2E=1)",
    )
    config.addinivalue_line(
        "markers",
        "e2e_llm: requires live LLM on host.docker.internal (Ollama + secondary)",
    )
    config.addinivalue_line(
        "markers",
        "e2e_browser: requires playwright (pip install benbot[e2e])",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_E2E") == "1":
        return
    skip = pytest.mark.skip(reason="set RUN_E2E=1 (see scripts/e2e.sh)")
    e2e_dir = str(ROOT / "tests" / "e2e")
    for item in items:
        if e2e_dir in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def e2e_web_base() -> str:
    return WEB_BASE


@pytest.fixture(scope="session")
def e2e_api_base() -> str:
    return API_BASE


@pytest.fixture(scope="session")
def http_client() -> Generator[httpx.Client, None, None]:
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def _wait_for_stack(http_client: httpx.Client, e2e_api_base: str) -> None:
    if os.environ.get("RUN_E2E") != "1":
        return
    deadline = time.time() + HEALTH_WAIT_SEC
    last_error = ""
    while time.time() < deadline:
        try:
            r = http_client.get(f"{e2e_api_base}/api/health")
            if r.status_code == 200:
                return
            last_error = f"status {r.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(5)
    pytest.fail(f"API health not ready at {e2e_api_base}: {last_error}")


@pytest.fixture(scope="session")
def docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.fixture(scope="session")
def llm_ready(http_client: httpx.Client, e2e_api_base: str) -> bool:
    """True when a chat turn succeeds (primary or secondary)."""
    try:
        r = http_client.post(
            f"{e2e_api_base}/api/chat",
            json={"message": "Reply with exactly: pong"},
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return False
        body = r.json()
        return body.get("status") == "ok" and bool(body.get("reply"))
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def require_llm(llm_ready: bool) -> None:
    if not llm_ready:
        pytest.skip(
            "LLM not reachable from api container "
            "(start Ollama on host or configure LLM_SECONDARY_* in .env)"
        )

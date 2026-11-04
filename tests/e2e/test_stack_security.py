"""Network, headers, and image checks — no LLM required."""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.e2e


def test_api_health_via_web_proxy(http_client, e2e_web_base: str) -> None:
    """Expected: dev web proxies /api to api (DEV_PROXY_API=1)."""
    r = http_client.get(f"{e2e_web_base}/api/health")
    assert r.status_code == 200
    assert "status" in r.json()


def test_embed_frame_ancestors_header(http_client, e2e_web_base: str) -> None:
    """Expected: CSP frame-ancestors lists allowed embed origins."""
    r = http_client.get(f"{e2e_web_base}/embed")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp.lower()
    assert "benlobaugh.com" in csp or "ben.lobaugh.net" in csp


def test_chat_page_has_no_api_only_json(http_client, e2e_web_base: str) -> None:
    r = http_client.get(f"{e2e_web_base}/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_embedder_has_no_published_port(docker_available: bool) -> None:
    """Expected: embedder is internal-only (BENBOT-24)."""
    if not docker_available:
        pytest.skip("docker not available")
    out = subprocess.run(
        ["docker", "port", "benbot_embedder"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip() == "" and out.stderr.strip() == ""


def test_dev_images_no_private_paths(docker_available: bool) -> None:
    """Expected: BENBOT-30 verify passes on dev-built api image."""
    if not docker_available:
        pytest.skip("docker not available")
    image = "benbot/api:dev"
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip(f"{image} not built yet (run e2e.sh)")
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    script = root / "scripts" / "verify_image.sh"
    run = subprocess.run(
        [str(script), image], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr or run.stdout

"""Compose files stay valid without calling docker."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DEV = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_production_compose_is_pull_only() -> None:
    assert "name: benbot" in PROD
    assert "build:" not in PROD
    assert "127.0.0.1:" not in PROD
    assert "container_name: benbot_api" in PROD
    assert "container_name: benbot_web" in PROD
    assert "container_name: benbot_embedder" in PROD
    assert "platform: linux/amd64" in PROD
    assert "internal: true" in PROD
    assert "DEV_PROXY_API: \"0\"" in PROD


def test_dev_override_builds_and_publishes_localhost_ports() -> None:
    assert DEV.count("build:") == 3
    assert "127.0.0.1:8080:8080" in DEV
    assert "127.0.0.1:8000:8000" in DEV
    assert "DEV_PROXY_API: \"1\"" in DEV
    assert "host.docker.internal" in DEV
    assert "examples:/content:ro" in DEV
    assert "external: false" in DEV


def test_dockerignore_keeps_private_paths_out() -> None:
    assert "content/**" in DOCKERIGNORE
    assert "data/**" in DOCKERIGNORE
    assert ".env" in DOCKERIGNORE
    assert "!src/**" in DOCKERIGNORE

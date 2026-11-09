"""Compose files stay valid without calling docker."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DEV = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
CHECKOUT = (ROOT / "docker-compose.checkout.yml").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_production_compose_is_pull_only() -> None:
    assert "name: benbot" in PROD
    assert "build:" not in PROD
    assert "127.0.0.1:" not in PROD
    assert "container_name: benbot_api" in PROD
    assert "container_name: benbot_web" in PROD
    assert "container_name: benbot_embedder" in PROD
    assert "container_name: benbot_backup" in PROD
    assert "profiles:" in PROD
    assert 'profiles: ["tools"]' in PROD or "profiles: [\"tools\"]" in PROD
    assert "src.ingest" in PROD
    assert "platform: linux/amd64" in PROD
    assert "internal: true" in PROD
    assert "DEV_PROXY_API: \"0\"" in PROD


def test_checkout_overlay_builds_without_host_ports() -> None:
    assert CHECKOUT.count("build:") == 4
    assert "127.0.0.1:" not in CHECKOUT
    assert "DEV_PROXY_API" not in CHECKOUT
    assert "host.docker.internal" not in CHECKOUT
    assert "examples:/content:ro" in CHECKOUT
    assert "external: false" not in CHECKOUT


def test_dev_override_builds_and_publishes_localhost_ports() -> None:
    assert DEV.count("build:") == 5
    assert "minio:" in DEV
    assert "pgsty/silo" in DEV or "minio/minio" in DEV
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

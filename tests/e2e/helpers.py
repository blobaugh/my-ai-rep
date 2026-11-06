"""HTTP helpers for e2e tests."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "docker-compose.e2e.yml",
)


def compose_cmd(*extra_files: str) -> list[str]:
    """Docker compose argv for the dev e2e stack (optional failover override)."""
    files = list(_COMPOSE_FILES)
    if os.environ.get("E2E_FAILOVER") == "1":
        files.append("docker-compose.e2e-failover.yml")
    files.extend(extra_files)
    args = ["docker", "compose"]
    for name in files:
        args.extend(["-f", name])
    return args


COMPOSE_E2E = compose_cmd()
_SETTING_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=")


def strip_cli_ask_stdout(raw: str) -> str:
    """Drop health warnings and settings dump; keep the answer line(s)."""
    kept: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("WARNING "):
            continue
        if text.startswith("Effective settings:"):
            continue
        if _SETTING_LINE.match(text):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def compose_exec(service: str, *cmd: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*compose_cmd(), "exec", "-T", service, *cmd],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )


def ensure_minio_bucket() -> subprocess.CompletedProcess[str]:
    """Create the dev backup bucket on Silo/MinIO when missing (e2e only)."""
    code = (
        "from botocore.exceptions import ClientError\n"
        "from src.backup import spaces\n"
        "from src.backup.settings import load_backup_settings\n"
        "s = load_backup_settings()\n"
        "c = spaces._client(s)\n"
        "try:\n"
        "    c.head_bucket(Bucket=s.spaces_bucket)\n"
        "except ClientError:\n"
        "    c.create_bucket(Bucket=s.spaces_bucket)\n"
    )
    return compose_exec("api", "python", "-c", code, timeout=60)


def compose_run(service: str, *cmd: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*compose_cmd(), "run", "--rm", "-T", service, *cmd],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )


def run_ingest_via_api_exec() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            *compose_cmd(),
            "exec",
            "-T",
            "api",
            "sh",
            "-c",
            "mkdir -p /app/data/tmp && TMPDIR=/app/data/tmp python -m src.ingest",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=600,
        check=False,
    )


def cli_ask_in_api_container(question: str) -> str:
    run = subprocess.run(
        [
            *compose_cmd(),
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "src.chat",
            "--ask",
            question,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if run.returncode != 0:
        msg = (run.stderr or run.stdout).strip()
        raise RuntimeError(f"cli --ask failed ({run.returncode}): {msg[:500]}")
    reply = strip_cli_ask_stdout(run.stdout)
    if not reply:
        raise RuntimeError(f"cli --ask empty after strip: {run.stdout[:500]!r}")
    return reply


def image_architecture(image: str) -> str | None:
    run = subprocess.run(
        ["docker", "image", "inspect", "-f", "{{.Architecture}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        return None
    return run.stdout.strip()


def post_chat(
    client: httpx.Client,
    base: str,
    message: str,
    *,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    if history is not None:
        payload["history"] = history
    return client.post(
        f"{base.rstrip('/')}/api/chat",
        json=payload,
        headers={"Content-Type": "application/json"},
    )


def chat_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    return response.json()


def record_scenario(
    results: list[dict[str, str]],
    *,
    scenario: str,
    expected: str,
    actual: str,
    passed: bool,
    evidence: str = "",
) -> None:
    results.append(
        {
            "scenario": scenario,
            "expected": expected,
            "actual": actual,
            "result": "pass" if passed else "fail",
            "evidence": evidence,
        }
    )

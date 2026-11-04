"""Deployment runbook files exist (BENBOT-29)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "docs" / "deploy"

REQUIRED = (
    "README.md",
    "droplet-setup.md",
    "verify.md",
    "operations.md",
    "mac-connectivity.md",
    "troubleshooting.md",
    "ci.md",
    "content.md",
    "backup-restore.md",
)


def test_deploy_docs_present() -> None:
    for name in REQUIRED:
        assert (DEPLOY / name).is_file(), name


def test_verify_deploy_local_script_exists() -> None:
    path = ROOT / "scripts" / "verify-deploy-local.sh"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("#!/")

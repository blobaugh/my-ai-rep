"""CONTENT_DIR resolution, git SHA notes, and the public-safety check."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import git_commit, load_settings, resolve_content_file

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_public_safe.sh"


def test_product_source_does_not_name_a_person() -> None:
    banned = ("Ben Lobaugh", "ben.lobaugh", "sailing", "benbot-llama", "Ben's ")
    hits: list[str] = []
    for folder in ("src", "prompts"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            if path.name == "voice_samples.md":
                continue
            text = path.read_text(encoding="utf-8")
            for word in banned:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}:{word}")
    assert hits == []


def test_content_dir_blank_means_content() -> None:
    settings = load_settings(environ={"CONTENT_DIR": "  "})
    assert settings.content_dir == "content"


def test_resolve_prefers_markdown_then_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    examples = tmp_path / "examples"
    examples.mkdir()
    sample = examples / "qa.example.md"
    sample.write_text("example\n", encoding="utf-8")
    monkeypatch.setattr("src.config._ROOT", tmp_path)
    settings = load_settings(environ={"CONTENT_DIR": "examples"})
    found = resolve_content_file("qa", settings)
    assert found.name == "qa.example.md"
    assert found.is_file()
    real = examples / "qa.md"
    real.write_text("real\n", encoding="utf-8")
    assert resolve_content_file("qa", settings).name == "qa.md"


def test_git_commit_notes_a_dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_check_output(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return "abc123\n"
        if cmd[:2] == ["git", "status"]:
            return " M src/config.py\n"
        raise AssertionError(cmd)

    monkeypatch.setattr("src.config.subprocess.check_output", fake_check_output)
    assert git_commit() == "abc123-dirty"


def test_git_commit_is_sha_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_check_output(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return "abc123\n"
        if cmd[:2] == ["git", "status"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr("src.config.subprocess.check_output", fake_check_output)
    assert git_commit() == "abc123"


def test_git_commit_none_without_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_check_output(cmd, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr("src.config.subprocess.check_output", fake_check_output)
    assert git_commit() == "none"


def _init_repo(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(SCRIPT, scripts / "check_public_safe.sh")
    os.chmod(scripts / "check_public_safe.sh", 0o755)
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    (tmp_path / "ok.txt").write_text("hello\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "ok.txt"], cwd=tmp_path)


def test_check_script_passes_on_a_clean_file_and_fails_on_a_secret(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    good = subprocess.run(
        ["sh", "scripts/check_public_safe.sh"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0, good.stderr
    secret = tmp_path / "leak.txt"
    secret.write_text("token " + "sk-" + ("A" * 12) + "\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "leak.txt"], cwd=tmp_path)
    bad = subprocess.run(
        ["sh", "scripts/check_public_safe.sh", "--staged"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    assert "secret pattern" in bad.stderr


def test_check_script_fails_on_a_staged_env_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=local\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "-f", ".env"], cwd=tmp_path)
    bad = subprocess.run(
        ["sh", "scripts/check_public_safe.sh", "--staged"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    assert "private path: .env" in bad.stderr

"""GitLab CI artifacts and verify_image helpers (no live GitLab)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITLAB_CI = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
VERIFY_SH = (ROOT / "scripts" / "verify_image.sh").read_text(encoding="utf-8")


def test_gitlab_ci_declares_required_stages() -> None:
    for stage in ("lint", "test", "scan", "build", "verify-images"):
        assert stage in GITLAB_CI


def test_gitlab_ci_builds_all_product_images() -> None:
    for part in ("/api", "/web", "/embedder", "/backup"):
        assert part in GITLAB_CI
    assert "linux/amd64" in GITLAB_CI or "BENBOT_BUILD_PLATFORM" in GITLAB_CI


def test_gitlab_ci_does_not_use_github_repo_name_as_image() -> None:
    assert "my-ai-rep" not in GITLAB_CI


def test_verify_image_script_checks_architecture_and_content() -> None:
    assert "Architecture" in VERIFY_SH or "amd64" in VERIFY_SH
    assert "qa*.md" in VERIFY_SH
    assert "--allow-root" in VERIFY_SH


def test_ci_scripts_exist_and_are_shell() -> None:
    for rel in (
        "scripts/ci/lint.sh",
        "scripts/ci/test.sh",
        "scripts/ci/scan.sh",
        "scripts/ci/build_images.sh",
        "scripts/ci/verify_images.sh",
    ):
        path = ROOT / rel
        assert path.is_file(), rel
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("#!/"), rel

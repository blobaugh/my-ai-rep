"""MinIO backup while the api stack is up (dev compose includes Silo)."""

from __future__ import annotations

import pytest

from tests.e2e.helpers import chat_json, compose_exec, ensure_minio_bucket, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm, pytest.mark.e2e_backup]


def test_backup_upload_while_chatting(http_client, e2e_web_base, require_llm) -> None:
    """Expected: backup run uploads a snapshot after chat created the database."""
    chat_json(post_chat(http_client, e2e_web_base, "Who is Ben?"))

    bucket = ensure_minio_bucket()
    if bucket.returncode != 0:
        pytest.fail(bucket.stderr or bucket.stdout)

    # Exec on api (WAL sqlite; reach Silo via host.docker.internal in e2e compose).
    run = compose_exec("api", "python", "-m", "src.backup", "run", timeout=120)
    if run.returncode != 0:
        pytest.fail(run.stderr or run.stdout)
    keys = [line.strip() for line in run.stdout.splitlines() if line.strip()]
    assert keys, "backup run printed no object keys"

    listed = compose_exec("api", "python", "-m", "src.backup", "list", timeout=60)
    if listed.returncode != 0:
        pytest.fail(listed.stderr or listed.stdout)
    for key in keys:
        assert key in listed.stdout

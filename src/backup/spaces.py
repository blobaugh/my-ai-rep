"""DigitalOcean Spaces and other S3-compatible uploads."""

from __future__ import annotations

import gzip
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.client import Config

from src.backup.settings import BackupSettings

logger = logging.getLogger(__name__)

_PATH_STYLE_HOSTS = frozenset({"localhost", "127.0.0.1", "minio"})


def _addressing_style(settings: BackupSettings) -> str:
    mode = settings.spaces_addressing_style.strip().lower()
    if mode in ("path", "virtual"):
        return mode
    host = (urlparse(settings.spaces_endpoint).hostname or "").lower()
    return "path" if host in _PATH_STYLE_HOSTS else "virtual"


def _client(settings: BackupSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_key,
        aws_secret_access_key=settings.spaces_secret,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": _addressing_style(settings)},
        ),
        region_name=settings.spaces_region,
    )


def compress_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as plain, gzip.open(destination, "wb") as gz:
        while True:
            chunk = plain.read(1024 * 1024)
            if not chunk:
                break
            gz.write(chunk)


def upload_file(settings: BackupSettings, path: Path, key: str) -> int:
    client = _client(settings)
    size = path.stat().st_size
    client.upload_file(str(path), settings.spaces_bucket, key)
    head = client.head_object(Bucket=settings.spaces_bucket, Key=key)
    remote = int(head.get("ContentLength") or 0)
    if remote != size:
        raise RuntimeError(f"upload size mismatch for {key}: local={size} remote={remote}")
    return size


def download_file(settings: BackupSettings, key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _client(settings).download_file(settings.spaces_bucket, key, str(path))


def list_keys(settings: BackupSettings, prefix: str) -> list[str]:
    client = _client(settings)
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": settings.spaces_bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for row in page.get("Contents") or []:
            keys.append(str(row["Key"]))
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return sorted(keys)


def ping_success(url: str) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as response:
        if response.status >= 400:
            raise RuntimeError(f"ping returned HTTP {response.status}")

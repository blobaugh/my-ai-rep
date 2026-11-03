"""Unit tests for embeddings helpers (mocked client, no Ollama)."""

from __future__ import annotations

from typing import Any

import pytest

from src.embeddings import (
    EmbedConfig,
    EmbeddingError,
    apply_prefix,
    embed_texts,
    truncate_text,
)


def test_truncate_text() -> None:
    text, flag = truncate_text("abcdef", 4)
    assert text == "abcd"
    assert flag is True
    text2, flag2 = truncate_text("abc", 10)
    assert text2 == "abc"
    assert flag2 is False


def test_apply_prefix() -> None:
    assert apply_prefix("hello", "search_document: ") == "search_document: hello"
    assert apply_prefix("hello", "") == "hello"


def test_batching_and_retry_with_mocked_client() -> None:
    calls: list[list[str]] = []
    failures_left = {"n": 1}

    class FakeItem:
        def __init__(self, index: int, embedding: list[float]) -> None:
            self.index = index
            self.embedding = embedding

    class FakeResp:
        def __init__(self, data: list[FakeItem]) -> None:
            self.data = data

    class FakeClient:
        def __init__(self) -> None:
            self.embeddings = self

        def create(self, model: str, input: list[str]) -> Any:
            calls.append(list(input))
            if failures_left["n"] > 0:
                failures_left["n"] -= 1

                class Boom(Exception):
                    status_code = 503

                raise Boom("transient")
            return FakeResp(
                [FakeItem(i, [float(i + 1), 0.0]) for i in range(len(input))]
            )

    slept: list[float] = []
    cfg = EmbedConfig(
        model="fake",
        base_url="http://example",
        api_key="x",
        batch_size=2,
        max_chars=100,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )
    vectors, truncated = embed_texts(
        ["a", "b", "c"],
        config=cfg,
        kind="document",
        client=FakeClient(),
        sleep=slept.append,
    )
    assert len(calls) == 3  # one failed batch + two successful batches
    assert len(vectors) == 3
    assert truncated == [False, False, False]
    assert slept  # retried once


def test_non_transient_error_raises() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.embeddings = self

        def create(self, model: str, input: list[str]) -> Any:
            class Boom(Exception):
                status_code = 400

            raise Boom("bad request")

    cfg = EmbedConfig(
        model="fake",
        base_url="http://example",
        api_key="x",
        batch_size=8,
        max_retries=2,
    )
    with pytest.raises(EmbeddingError):
        embed_texts(["a"], config=cfg, client=FakeClient(), sleep=lambda _: None)


def test_truncation_flag_from_embed_texts() -> None:
    class FakeItem:
        def __init__(self, index: int) -> None:
            self.index = index
            self.embedding = [1.0, 0.0]

    class FakeResp:
        def __init__(self, n: int) -> None:
            self.data = [FakeItem(i) for i in range(n)]

    class FakeClient:
        def __init__(self) -> None:
            self.embeddings = self

        def create(self, model: str, input: list[str]) -> Any:
            assert all(len(t) <= 5 for t in input)
            return FakeResp(len(input))

    cfg = EmbedConfig(
        model="fake",
        base_url="http://example",
        api_key="x",
        max_chars=5,
    )
    _, truncated = embed_texts(
        ["123456789"],
        config=cfg,
        client=FakeClient(),
        sleep=lambda _: None,
    )
    assert truncated == [True]

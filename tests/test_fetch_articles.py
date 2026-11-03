"""Tests for article fetch pagination and published filter (mocked HTTP)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.fetch_articles import (
    ARTICLES_QUERY,
    PUBLISHED_WHERE,
    FetchError,
    fetch_all_articles,
    fetch_articles_page,
    post_graphql,
)


def _article(doc_id: int) -> dict[str, Any]:
    return {
        "id": doc_id,
        "title": f"Title {doc_id}",
        "slug": f"slug-{doc_id}",
        "createdAt": "2024-01-01T00:00:00.000Z",
        "updatedAt": "2024-01-02T00:00:00.000Z",
        "publishedAt": "2024-01-03T00:00:00.000Z",
        "_status": "published",
        "content": {"root": {"children": []}},
    }


def _articles_payload(
    docs: list[dict[str, Any]],
    *,
    page: int,
    total_docs: int,
    has_next: bool,
) -> dict[str, Any]:
    return {
        "data": {
            "Articles": {
                "totalDocs": total_docs,
                "totalPages": 2 if has_next or page > 1 else 1,
                "page": page,
                "hasNextPage": has_next,
                "docs": docs,
            }
        }
    }


def _mock_urlopen(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return MagicMock(return_value=response)


def test_post_graphql_sends_published_where() -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float = 0) -> MagicMock:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        response = MagicMock()
        response.read.return_value = json.dumps(
            _articles_payload([_article(1)], page=1, total_docs=1, has_next=False)
        ).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = fetch_articles_page(
            "https://cms.example/api/graphql", page=1, limit=10
        )

    assert result["docs"][0]["id"] == 1
    assert captured["body"]["query"] == ARTICLES_QUERY
    assert captured["body"]["variables"]["where"] == PUBLISHED_WHERE
    assert captured["body"]["variables"]["where"]["_status"]["equals"] == "published"
    assert captured["body"]["variables"]["page"] == 1
    assert captured["body"]["variables"]["limit"] == 10


def test_fetch_all_articles_paginates_until_has_next_false() -> None:
    page_payloads = {
        1: _articles_payload(
            [_article(1), _article(2)], page=1, total_docs=3, has_next=True
        ),
        2: _articles_payload([_article(3)], page=2, total_docs=3, has_next=False),
    }
    calls: list[int] = []

    def fake_urlopen(request: Any, timeout: float = 0) -> MagicMock:
        body = json.loads(request.data.decode("utf-8"))
        page = body["variables"]["page"]
        calls.append(page)
        assert body["variables"]["where"] == PUBLISHED_WHERE
        response = MagicMock()
        response.read.return_value = json.dumps(page_payloads[page]).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    with (
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch("src.fetch_articles.time.sleep") as sleep_mock,
    ):
        docs = fetch_all_articles(
            "https://cms.example/api/graphql",
            limit=2,
            page_delay=0.1,
        )

    assert [doc["id"] for doc in docs] == [1, 2, 3]
    assert calls == [1, 2]
    sleep_mock.assert_called_once_with(0.1)


def test_fetch_all_articles_raises_on_count_mismatch() -> None:
    payload = _articles_payload([_article(1)], page=1, total_docs=2, has_next=False)

    with (
        patch("urllib.request.urlopen", _mock_urlopen(payload)),
        pytest.raises(FetchError, match="totalDocs was 2"),
    ):
        fetch_all_articles("https://cms.example/api/graphql", page_delay=0)


def test_post_graphql_raises_on_graphql_errors() -> None:
    payload = {"errors": [{"message": "boom"}]}

    with (
        patch("urllib.request.urlopen", _mock_urlopen(payload)),
        pytest.raises(FetchError, match="GraphQL errors"),
    ):
        post_graphql(
            "https://cms.example/api/graphql",
            ARTICLES_QUERY,
            {"limit": 1, "page": 1, "where": PUBLISHED_WHERE},
        )

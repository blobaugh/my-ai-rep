"""Fetch published Articles from Payload CMS GraphQL into a raw JSON cache."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ARTICLE_FIELDS = (
    "id",
    "title",
    "slug",
    "createdAt",
    "updatedAt",
    "publishedAt",
    "_status",
    "content",
)

DEFAULT_PAGE_SIZE = 50
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_PAGE_DELAY_SECONDS = 0.25

OUTPUT_PATH = Path("data/raw/articles.json")

ARTICLES_QUERY = """
query FetchArticles($limit: Int!, $page: Int!, $where: Article_where) {
  Articles(limit: $limit, page: $page, where: $where) {
    totalDocs
    totalPages
    page
    hasNextPage
    docs {
      id
      title
      slug
      createdAt
      updatedAt
      publishedAt
      _status
      content
    }
  }
}
""".strip()

PUBLISHED_WHERE: dict[str, Any] = {"_status": {"equals": "published"}}


class FetchError(RuntimeError):
    """Raised when the CMS GraphQL request or response is unusable."""


def load_graphql_url() -> str:
    """Return CMS_GRAPHQL_URL. Required only by the fetch step."""
    from src.config import load_settings

    url = load_settings().cms_graphql_url.strip()
    if not url:
        raise FetchError("CMS_GRAPHQL_URL is not set in the environment or .env")
    return url


def post_graphql(
    url: str,
    query: str,
    variables: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST a GraphQL query and return the parsed JSON body."""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FetchError(f"GraphQL HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"GraphQL request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"GraphQL request timed out after {timeout}s") from exc

    try:
        parsed: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(f"GraphQL response was not valid JSON: {exc}") from exc

    if parsed.get("errors"):
        raise FetchError(f"GraphQL errors: {json.dumps(parsed['errors'])}")

    return parsed


def fetch_articles_page(
    url: str,
    page: int,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch one page of Articles and return the Articles payload."""
    variables = {
        "limit": limit,
        "page": page,
        "where": PUBLISHED_WHERE if where is None else where,
    }
    parsed = post_graphql(url, ARTICLES_QUERY, variables, timeout=timeout)
    data = parsed.get("data") or {}
    articles = data.get("Articles")
    if not isinstance(articles, dict):
        raise FetchError("GraphQL response missing data.Articles")
    return articles


def fetch_all_articles(
    url: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    page_delay: float = DEFAULT_PAGE_DELAY_SECONDS,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Page through published Articles until hasNextPage is false."""
    docs: list[dict[str, Any]] = []
    page = 1
    expected_total: int | None = None

    while True:
        articles = fetch_articles_page(
            url,
            page,
            limit=limit,
            timeout=timeout,
            where=where,
        )
        page_docs = articles.get("docs")
        if not isinstance(page_docs, list):
            raise FetchError(f"Articles page {page} missing docs list")

        if expected_total is None:
            total = articles.get("totalDocs")
            if not isinstance(total, int):
                raise FetchError("Articles response missing integer totalDocs")
            expected_total = total

        docs.extend(page_docs)

        has_next = articles.get("hasNextPage")
        if has_next is not True:
            break

        page += 1
        if page_delay > 0:
            time.sleep(page_delay)

    if expected_total is not None and len(docs) != expected_total:
        raise FetchError(
            f"Fetched {len(docs)} articles but totalDocs was {expected_total}"
        )

    return docs


def write_articles(docs: list[dict[str, Any]], path: Path = OUTPUT_PATH) -> None:
    """Overwrite path with the raw article list as pretty JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> int:
    """CLI entry: fetch articles and write data/raw/articles.json."""
    try:
        url = load_graphql_url()
        docs = fetch_all_articles(url)
        write_articles(docs)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(docs)} articles to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compare embeddings from two OpenAI-compatible /v1 endpoints."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI

from src.config import load_settings

DEFAULT_TEXTS = [
    "What does AI-first mean to you?",
    "How do you approach product discovery?",
    "Tell me about your experience with WordPress.",
    "What is retrieval-augmented generation?",
    "Short ping.",
    "A five sentence passage about building software teams that communicate clearly, ship incrementally, measure outcomes instead of outputs, and keep documentation close to the code so newcomers can contribute within a week.",
    "Pottery on weekends.",
    "Q: Who are you?\nA: I am a builder.",
    "search_query: pricing for enterprise",
    "search_document: Our SLA covers 99.9% uptime.",
    "Embedding portability check line eleven.",
    "Twelve.",
    "Thirteen with unicode: café naïve résumé.",
    "Fourteen " + "word " * 40,
    "Fifteen.",
    "Sixteen.",
    "Seventeen.",
    "Eighteen.",
    "Nineteen.",
    "Twenty.",
]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def embed(client: OpenAI, model: str, text: str) -> list[float]:
    response = client.embeddings.create(model=model, input=text)
    return list(response.data[0].embedding)


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--embed-a",
        default=settings.embed_base_url.rstrip("/"),
        help="First OpenAI-compatible embed base URL",
    )
    parser.add_argument(
        "--embed-b",
        default=settings.embed_base_url.rstrip("/"),
        help="Second embed base URL (defaults to --embed-a)",
    )
    parser.add_argument(
        "--model",
        default=settings.embed_model,
        help="Embedding model name",
    )
    args = parser.parse_args()
    url_a = args.embed_a.rstrip("/")
    url_b = args.embed_b.rstrip("/")
    model = args.model
    client_a = OpenAI(base_url=url_a + "/", api_key=settings.embed_api_key)
    client_b = OpenAI(base_url=url_b + "/", api_key=settings.embed_api_key)

    scores: list[float] = []
    for index, text in enumerate(DEFAULT_TEXTS, start=1):
        va = embed(client_a, model, text)
        vb = embed(client_b, model, text)
        if len(va) != len(vb):
            print(f"error: dimension mismatch on text {index}", file=sys.stderr)
            return 1
        scores.append(cosine(va, vb))

    minimum = min(scores)
    average = sum(scores) / len(scores)
    print(f"Texts compared: {len(scores)}")
    print(f"Min cosine similarity: {minimum:.6f}")
    print(f"Mean cosine similarity: {average:.6f}")
    for index, score in enumerate(scores, start=1):
        print(f"  {index:2d}: {score:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

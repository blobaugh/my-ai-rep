"""Vector store interface and NumPy file-backed implementation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

VECTORS_FILENAME = "vectors.npy"
INDEX_FILENAME = "index.json"


@dataclass
class VectorRecord:
    """One chunk vector plus metadata stored alongside it."""

    id: str
    vector: Sequence[float]
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    """A search result: chunk id, score, metadata, content hash."""

    id: str
    score: float
    content_hash: str
    metadata: dict[str, Any]


@dataclass
class IndexMeta:
    """Index-level settings that must match across incremental updates."""

    embed_model: str
    dimension: int
    query_prefix: str
    doc_prefix: str
    created_at: str
    max_chars: int = 0
    qa_embed_mode: str = ""
    qa_vector_mode: str = ""
    q_vector_prefix: str = ""


@runtime_checkable
class VectorStore(Protocol):
    """Backend-agnostic vector store used by indexing and retrieval."""

    @property
    def meta(self) -> IndexMeta: ...

    def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    def remove(self, ids: Sequence[str]) -> None: ...

    def search(
        self,
        query_vec: Sequence[float],
        k: int,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]: ...

    def save(self, directory: Path) -> None: ...

    def get(self, chunk_id: str) -> VectorRecord | None: ...

    def ids(self) -> list[str]: ...

    def content_hashes(self) -> dict[str, str]: ...


def normalize_vector(vec: np.ndarray) -> np.ndarray:
    """Return a float32 unit-length vector (zero vector stays zero)."""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return arr
    return arr / norm


class NumpyVectorStore:
    """In-memory float32 matrix with JSON sidecar metadata on disk."""

    def __init__(self, meta: IndexMeta) -> None:
        self._meta = meta
        self._ids: list[str] = []
        self._hashes: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._vectors = np.zeros((0, meta.dimension), dtype=np.float32)
        self._id_to_row: dict[str, int] = {}

    @property
    def meta(self) -> IndexMeta:
        return self._meta

    def ids(self) -> list[str]:
        return list(self._ids)

    def content_hashes(self) -> dict[str, str]:
        return dict(zip(self._ids, self._hashes))

    def get(self, chunk_id: str) -> VectorRecord | None:
        row = self._id_to_row.get(chunk_id)
        if row is None:
            return None
        return VectorRecord(
            id=chunk_id,
            vector=self._vectors[row].tolist(),
            content_hash=self._hashes[row],
            metadata=dict(self._metadata[row]),
        )

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        for record in records:
            vec = normalize_vector(np.asarray(record.vector, dtype=np.float32))
            if vec.shape[0] != self._meta.dimension:
                raise ValueError(
                    f"vector dim {vec.shape[0]} != index dim {self._meta.dimension}"
                )
            row = self._id_to_row.get(record.id)
            if row is None:
                self._id_to_row[record.id] = len(self._ids)
                self._ids.append(record.id)
                self._hashes.append(record.content_hash)
                self._metadata.append(dict(record.metadata))
                if self._vectors.shape[0] == 0:
                    self._vectors = vec.reshape(1, -1)
                else:
                    self._vectors = np.vstack([self._vectors, vec.reshape(1, -1)])
            else:
                self._vectors[row] = vec
                self._hashes[row] = record.content_hash
                self._metadata[row] = dict(record.metadata)

    def remove(self, ids: Sequence[str]) -> None:
        drop = {i for i in ids if i in self._id_to_row}
        if not drop:
            return
        keep = [i for i, cid in enumerate(self._ids) if cid not in drop]
        self._ids = [self._ids[i] for i in keep]
        self._hashes = [self._hashes[i] for i in keep]
        self._metadata = [self._metadata[i] for i in keep]
        self._vectors = (
            self._vectors[keep]
            if keep
            else np.zeros((0, self._meta.dimension), dtype=np.float32)
        )
        self._id_to_row = {cid: i for i, cid in enumerate(self._ids)}

    def search(
        self,
        query_vec: Sequence[float],
        k: int,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        if k <= 0 or self._vectors.shape[0] == 0:
            return []
        q = normalize_vector(np.asarray(query_vec, dtype=np.float32))
        if q.shape[0] != self._meta.dimension:
            raise ValueError(
                f"query dim {q.shape[0]} != index dim {self._meta.dimension}"
            )
        mask = self._filter_mask(filters)
        if not np.any(mask):
            return []
        scores = self._vectors @ q
        # Mask non-matching rows to -inf so they sort last.
        masked = np.where(mask, scores, np.float32("-inf"))
        top_n = min(k, int(np.sum(mask)))
        # argpartition then sort the top slice for stable ordering by score desc
        candidate_idx = np.argpartition(masked, -top_n)[-top_n:]
        candidate_idx = candidate_idx[np.argsort(masked[candidate_idx])[::-1]]
        hits: list[SearchHit] = []
        for idx in candidate_idx:
            score = float(masked[idx])
            if not np.isfinite(score):
                continue
            hits.append(
                SearchHit(
                    id=self._ids[int(idx)],
                    score=score,
                    content_hash=self._hashes[int(idx)],
                    metadata=dict(self._metadata[int(idx)]),
                )
            )
        return hits

    def _filter_mask(self, filters: Mapping[str, Any] | None) -> np.ndarray:
        mask = np.ones(len(self._ids), dtype=bool)
        if not filters:
            return mask
        source_type = filters.get("source_type")
        source_types = filters.get("source_types")
        min_published = filters.get("min_published_at") or filters.get("published_at")
        allowed: set[str] | None = None
        if source_types is not None:
            allowed = {str(s) for s in source_types}
        elif source_type is not None:
            if isinstance(source_type, (set, frozenset, list, tuple)):
                allowed = {str(s) for s in source_type}
            else:
                allowed = {str(source_type)}
        for i, meta in enumerate(self._metadata):
            if allowed is not None and str(meta.get("source_type", "")) not in allowed:
                mask[i] = False
                continue
            if min_published is not None:
                published = meta.get("published_at") or ""
                if published < str(min_published):
                    mask[i] = False
        return mask

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / VECTORS_FILENAME, self._vectors)
        payload = {
            "embed_model": self._meta.embed_model,
            "dimension": self._meta.dimension,
            "query_prefix": self._meta.query_prefix,
            "doc_prefix": self._meta.doc_prefix,
            "created_at": self._meta.created_at,
            "max_chars": self._meta.max_chars,
            "qa_embed_mode": self._meta.qa_embed_mode,
            "qa_vector_mode": self._meta.qa_vector_mode,
            "q_vector_prefix": self._meta.q_vector_prefix,
            "ids": self._ids,
            "content_hashes": self._hashes,
            "metadata": self._metadata,
        }
        (directory / INDEX_FILENAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> NumpyVectorStore:
        index_path = directory / INDEX_FILENAME
        vectors_path = directory / VECTORS_FILENAME
        if not index_path.is_file() or not vectors_path.is_file():
            raise FileNotFoundError(f"No vector index in {directory}")
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        meta = IndexMeta(
            embed_model=payload["embed_model"],
            dimension=int(payload["dimension"]),
            query_prefix=payload.get("query_prefix", ""),
            doc_prefix=payload.get("doc_prefix", ""),
            created_at=payload.get("created_at", ""),
            max_chars=int(payload.get("max_chars", 0)),
            qa_embed_mode=str(payload.get("qa_embed_mode", "")),
            qa_vector_mode=str(payload.get("qa_vector_mode", "")),
            q_vector_prefix=str(payload.get("q_vector_prefix", "")),
        )
        store = cls(meta)
        store._ids = list(payload["ids"])
        store._hashes = list(payload["content_hashes"])
        store._metadata = [dict(m) for m in payload["metadata"]]
        store._vectors = np.load(vectors_path).astype(np.float32)
        if store._vectors.ndim == 1 and store._vectors.size == 0:
            store._vectors = np.zeros((0, meta.dimension), dtype=np.float32)
        store._id_to_row = {cid: i for i, cid in enumerate(store._ids)}
        if store._vectors.shape[0] != len(store._ids):
            raise ValueError("vectors.npy row count does not match index.json ids")
        if store._vectors.shape[0] and store._vectors.shape[1] != meta.dimension:
            raise ValueError("vectors.npy dimension does not match index.json")
        return store


def new_index_meta(
    *,
    embed_model: str,
    dimension: int,
    query_prefix: str = "",
    doc_prefix: str = "",
    max_chars: int = 0,
    qa_embed_mode: str = "",
    qa_vector_mode: str = "",
    q_vector_prefix: str = "",
) -> IndexMeta:
    """Create IndexMeta with UTC creation timestamp."""
    return IndexMeta(
        embed_model=embed_model,
        dimension=dimension,
        query_prefix=query_prefix,
        doc_prefix=doc_prefix,
        created_at=datetime.now(timezone.utc).isoformat(),
        max_chars=max_chars,
        qa_embed_mode=qa_embed_mode,
        qa_vector_mode=qa_vector_mode,
        q_vector_prefix=q_vector_prefix,
    )

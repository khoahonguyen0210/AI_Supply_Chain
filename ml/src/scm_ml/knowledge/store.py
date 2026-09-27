from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from scm_common.domain import PolicyDocument

from .chunking import Chunk, chunk_document
from .embedding import Embedder, Matrix


def content_sha256(document: PolicyDocument) -> str:
    return hashlib.sha256(document.content.encode()).hexdigest()


@dataclass
class KnowledgeStore:
    embedding_dim: int
    _documents: dict[tuple[str, str], PolicyDocument] = field(default_factory=dict)
    _hashes: dict[tuple[str, str], str] = field(default_factory=dict)
    _chunks: list[Chunk] = field(default_factory=list)
    _vectors: list[Matrix] = field(default_factory=list)

    @property
    def documents(self) -> tuple[PolicyDocument, ...]:
        return tuple(self._documents.values())

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return tuple(self._chunks)

    @property
    def vectors(self) -> Matrix:
        if not self._vectors:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        return np.vstack(self._vectors)

    def document(self, document_id: str, version: str) -> PolicyDocument:
        return self._documents[(document_id, version)]

    def has_current(self, document: PolicyDocument) -> bool:
        key = (document.document_id, document.version)
        return self._hashes.get(key) == content_sha256(document)

    def put(self, document: PolicyDocument, chunks: tuple[Chunk, ...], vectors: Matrix) -> None:
        if vectors.shape != (len(chunks), self.embedding_dim):
            raise ValueError(
                f"expected embeddings of shape {(len(chunks), self.embedding_dim)}, "
                f"got {vectors.shape}"
            )
        key = (document.document_id, document.version)
        keep = [i for i, c in enumerate(self._chunks) if (c.document_id, c.document_version) != key]
        self._chunks = [self._chunks[i] for i in keep]
        self._vectors = [self._vectors[i] for i in keep]
        self._documents[key] = document
        self._hashes[key] = content_sha256(document)
        self._chunks.extend(chunks)
        self._vectors.extend(vectors[i : i + 1] for i in range(len(chunks)))


@dataclass(frozen=True)
class IngestReport:
    ingested: int
    skipped_unchanged: int
    chunks_written: int


def ingest(
    documents: Iterable[PolicyDocument], embedder: Embedder, store: KnowledgeStore
) -> IngestReport:
    if embedder.dim != store.embedding_dim:
        raise ValueError(f"embedder dim {embedder.dim} != store dim {store.embedding_dim}")
    ingested = skipped = written = 0
    for document in documents:
        if store.has_current(document):
            skipped += 1
            continue
        chunks = chunk_document(document)
        vectors = embedder.embed_documents([c.content for c in chunks])
        store.put(document, chunks, vectors)
        ingested += 1
        written += len(chunks)
    return IngestReport(ingested, skipped, written)

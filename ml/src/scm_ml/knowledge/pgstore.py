"""PostgreSQL/pgvector persistence of the knowledge base (`knowledge_document`, `knowledge_chunk`).

The in-memory `KnowledgeStore` is what retrieval reads; this module makes PostgreSQL the system of
record behind it. `sync` writes a corpus idempotently (an unchanged document version is skipped, so
embeddings are computed once and reused across restarts), `load` rebuilds the in-memory store from
the tables, and `search` runs the vector query in the database with the permission and validity
filters applied in SQL, so a chunk a role may not read or that is no longer in force never leaves
the database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from scm_common.domain import DocumentType, PolicyDocument

from .chunking import Chunk, chunk_document
from .embedding import EMBEDDING_DIM, Embedder, Matrix
from .store import IngestReport, KnowledgeStore, content_sha256


def _as_array(value: Any) -> Matrix:
    """The embedding column as float32, whether the driver gives a pgvector `Vector` or an array."""
    converted = value.to_numpy() if hasattr(value, "to_numpy") else value
    return np.asarray(converted, dtype=np.float32)


_CONTEXT_KEY = "context"
"""Chunk context is not a column; it is kept in the chunk's metadata and restored on load."""


@dataclass(frozen=True)
class VectorHit:
    chunk: Chunk
    score: float
    """Cosine similarity, 1.0 for identical direction."""


class PgKnowledgeStore:
    def __init__(self, conninfo: str, embedding_dim: int = EMBEDDING_DIM) -> None:
        self._conninfo = conninfo
        self.embedding_dim = embedding_dim

    def _connect(self) -> psycopg.Connection[Any]:
        connection = psycopg.connect(self._conninfo)
        register_vector(connection)
        return connection

    def sync(self, documents: Iterable[PolicyDocument], embedder: Embedder) -> IngestReport:
        """Write the documents: skip unchanged versions (same hash), rewrite changed ones."""
        if embedder.dim != self.embedding_dim:
            raise ValueError(f"embedder dim {embedder.dim} != store dim {self.embedding_dim}")
        ingested = skipped = written = 0
        with self._connect() as connection:
            known = {
                (row[0], row[1]): row[2]
                for row in connection.execute(
                    "SELECT document_id, version, content_sha256 FROM knowledge_document"
                )
            }
            for document in documents:
                key = (document.document_id, document.version)
                if known.get(key) == content_sha256(document):
                    skipped += 1
                    continue
                chunks = chunk_document(document)
                vectors = embedder.embed_documents([c.content for c in chunks])
                if vectors.shape != (len(chunks), self.embedding_dim):
                    raise ValueError(f"unexpected embedding shape {vectors.shape}")
                self._write(connection, document, chunks, vectors)
                ingested += 1
                written += len(chunks)
            connection.commit()
        return IngestReport(ingested, skipped, written)

    @staticmethod
    def _write(
        connection: psycopg.Connection[Any],
        document: PolicyDocument,
        chunks: tuple[Chunk, ...],
        vectors: Matrix,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_document (document_id, version, doc_type, title, effective_date,
                expiry_date, supplier_id, allowed_roles, content, content_sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, version) DO UPDATE SET doc_type = EXCLUDED.doc_type,
                title = EXCLUDED.title, effective_date = EXCLUDED.effective_date,
                expiry_date = EXCLUDED.expiry_date, supplier_id = EXCLUDED.supplier_id,
                allowed_roles = EXCLUDED.allowed_roles, content = EXCLUDED.content,
                content_sha256 = EXCLUDED.content_sha256, ingested_at = now()
            """,
            (
                document.document_id,
                document.version,
                document.doc_type.value,
                document.title,
                document.effective_date,
                document.expiry_date,
                document.supplier_id,
                list(document.allowed_roles),
                document.content,
                content_sha256(document),
            ),
        )
        connection.execute(
            "DELETE FROM knowledge_chunk WHERE document_id = %s AND document_version = %s",
            (document.document_id, document.version),
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            connection.execute(
                """
                INSERT INTO knowledge_chunk (document_id, document_version, chunk_index, content,
                    token_count, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    chunk.document_id,
                    chunk.document_version,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.token_count,
                    np.asarray(vector, dtype=np.float32),
                    Jsonb({**chunk.metadata, _CONTEXT_KEY: chunk.context}),
                ),
            )

    def load(self) -> KnowledgeStore:
        """Rebuild the in-memory store retrieval reads from what the tables hold."""
        store = KnowledgeStore(self.embedding_dim)
        with self._connect() as connection:
            documents = {
                (row[0], row[1]): PolicyDocument(
                    document_id=row[0],
                    version=row[1],
                    doc_type=DocumentType(row[2]),
                    title=row[3],
                    effective_date=row[4],
                    expiry_date=row[5],
                    supplier_id=row[6],
                    allowed_roles=tuple(row[7]),
                    content=row[8],
                )
                for row in connection.execute(
                    """
                    SELECT document_id, version, doc_type, title, effective_date, expiry_date,
                           supplier_id, allowed_roles, content
                    FROM knowledge_document ORDER BY document_id, version
                    """
                )
            }
            rows = connection.execute(
                """
                SELECT document_id, document_version, chunk_index, content, token_count, embedding,
                       metadata
                FROM knowledge_chunk ORDER BY chunk_id
                """
            ).fetchall()
        # Chunk ids grow in the order documents were written, so ordering by them restores the order
        # the in-memory store had; retrieval breaks score ties by that order.
        by_document: dict[tuple[str, str], list[tuple[Chunk, Matrix]]] = {}
        for row in rows:
            metadata = dict(row[6])
            context = str(metadata.pop(_CONTEXT_KEY, ""))
            chunk = Chunk(
                document_id=row[0],
                document_version=row[1],
                chunk_index=row[2],
                content=row[3],
                context=context,
                token_count=row[4],
                metadata=metadata,
            )
            by_document.setdefault((row[0], row[1]), []).append((chunk, _as_array(row[5])))
        for key, pairs in by_document.items():
            document = documents[key]
            store.put(
                document,
                tuple(c for c, _ in pairs),
                np.vstack([v for _, v in pairs]).astype(np.float32),
            )
        return store

    def search(self, query: Matrix, *, role: str, as_of: date, k: int = 5) -> list[VectorHit]:
        """The k nearest chunks the role may read and that are in force on `as_of`, by cosine."""
        vector = np.asarray(query, dtype=np.float32).reshape(-1)
        if vector.shape[0] != self.embedding_dim:
            raise ValueError(f"expected a {self.embedding_dim}-dim query, got {vector.shape[0]}")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.document_id, c.document_version, c.chunk_index, c.content, c.token_count,
                       c.metadata, 1 - (c.embedding <=> %(q)s) AS score
                FROM knowledge_chunk c
                JOIN knowledge_document d
                  ON d.document_id = c.document_id AND d.version = c.document_version
                WHERE %(role)s = ANY (d.allowed_roles)
                  AND d.effective_date <= %(as_of)s
                  AND (d.expiry_date IS NULL OR d.expiry_date >= %(as_of)s)
                ORDER BY c.embedding <=> %(q)s
                LIMIT %(k)s
                """,
                {"q": vector, "role": role, "as_of": as_of, "k": k},
            ).fetchall()
        hits: list[VectorHit] = []
        for row in rows:
            metadata = dict(row[5])
            context = str(metadata.pop(_CONTEXT_KEY, ""))
            chunk = Chunk(
                document_id=row[0],
                document_version=row[1],
                chunk_index=row[2],
                content=row[3],
                context=context,
                token_count=row[4],
                metadata=metadata,
            )
            hits.append(VectorHit(chunk, float(row[6])))
        return hits

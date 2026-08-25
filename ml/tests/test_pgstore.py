"""RAG <-> vector store: the knowledge base round-trips through real PostgreSQL with pgvector."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from scm_common.domain import PolicyDocument
from scm_ml.knowledge import (
    EMBEDDING_DIM,
    HashingEmbedder,
    KnowledgeStore,
    Retriever,
    build_corpus,
    ingest,
)
from scm_ml.knowledge.chunking import Chunk
from scm_ml.knowledge.corpus import ADMIN, FINANCE, PLANNER
from scm_ml.knowledge.pgstore import PgKnowledgeStore
from scm_ml.service.engine import build_engine
from scm_ml.service.engine_contracts import ActorRef, DocumentQuestionRequest
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticWorld

try:
    from testcontainers.postgres import PostgresContainer

    HAVE_TESTCONTAINERS = True
except ImportError:  # pragma: no cover
    HAVE_TESTCONTAINERS = False

pytestmark = pytest.mark.integration

MIGRATIONS = Path("backend/src/main/resources/db/migration")
AS_OF = date(2024, 12, 30)


def _docker_available() -> bool:
    if not HAVE_TESTCONTAINERS:
        return False
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def conninfo() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker is not available")
    container = PostgresContainer(
        "pgvector/pgvector:pg16", username="scm", password="scm", dbname="scm", driver=None
    )
    with container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
        url = f"host={host} port={port} user=scm password=scm dbname=scm"
        import psycopg

        with psycopg.connect(url, autocommit=True) as connection:
            for migration in sorted(MIGRATIONS.glob("V*.sql"), key=lambda p: _version(p.name)):
                connection.execute(migration.read_text(encoding="utf-8"))
        yield url


def _version(name: str) -> int:
    match = re.match(r"V(\d+)__", name)
    assert match, name
    return int(match.group(1))


@pytest.fixture(scope="module")
def documents(small_world: SyntheticWorld) -> tuple[PolicyDocument, ...]:
    return build_corpus(small_world).documents


@pytest.fixture
def clean_database(conninfo: str, small_world: SyntheticWorld) -> str:
    import psycopg

    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute("TRUNCATE region, supplier, knowledge_document CASCADE")
        connection.execute("INSERT INTO region VALUES ('R1', 'North')")
        for supplier in small_world.suppliers:
            connection.execute(
                "INSERT INTO supplier (supplier_id, name, region_id, reliability, quality_score) "
                "VALUES (%s, %s, 'R1', 0.9, 0.9)",
                (supplier.supplier_id, supplier.name),
            )
    return conninfo


def _count(conninfo: str, table: str) -> int:
    import psycopg

    with psycopg.connect(conninfo) as connection:
        row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        return int(row[0])


def test_the_corpus_is_written_once_and_unchanged_documents_are_skipped(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    pg = PgKnowledgeStore(clean_database)
    embedder = HashingEmbedder()

    first = pg.sync(documents, embedder)
    assert first.ingested == len(documents) and first.skipped_unchanged == 0
    assert _count(clean_database, "knowledge_document") == len(documents)
    assert _count(clean_database, "knowledge_chunk") == first.chunks_written

    second = pg.sync(documents, embedder)
    assert second.ingested == 0 and second.skipped_unchanged == len(documents)
    assert _count(clean_database, "knowledge_chunk") == first.chunks_written


def test_a_changed_document_replaces_only_its_own_chunks(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    pg = PgKnowledgeStore(clean_database)
    embedder = HashingEmbedder()
    pg.sync(documents, embedder)
    before = _count(clean_database, "knowledge_chunk")

    edited = documents[0].model_copy(
        update={"content": documents[0].content + "\n99. A brand new clause appears here."}
    )
    report = pg.sync([edited, *documents[1:]], embedder)

    assert report.ingested == 1 and report.skipped_unchanged == len(documents) - 1
    assert _count(clean_database, "knowledge_chunk") >= before
    stored = pg.load()
    assert "brand new clause" in stored.document(edited.document_id, edited.version).content


def test_loading_restores_documents_chunks_and_vectors_exactly(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    embedder = HashingEmbedder()
    memory = KnowledgeStore(EMBEDDING_DIM)
    ingest(documents, embedder, memory)
    pg = PgKnowledgeStore(clean_database)
    pg.sync(documents, embedder)

    loaded = pg.load()

    def key(chunk: Chunk) -> tuple[str, str, int]:
        return (chunk.document_id, chunk.document_version, chunk.chunk_index)

    assert {(d.document_id, d.version) for d in loaded.documents} == {
        (d.document_id, d.version) for d in memory.documents
    }
    original = {key(c): (c, v) for c, v in zip(memory.chunks, memory.vectors, strict=True)}
    restored = {key(c): (c, v) for c, v in zip(loaded.chunks, loaded.vectors, strict=True)}
    assert original.keys() == restored.keys()
    for chunk_key, (chunk, vector) in original.items():
        other, other_vector = restored[chunk_key]
        assert other == chunk  # content, context, token count and metadata survive
        assert np.allclose(vector, other_vector, atol=1e-6)


def test_retrieval_over_the_loaded_store_matches_retrieval_over_memory(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    embedder = HashingEmbedder()
    memory = KnowledgeStore(EMBEDDING_DIM)
    ingest(documents, embedder, memory)
    pg = PgKnowledgeStore(clean_database)
    pg.sync(documents, embedder)
    in_memory, from_database = Retriever(memory, embedder), Retriever(pg.load(), embedder)

    for question in [
        "Who must approve a purchase order above USD 20,000?",
        "What are the payment terms for the first supplier?",
        "How long may a delivery be late before a penalty applies?",
    ]:
        a = in_memory.retrieve(question, role=PLANNER, as_of=AS_OF)
        b = from_database.retrieve(question, role=PLANNER, as_of=AS_OF)
        assert [(h.chunk.document_id, h.chunk.chunk_index) for h in a.hits] == [
            (h.chunk.document_id, h.chunk.chunk_index) for h in b.hits
        ]


def test_the_database_search_applies_permissions_and_validity_in_sql(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    embedder = HashingEmbedder()
    pg = PgKnowledgeStore(clean_database)
    pg.sync(documents, embedder)
    query = embedder.embed_query("What is the contract payment term and the maximum order value?")

    planner_docs = {h.chunk.document_id for h in pg.search(query, role=PLANNER, as_of=AS_OF, k=200)}
    finance_docs = {h.chunk.document_id for h in pg.search(query, role=FINANCE, as_of=AS_OF, k=200)}
    by_id = {d.document_id: d for d in documents}

    assert planner_docs and all(PLANNER in by_id[i].allowed_roles for i in planner_docs)
    assert all(FINANCE in by_id[i].allowed_roles for i in finance_docs)
    restricted = {d.document_id for d in documents if PLANNER not in d.allowed_roles}
    assert restricted and not (planner_docs & restricted)  # a role never receives unreadable chunks
    assert pg.search(query, role="intern", as_of=AS_OF, k=50) == []

    # stale documents are filtered by date: far in the future every expired version is gone
    expired = {d.document_id: d for d in documents if d.expiry_date is not None}
    future = date(2100, 1, 1)
    in_force = {
        (h.chunk.document_id, h.chunk.document_version)
        for h in pg.search(query, role=ADMIN, as_of=future, k=500)
    }
    assert not any(
        (d.document_id, d.version) in in_force for d in expired.values() if d.expiry_date
    )


def test_the_database_ranks_like_cosine_over_the_stored_vectors(
    clean_database: str, documents: tuple[PolicyDocument, ...]
) -> None:
    embedder = HashingEmbedder()
    memory = KnowledgeStore(EMBEDDING_DIM)
    ingest(documents, embedder, memory)
    pg = PgKnowledgeStore(clean_database)
    pg.sync(documents, embedder)
    query = embedder.embed_query("Who must approve a purchase order above USD 20,000?")

    hits = pg.search(query, role=ADMIN, as_of=AS_OF, k=3)

    readable = [
        i
        for i, chunk in enumerate(memory.chunks)
        if ADMIN in memory.document(chunk.document_id, chunk.document_version).allowed_roles
        and memory.document(chunk.document_id, chunk.document_version).is_effective_on(AS_OF)
    ]
    matrix = memory.vectors[readable]
    q = np.asarray(query, dtype=np.float32).reshape(-1)
    cosine = (matrix @ q) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q))
    best = readable[int(np.argmax(cosine))]
    assert hits[0].chunk.content == memory.chunks[best].content
    assert hits[0].score == pytest.approx(float(cosine.max()), abs=1e-4)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_the_engine_can_answer_from_the_database_backed_knowledge_base(
    clean_database: str, small_world: SyntheticWorld, small_service: ForecastService
) -> None:
    engine = build_engine(small_world, small_service, knowledge_url=clean_database)
    assert _count(clean_database, "knowledge_chunk") > 0  # the corpus was synced to PostgreSQL

    answer = engine.ask_documents(
        DocumentQuestionRequest(
            actor=ActorRef(user_id="pat", role=PLANNER),
            question="Who must approve a purchase order above USD 20,000?",
        )
    )

    assert answer["status"] == "ANSWERED" and answer["citations"]
    # a second engine start reuses the stored embeddings instead of embedding again
    again = PgKnowledgeStore(clean_database).sync(
        build_corpus(small_world).documents, HashingEmbedder()
    )
    assert again.ingested == 0


def test_a_wrong_embedding_dimension_is_rejected(clean_database: str) -> None:
    pg = PgKnowledgeStore(clean_database)
    with pytest.raises(ValueError, match="expected a 384-dim query"):
        pg.search(np.zeros(10, dtype=np.float32), role=PLANNER, as_of=AS_OF)
    with pytest.raises(ValueError, match="embedder dim"):
        PgKnowledgeStore(clean_database, embedding_dim=64).sync([], HashingEmbedder())

from datetime import date

import numpy as np
import pytest

from scm_common.domain import DocumentType, PolicyDocument
from scm_ml.knowledge import (
    EMBEDDING_DIM,
    Corpus,
    HashingEmbedder,
    KnowledgeStore,
    build_corpus,
    chunk_document,
    ingest,
    parse_document,
)
from scm_ml.synthetic import generate_world


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return build_corpus(generate_world())


def _doc(content: str, document_id: str = "D-1") -> PolicyDocument:
    return PolicyDocument(
        document_id=document_id,
        doc_type=DocumentType.POLICY,
        title="Test policy",
        version="1",
        effective_date=date(2024, 1, 1),
        allowed_roles=("planner",),
        content=content,
    )


def test_parse_splits_numbered_clauses() -> None:
    parsed = parse_document(_doc("Intro line.\n1. First rule.\n2. Second rule\ncontinues here."))
    assert parsed.preamble == "Intro line."
    assert parsed.clauses == ("1. First rule.", "2. Second rule continues here.")


def test_parse_splits_inline_clauses_of_single_paragraph_sops(corpus: Corpus) -> None:
    sop = corpus.get("SOP-STOCKOUT", "1")
    parsed = parse_document(sop)
    assert parsed.preamble == "Stockout response."
    assert len(parsed.clauses) == 3
    assert parsed.clauses[0].startswith("1. Planners escalate")


def test_parse_keeps_unnumbered_text_as_one_clause() -> None:
    parsed = parse_document(_doc("Just a sentence with no numbered clauses."))
    assert parsed.clauses == ("Just a sentence with no numbered clauses.",)


def test_chunks_carry_context_and_metadata(corpus: Corpus) -> None:
    contract = next(d for d in corpus.documents if d.document_id.startswith("CTR-"))
    chunks = chunk_document(contract)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    payment = next(c for c in chunks if "payable within" in c.content)
    assert contract.title in payment.content
    assert contract.supplier_id and contract.supplier_id in payment.content
    assert payment.metadata["doc_type"] == "CONTRACT"
    assert payment.metadata["supplier_id"] == contract.supplier_id
    assert payment.metadata["allowed_roles"] == list(contract.allowed_roles)
    assert contract.expiry_date is not None
    assert payment.metadata["expiry_date"] == contract.expiry_date.isoformat()


def test_long_clause_is_windowed_with_overlap() -> None:
    words = [f"w{i}" for i in range(300)]
    chunks = chunk_document(_doc("1. " + " ".join(words)), max_tokens=60, overlap=10)
    assert len(chunks) > 3
    assert all(c.token_count <= 60 + 2 for c in chunks)
    first, second = chunks[0].content.split(), chunks[1].content.split()
    assert set(first[-10:]) & set(second)
    covered = {w for c in chunks for w in c.content.split()}
    assert set(words) <= covered


def test_every_corpus_document_is_chunked_within_budget(corpus: Corpus) -> None:
    for document in corpus.documents:
        chunks = chunk_document(document)
        assert chunks, document.document_id
        assert all(c.token_count <= 125 for c in chunks)


def test_hashing_embedder_is_deterministic_unit_norm_and_lexical() -> None:
    embedder = HashingEmbedder()
    texts = ["payment terms are 30 days", "payment terms are 45 days", "cold chain storage"]
    a, b = embedder.embed_documents(texts), embedder.embed_documents(texts)
    assert a.shape == (3, EMBEDDING_DIM)
    assert np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert float(a[0] @ a[1]) > float(a[0] @ a[2])
    assert embedder.embed_query(texts[0]).shape == (1, EMBEDDING_DIM)


def test_ingest_populates_store_and_is_idempotent(corpus: Corpus) -> None:
    store, embedder = KnowledgeStore(EMBEDDING_DIM), HashingEmbedder()
    first = ingest(corpus.documents, embedder, store)
    assert first.ingested == len(corpus.documents) and first.skipped_unchanged == 0
    assert first.chunks_written == len(store.chunks) == store.vectors.shape[0]
    again = ingest(corpus.documents, embedder, store)
    assert again.ingested == 0 and again.skipped_unchanged == len(corpus.documents)
    assert len(store.chunks) == first.chunks_written


def test_changed_document_replaces_its_chunks() -> None:
    store, embedder = KnowledgeStore(EMBEDDING_DIM), HashingEmbedder()
    other = _doc("1. Unrelated rule.", "D-2")
    ingest([_doc("1. Old rule."), other], embedder, store)
    report = ingest([_doc("1. New rule about pallets."), other], embedder, store)
    assert (report.ingested, report.skipped_unchanged) == (1, 1)
    contents = [c.content for c in store.chunks if c.document_id == "D-1"]
    assert len(contents) == 1 and "pallets" in contents[0]
    assert len(store.chunks) == store.vectors.shape[0] == 2


def test_store_rejects_wrong_embedding_shape() -> None:
    store = KnowledgeStore(EMBEDDING_DIM)
    document = _doc("1. Rule.")
    with pytest.raises(ValueError, match="shape"):
        store.put(document, chunk_document(document), np.zeros((1, 8), dtype=np.float32))


def test_ingest_rejects_mismatched_embedder_dim() -> None:
    with pytest.raises(ValueError, match="dim"):
        ingest([_doc("1. Rule.")], HashingEmbedder(), KnowledgeStore(128))

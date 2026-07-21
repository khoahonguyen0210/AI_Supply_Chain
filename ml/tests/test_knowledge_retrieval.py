import pytest

from scm_ml.knowledge import (
    EMBEDDING_DIM,
    FINANCE,
    PLANNER,
    Corpus,
    Expectation,
    HashingEmbedder,
    KnowledgeStore,
    Retriever,
    ValidityStatus,
    build_corpus,
    ingest,
)
from scm_ml.knowledge.retrieval import Bm25Index
from scm_ml.synthetic import generate_world


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return build_corpus(generate_world())


@pytest.fixture(scope="module")
def retriever(corpus: Corpus) -> Retriever:
    embedder = HashingEmbedder()
    store = KnowledgeStore(EMBEDDING_DIM)
    ingest(corpus.documents, embedder, store)
    return Retriever(store, embedder)


def test_source_document_is_retrieved_for_every_answerable_fact(
    corpus: Corpus, retriever: Retriever
) -> None:
    misses = []
    for fact in corpus.facts:
        if fact.expectation == Expectation.DENY:
            continue
        result = retriever.retrieve(fact.question, role=fact.role, as_of=corpus.as_of, k=5)
        if not any(
            h.chunk.document_id == fact.document_id and h.chunk.document_version == fact.version
            for h in result.hits
        ):
            misses.append(fact.fact_id)
    assert misses == []


def test_restricted_chunks_are_never_returned_to_other_roles(
    corpus: Corpus, retriever: Retriever
) -> None:
    rebate = next(f for f in corpus.facts if f.expectation == Expectation.DENY)
    result = retriever.retrieve(rebate.question, role=PLANNER, as_of=corpus.as_of, k=20)
    assert result.hits
    assert all(PLANNER in h.chunk.metadata["allowed_roles"] for h in result.hits)
    assert not any(h.chunk.document_id == rebate.document_id for h in result.hits)
    assert result.restricted_hits > 0


def test_permitted_role_retrieves_restricted_document(corpus: Corpus, retriever: Retriever) -> None:
    fact = next(
        f for f in corpus.facts if f.expectation == Expectation.ANSWER and f.role == FINANCE
    )
    result = retriever.retrieve(fact.question, role=FINANCE, as_of=corpus.as_of, k=3)
    assert result.hits[0].chunk.document_id == fact.document_id
    assert result.restricted_hits == 0


def test_current_version_outranks_superseded_version(corpus: Corpus, retriever: Retriever) -> None:
    result = retriever.retrieve(
        "Above what order value is procurement manager approval required?",
        role=PLANNER,
        as_of=corpus.as_of,
        k=10,
    )
    approval = [h for h in result.hits if h.chunk.document_id == "POL-APPROVAL"]
    versions = [h.chunk.document_version for h in approval]
    assert versions[0] == "2" and "1" in versions
    assert approval[0].status == ValidityStatus.CURRENT
    old = next(h for h in approval if h.chunk.document_version == "1")
    assert old.status == ValidityStatus.SUPERSEDED
    assert approval[0].score > old.score


def test_expired_contract_is_retrieved_and_labelled(corpus: Corpus, retriever: Retriever) -> None:
    fact = next(f for f in corpus.facts if f.expectation == Expectation.QUALIFY_EXPIRED)
    result = retriever.retrieve(fact.question, role=fact.role, as_of=corpus.as_of, k=5)
    hit = next(h for h in result.hits if h.chunk.document_id == fact.document_id)
    assert hit.status == ValidityStatus.EXPIRED


def test_not_yet_effective_documents_are_labelled(corpus: Corpus, retriever: Retriever) -> None:
    earlier = corpus.as_of.replace(year=corpus.as_of.year - 1, month=1, day=1)
    result = retriever.retrieve("quarterly procurement budget", role=FINANCE, as_of=earlier, k=3)
    budget = next(h for h in result.hits if h.chunk.document_id == "POL-BUDGET")
    assert budget.status == ValidityStatus.NOT_YET_EFFECTIVE


def test_named_supplier_boosts_its_own_documents(retriever: Retriever, corpus: Corpus) -> None:
    result = retriever.retrieve(
        "What are the payment terms for Supplier B (SUP-002)?",
        role=PLANNER,
        as_of=corpus.as_of,
        k=3,
    )
    assert result.hits[0].chunk.metadata["supplier_id"] == "SUP-002"
    assert all(h.chunk.metadata["supplier_id"] in ("SUP-002", None) for h in result.hits)


def test_supplier_is_recognised_by_id_and_by_name(retriever: Retriever) -> None:
    assert retriever.mentioned_suppliers("terms of sup-003 please") == {"SUP-003"}
    assert retriever.mentioned_suppliers("what does supplier c commit to") == {"SUP-003"}
    assert retriever.mentioned_suppliers("warehouse utilisation") == frozenset()


def test_supplier_mentions_are_stripped_from_query_text(retriever: Retriever) -> None:
    query = "What are the payment terms for Supplier B (SUP-002)?"
    topic = retriever.topic(query, retriever.mentioned_suppliers(query))
    assert "SUP-002" not in topic and "Supplier B" not in topic
    assert "payment terms" in topic


def test_empty_store_returns_no_hits() -> None:
    retriever = Retriever(KnowledgeStore(EMBEDDING_DIM), HashingEmbedder())
    result = retriever.retrieve("anything", role=PLANNER, as_of=generate_world().as_of)
    assert result.hits == () and result.restricted_hits == 0


def test_bm25_prefers_rare_matching_terms() -> None:
    index = Bm25Index(["pallet strapping rules", "payment within thirty days", "payment rules"])
    scores = index.scores("thirty days payment")
    assert scores.argmax() == 1
    assert index.scores("unseen").sum() == 0

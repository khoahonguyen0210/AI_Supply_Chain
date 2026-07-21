import pytest

from scm_common.domain import ContractStatus, DocumentType
from scm_ml.knowledge import (
    ADMIN,
    FINANCE,
    PLANNER,
    Corpus,
    Expectation,
    build_corpus,
)
from scm_ml.synthetic import SyntheticWorld, generate_world


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    return generate_world()


@pytest.fixture(scope="module")
def corpus(world: SyntheticWorld) -> Corpus:
    return build_corpus(world)


def test_corpus_is_deterministic(world: SyntheticWorld, corpus: Corpus) -> None:
    again = build_corpus(world)
    assert again.documents == corpus.documents
    assert again.facts == corpus.facts


def test_every_document_type_is_present(corpus: Corpus) -> None:
    assert {d.doc_type for d in corpus.documents} == set(DocumentType)


def test_document_versions_are_unique(corpus: Corpus) -> None:
    keys = [(d.document_id, d.version) for d in corpus.documents]
    assert len(keys) == len(set(keys))


def test_fact_ids_are_unique_and_point_at_real_documents(corpus: Corpus) -> None:
    ids = [f.fact_id for f in corpus.facts]
    assert len(ids) == len(set(ids))
    for fact in corpus.facts:
        corpus.get(fact.document_id, fact.version)
        for other in fact.conflicting_document_ids:
            assert any(d.document_id == other for d in corpus.documents)


def test_expected_answers_appear_in_their_source_document(corpus: Corpus) -> None:
    for fact in corpus.facts:
        if fact.expectation == Expectation.DENY:
            continue
        document = corpus.get(fact.document_id, fact.version)
        assert fact.expected_answer.lower() in document.content.lower(), fact.fact_id


def test_forbidden_answers_are_absent_from_the_current_document(corpus: Corpus) -> None:
    for fact in corpus.facts:
        if fact.forbidden_answer is None or fact.expectation == Expectation.DENY:
            continue
        document = corpus.get(fact.document_id, fact.version)
        assert fact.forbidden_answer not in document.content, fact.fact_id


def test_superseded_versions_are_expired_and_stale(corpus: Corpus) -> None:
    approval = [d for d in corpus.documents if d.document_id == "POL-APPROVAL"]
    assert sorted(d.version for d in approval) == ["1", "2"]
    old, new = sorted(approval, key=lambda d: d.version)
    assert old.expiry_date is not None and old.expiry_date < new.effective_date
    assert not old.is_effective_on(corpus.as_of)
    assert new.is_effective_on(corpus.as_of)


def test_expired_contract_has_a_qualify_fact(world: SyntheticWorld, corpus: Corpus) -> None:
    expired = [c for c in world.contracts if c.status == ContractStatus.EXPIRED]
    assert expired
    facts = [f for f in corpus.facts if f.expectation == Expectation.QUALIFY_EXPIRED]
    assert len(facts) == len(expired)
    for fact in facts:
        assert not corpus.get(fact.document_id, fact.version).is_effective_on(corpus.as_of)


def test_suspended_supplier_has_a_notice(world: SyntheticWorld, corpus: Corpus) -> None:
    suspended = [c for c in world.contracts if c.status == ContractStatus.SUSPENDED]
    notices = {d.supplier_id for d in corpus.documents if d.document_id.startswith("NTC-")}
    assert notices == {c.supplier_id for c in suspended}


def test_conflicting_documents_are_both_current(corpus: Corpus) -> None:
    (fact,) = [f for f in corpus.facts if f.expectation == Expectation.FLAG_CONFLICT]
    documents = [corpus.get(fact.document_id, fact.version)]
    documents += [
        d
        for d in corpus.documents
        if d.document_id in fact.conflicting_document_ids and d.is_effective_on(corpus.as_of)
    ]
    assert len(documents) >= 2
    assert all(d.is_effective_on(corpus.as_of) for d in documents)


def test_restricted_documents_deny_unprivileged_roles(corpus: Corpus) -> None:
    denials = [f for f in corpus.facts if f.expectation == Expectation.DENY]
    assert denials
    for fact in denials:
        document = corpus.get(fact.document_id, fact.version)
        assert fact.role not in document.allowed_roles
        assert fact.expected_answer == ""
        assert fact.forbidden_answer is not None
        assert fact.forbidden_answer in document.content
    # the same restricted document answers a permitted role
    answered = [
        f for f in corpus.facts if f.expectation == Expectation.ANSWER and f.role == FINANCE
    ]
    assert answered
    for fact in answered:
        assert fact.role in corpus.get(fact.document_id, fact.version).allowed_roles


def test_restricted_documents_exclude_the_planner_role(corpus: Corpus) -> None:
    restricted = [d for d in corpus.documents if PLANNER not in d.allowed_roles]
    assert restricted
    assert all(set(d.allowed_roles) == {FINANCE, ADMIN} for d in restricted)


def test_contract_text_matches_master_data(world: SyntheticWorld, corpus: Corpus) -> None:
    for contract in world.contracts:
        document = corpus.get(f"CTR-{contract.supplier_id}", "1")
        assert f"within {contract.payment_terms_days} days" in document.content
        assert document.expiry_date == contract.effective_to

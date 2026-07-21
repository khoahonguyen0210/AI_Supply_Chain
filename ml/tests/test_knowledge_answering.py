from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from scm_ml.knowledge import (
    EMBEDDING_DIM,
    PLANNER,
    AnswerStatus,
    ClaudeGenerator,
    Corpus,
    Draft,
    Expectation,
    ExtractiveGenerator,
    GroundedAnswerer,
    HashingEmbedder,
    KnowledgeStore,
    Retriever,
    Source,
    build_corpus,
    ingest,
)
from scm_ml.knowledge.answering import unsupported_numbers
from scm_ml.llm import ClaudeJsonLlm, LlmError
from scm_ml.synthetic import generate_world

PAYMENT_QUESTION = "What are the payment terms for Supplier A (SUP-001)?"


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return build_corpus(generate_world())


@pytest.fixture(scope="module")
def retriever(corpus: Corpus) -> Retriever:
    embedder = HashingEmbedder()
    store = KnowledgeStore(EMBEDDING_DIM)
    ingest(corpus.documents, embedder, store)
    return Retriever(store, embedder)


@pytest.fixture(scope="module")
def answerer(retriever: Retriever) -> GroundedAnswerer:
    return GroundedAnswerer(retriever, ExtractiveGenerator())


class SpyGenerator:
    name = "spy"

    def __init__(self, draft: Draft | None = None, error: Exception | None = None) -> None:
        self.calls = 0
        self._draft, self._error = draft, error

    def generate(self, question: str, sources: Sequence[Source]) -> Draft:
        self.calls += 1
        if self._error:
            raise self._error
        assert self._draft is not None
        return self._draft


def test_answerable_fact_is_answered_with_matching_citation(
    corpus: Corpus, answerer: GroundedAnswerer
) -> None:
    fact = next(f for f in corpus.facts if f.fact_id == "FACT-004")
    answer = answerer.answer(fact.question, role=fact.role, as_of=corpus.as_of)
    assert answer.status == AnswerStatus.ANSWERED
    assert fact.expected_answer in answer.text
    assert [(c.document_id, c.version) for c in answer.citations] == [
        (fact.document_id, fact.version)
    ]


def test_stale_value_is_not_asserted_when_a_newer_version_exists(
    corpus: Corpus, answerer: GroundedAnswerer
) -> None:
    fact = next(f for f in corpus.facts if f.fact_id == "FACT-008")
    answer = answerer.answer(fact.question, role=fact.role, as_of=corpus.as_of)
    assert fact.expected_answer in answer.text
    assert fact.forbidden_answer is not None and fact.forbidden_answer not in answer.text


def test_expired_source_is_qualified(corpus: Corpus, answerer: GroundedAnswerer) -> None:
    fact = next(f for f in corpus.facts if f.expectation == Expectation.QUALIFY_EXPIRED)
    answer = answerer.answer(fact.question, role=fact.role, as_of=corpus.as_of)
    assert answer.status == AnswerStatus.QUALIFIED
    assert fact.expected_answer in answer.text
    assert any("expired" in c for c in answer.caveats)


def test_conflicting_in_force_documents_are_reported_not_resolved(
    corpus: Corpus, answerer: GroundedAnswerer
) -> None:
    fact = next(f for f in corpus.facts if f.expectation == Expectation.FLAG_CONFLICT)
    answer = answerer.answer(fact.question, role=fact.role, as_of=corpus.as_of)
    assert answer.status == AnswerStatus.CONFLICT
    assert {c.document_id for c in answer.citations} == {
        fact.document_id,
        *fact.conflicting_document_ids,
    }
    assert "12,000" in answer.text and "15,000" in answer.text


def test_general_question_is_not_flagged_as_conflict_by_a_regional_addendum(
    answerer: GroundedAnswerer, corpus: Corpus
) -> None:
    answer = answerer.answer(
        "Above what order value is procurement manager approval required?",
        role=PLANNER,
        as_of=corpus.as_of,
    )
    assert answer.status == AnswerStatus.ANSWERED
    assert "15,000" in answer.text


def test_restricted_document_is_not_disclosed(corpus: Corpus, answerer: GroundedAnswerer) -> None:
    for fact in (f for f in corpus.facts if f.expectation == Expectation.DENY):
        answer = answerer.answer(fact.question, role=fact.role, as_of=corpus.as_of)
        assert answer.status == AnswerStatus.RESTRICTED
        assert fact.forbidden_answer is not None and fact.forbidden_answer not in answer.text
        assert answer.citations == ()


def test_missing_evidence_is_refused_without_calling_the_generator(
    retriever: Retriever, corpus: Corpus
) -> None:
    spy = SpyGenerator(Draft("anything [S1]", ("S1",)))
    answer = GroundedAnswerer(retriever, spy).answer(
        "What is the dress code for warehouse staff?", role=PLANNER, as_of=corpus.as_of
    )
    assert answer.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert spy.calls == 0 and answer.citations == ()


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        (Draft("Invoices are payable within 90 days [S1]", ("S1",)), "numbers not in cited"),
        (Draft("Invoices are payable within 30 days [S9]", ("S9",)), "unknown sources"),
        (Draft("Invoices are payable within 30 days", ()), "no citations"),
        (Draft("", ("S1",)), "empty answer"),
    ],
)
def test_unsupported_drafts_are_rejected(
    retriever: Retriever, corpus: Corpus, draft: Draft, expected: str
) -> None:
    answer = GroundedAnswerer(retriever, SpyGenerator(draft)).answer(
        PAYMENT_QUESTION, role=PLANNER, as_of=corpus.as_of
    )
    assert answer.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert any(expected in v for v in answer.violations)


def test_generator_declaring_insufficient_evidence_yields_refusal(
    retriever: Retriever, corpus: Corpus
) -> None:
    answer = GroundedAnswerer(retriever, SpyGenerator(Draft("", (), sufficient=False))).answer(
        PAYMENT_QUESTION, role=PLANNER, as_of=corpus.as_of
    )
    assert answer.status == AnswerStatus.INSUFFICIENT_EVIDENCE and answer.violations == ()


def test_llm_failure_degrades_to_insufficient_evidence(
    retriever: Retriever, corpus: Corpus
) -> None:
    answer = GroundedAnswerer(retriever, SpyGenerator(error=LlmError("boom"))).answer(
        PAYMENT_QUESTION, role=PLANNER, as_of=corpus.as_of
    )
    assert answer.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "boom" in answer.violations[0]


def test_unsupported_numbers_ignores_formatting_and_citation_markers(
    retriever: Retriever, corpus: Corpus
) -> None:
    result = retriever.retrieve(
        "maximum value of a single purchase order Supplier A", role=PLANNER, as_of=corpus.as_of
    )
    source = Source("S1", result.hits[0])
    assert unsupported_numbers("The limit is USD 250,000 [S1]", [source]) == set()
    assert unsupported_numbers("The limit is USD 300,000 [S1]", [source]) == {"300000"}


class FakeLlm:
    name = "fake-llm"

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply, self.prompt = reply, ""

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]:
        self.prompt = user
        return self.reply


def test_claude_generator_sends_labelled_sources_and_parses_the_draft(
    retriever: Retriever, corpus: Corpus
) -> None:
    llm = FakeLlm(
        {
            "answer": "Invoices are payable within 30 days [S1].",
            "cited_sources": ["S1"],
            "sufficient": True,
        }
    )
    answer = GroundedAnswerer(retriever, ClaudeGenerator(llm)).answer(
        PAYMENT_QUESTION, role=PLANNER, as_of=corpus.as_of
    )
    assert answer.status == AnswerStatus.ANSWERED and answer.generator == "fake-llm"
    assert '<source id="S1" document="CTR-SUP-001"' in llm.prompt


def _response(stop_reason: str, text: str | None) -> SimpleNamespace:
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(stop_reason=stop_reason, content=content)


class FakeAnthropic:
    def __init__(self, response: SimpleNamespace | Exception) -> None:
        self.messages = SimpleNamespace(create=self._create)
        self._response = response
        self.kwargs: dict[str, Any] = {}

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _llm(response: SimpleNamespace | Exception) -> tuple[ClaudeJsonLlm, FakeAnthropic]:
    fake = FakeAnthropic(response)
    return ClaudeJsonLlm(client=fake), fake  # type: ignore[arg-type]


def test_claude_client_requests_structured_output_and_parses_json() -> None:
    llm, fake = _llm(_response("end_turn", '{"ok": true}'))
    assert llm.complete_json(system="s", user="u", schema={"type": "object"}) == {"ok": True}
    assert fake.kwargs["model"] == "claude-opus-5-5"
    assert fake.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in fake.kwargs


@pytest.mark.parametrize(
    "response",
    [
        _response("refusal", None),
        _response("max_tokens", '{"ok":'),
        _response("end_turn", None),
        _response("end_turn", "not json"),
        _response("end_turn", "[1]"),
        anthropic.APIConnectionError(request=SimpleNamespace()),  # type: ignore[arg-type]
    ],
)
def test_claude_client_failures_raise_llm_error(response: SimpleNamespace | Exception) -> None:
    llm, _ = _llm(response)
    with pytest.raises(LlmError):
        llm.complete_json(system="s", user="u", schema={"type": "object"})

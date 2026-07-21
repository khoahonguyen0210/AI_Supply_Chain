import json
from pathlib import Path
from typing import Any

import pytest

from scm_ml.knowledge import (
    EMBEDDING_DIM,
    Corpus,
    ExtractiveGenerator,
    GroundedAnswerer,
    HashingEmbedder,
    KnowledgeStore,
    Retriever,
    build_corpus,
    ingest,
)
from scm_ml.knowledge.evaluation import Category, build_eval_set, mentions, run_evaluation
from scm_ml.synthetic import generate_world


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return build_corpus(generate_world())


@pytest.fixture(scope="module")
def outcome(
    corpus: Corpus, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict[str, Any], Path]:
    embedder = HashingEmbedder()
    store = KnowledgeStore(EMBEDDING_DIM)
    ingest(corpus.documents, embedder, store)
    retriever = Retriever(store, embedder)
    out = tmp_path_factory.mktemp("rag") / "eval.json"
    result = run_evaluation(
        corpus, retriever, GroundedAnswerer(retriever, ExtractiveGenerator()), out, embedder="hash"
    )
    return result, out


def test_eval_set_covers_every_required_category(corpus: Corpus) -> None:
    cases = build_eval_set(corpus)
    assert {c.category for c in cases} == set(Category)
    assert len({c.case_id for c in cases}) == len(cases)
    missing = [c for c in cases if c.category == Category.MISSING]
    assert {c.split for c in missing} == {"calibration", "holdout"}
    assert all(not c.gold for c in missing)


def test_conflict_case_expects_both_documents(corpus: Corpus) -> None:
    case = next(c for c in build_eval_set(corpus) if c.category == Category.CONFLICT)
    assert {d for d, _ in case.gold} == {"POL-APPROVAL", "POL-APPROVAL-R3"}
    assert ("POL-APPROVAL", "2") in case.gold


def test_mentions_matches_whole_tokens_only() -> None:
    assert mentions("No new purchase orders may be placed", "No")
    assert not mentions("This is not allowed", "No")
    assert mentions("rebate of 3% applies", "3%") and not mentions("rebate of 13% applies", "3%")


def test_no_unsafe_outcome_on_the_fixed_set(outcome: tuple[dict[str, Any], Path]) -> None:
    result, _ = outcome
    answers = result["answers"]
    assert answers["wrong_answer_rate"] == 0
    assert answers["restricted_leaks"] == 0
    assert answers["groundedness"] == 1
    assert answers["missing_evidence_refusal"]["holdout"] == 1
    assert result["retrieval"]["hit@5"] == 1


def test_known_failure_is_reported_not_hidden(outcome: tuple[dict[str, Any], Path]) -> None:
    result, _ = outcome
    assert [f["case_id"] for f in result["failures"]] == ["FACT-033"]


def test_artifact_records_configuration_and_unmeasured_llm(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, out = outcome
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["embedder"] == "hash" and saved["generator"] == "extractive-stub"
    assert saved["llm_generator_metrics"] == "NOT YET MEASURED"
    assert {"created_at", "code_revision"} <= set(saved["provenance"])
    assert saved["cases"] == len(result["results"])

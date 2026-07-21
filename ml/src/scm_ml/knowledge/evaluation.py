"""Fixed RAG evaluation set and metrics.

The set is the corpus ground truth (normal, superseded-value, expired, conflicting and
permission-restricted questions) plus questions the corpus cannot answer. Missing-evidence
questions are split into a `calibration` batch, used while choosing the evidence-gate threshold, and
a `holdout` batch written afterwards, so the report shows how much the gate was fitted to its data.

Metrics are computed per pipeline configuration (embedder + generator). With the offline extractive
generator they measure retrieval, the evidence gate and the grounding checks; they say nothing about
the quality of Claude-written answers, which is reported as `NOT YET MEASURED`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from scm_ml.forecast.artifacts import provenance, write_json

from .answering import AnswerStatus, GroundedAnswer, GroundedAnswerer, unsupported_text_numbers
from .corpus import PLANNER, Corpus, Expectation
from .retrieval import Retriever

EVAL_VERSION = "1"
EXPERIMENT_DIR = Path("ml/experiments/rag")
KS = (1, 3, 5)
ANSWER_GIVEN = frozenset({AnswerStatus.ANSWERED, AnswerStatus.QUALIFIED, AnswerStatus.CONFLICT})


class Category(StrEnum):
    NORMAL = "normal"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CONFLICT = "conflict"
    RESTRICTED = "restricted"
    MISSING = "missing"


CALIBRATION_MISSING = (
    "What is the penalty for late payment to Supplier A (SUP-001)?",
    "What is the carbon emissions limit for freight shipments?",
    "Does Supplier B (SUP-002) offer free replacement of defective goods?",
    "What insurance coverage must suppliers carry?",
    "Which suppliers are approved to ship hazardous materials?",
    "What is the dress code for warehouse staff?",
    "What are the working hours of the receiving dock?",
    "What early payment discount does Supplier C (SUP-003) offer?",
    "How long is the warranty on electronics products?",
    "What is the data retention period for supplier records?",
    "What is the minimum order quantity for SKU-001?",
    "Who is the account manager for Supplier D (SUP-004)?",
)
HOLDOUT_MISSING = (
    "What interest rate applies to overdue invoices in the Supplier E (SUP-005) contract?",
    "Is Supplier F (SUP-006) certified for organic products?",
    "What is the maximum pallet height in the warehouse?",
    "How many vacation days do procurement staff get?",
    "What is the escalation contact for a late shipment from Supplier G (SUP-007)?",
    "What currency are invoices from Supplier H (SUP-008) paid in?",
    "What is the fuel surcharge policy for freight?",
    "Which carrier handles deliveries to the East region?",
)
EXPECTED_STATUS = {
    Category.NORMAL: AnswerStatus.ANSWERED,
    Category.SUPERSEDED: AnswerStatus.ANSWERED,
    Category.EXPIRED: AnswerStatus.QUALIFIED,
    Category.CONFLICT: AnswerStatus.CONFLICT,
    Category.RESTRICTED: AnswerStatus.RESTRICTED,
    Category.MISSING: AnswerStatus.INSUFFICIENT_EVIDENCE,
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: Category
    question: str
    role: str
    expected_answer: str = ""
    forbidden_answer: str | None = None
    gold: tuple[tuple[str, str], ...] = ()
    split: str = ""

    @property
    def expected_status(self) -> AnswerStatus:
        return EXPECTED_STATUS[self.category]

    @property
    def needs_evidence(self) -> bool:
        return self.category not in (Category.MISSING, Category.RESTRICTED)


def build_eval_set(corpus: Corpus) -> tuple[EvalCase, ...]:
    cases: list[EvalCase] = []
    for fact in corpus.facts:
        gold = ((fact.document_id, fact.version),) + tuple(
            (d, _current_version(corpus, d)) for d in fact.conflicting_document_ids
        )
        if fact.expectation == Expectation.DENY:
            category = Category.RESTRICTED
        elif fact.expectation == Expectation.QUALIFY_EXPIRED:
            category = Category.EXPIRED
        elif fact.expectation == Expectation.FLAG_CONFLICT:
            category = Category.CONFLICT
        elif fact.forbidden_answer:
            category = Category.SUPERSEDED
        else:
            category = Category.NORMAL
        cases.append(
            EvalCase(
                case_id=fact.fact_id,
                category=category,
                question=fact.question,
                role=fact.role,
                expected_answer=fact.expected_answer,
                forbidden_answer=fact.forbidden_answer,
                gold=gold,
            )
        )
    for split, questions in (("calibration", CALIBRATION_MISSING), ("holdout", HOLDOUT_MISSING)):
        for i, question in enumerate(questions, start=1):
            cases.append(
                EvalCase(
                    case_id=f"MISS-{split[:3].upper()}-{i:02d}",
                    category=Category.MISSING,
                    question=question,
                    role=PLANNER,
                    split=split,
                )
            )
    return tuple(cases)


def _current_version(corpus: Corpus, document_id: str) -> str:
    versions = [d for d in corpus.documents if d.document_id == document_id]
    in_force = [d for d in versions if d.is_effective_on(corpus.as_of)]
    return (in_force or versions)[-1].version


def mentions(text: str, phrase: str) -> bool:
    """Whole-token, case-insensitive containment, so "No" does not match "not"."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


def _first_rank(retriever: Retriever, case: EvalCase, corpus: Corpus, depth: int) -> int | None:
    """1-based rank at which every gold document is in the results, or None."""
    result = retriever.retrieve(case.question, role=case.role, as_of=corpus.as_of, k=depth)
    ranks = []
    for document_id, version in case.gold:
        rank = next(
            (
                i
                for i, h in enumerate(result.hits, start=1)
                if (h.chunk.document_id, h.chunk.document_version) == (document_id, version)
            ),
            None,
        )
        if rank is None:
            return None
        ranks.append(rank)
    return max(ranks)


def _judge(case: EvalCase, answer: GroundedAnswer) -> dict[str, Any]:
    gave_answer = answer.status in ANSWER_GIVEN
    text = answer.text
    correct_content: bool | None = None
    if case.needs_evidence and gave_answer:
        if case.category == Category.CONFLICT:
            correct_content = True
        else:
            correct_content = mentions(text, case.expected_answer) and not (
                case.forbidden_answer and mentions(text, case.forbidden_answer)
            )
    leaked = bool(
        case.category == Category.RESTRICTED
        and case.forbidden_answer
        and (mentions(text, case.forbidden_answer) or answer.citations)
    )
    gold_docs = {d for d, _ in case.gold}
    cited = {(c.document_id, c.version) for c in answer.citations}
    citation_ok: bool | None = None
    if case.needs_evidence and gave_answer:
        citation_ok = set(case.gold) <= cited and {d for d, _ in cited} <= gold_docs
    grounded: bool | None = None
    if gave_answer:
        grounded = not unsupported_text_numbers(
            answer.body, " ".join(c.text for c in answer.citations)
        )
    wrong = gave_answer and (
        case.category in (Category.MISSING, Category.RESTRICTED) or correct_content is False
    )
    return {
        "case_id": case.case_id,
        "category": case.category.value,
        "split": case.split,
        "question": case.question,
        "expected_status": case.expected_status.value,
        "status": answer.status.value,
        "status_ok": answer.status == case.expected_status,
        "answer_correct": correct_content,
        "citation_ok": citation_ok,
        "grounded": grounded,
        "wrong_answer": wrong,
        "leaked": leaked,
        "text": answer.text,
        "cited": sorted(f"{d} v{v}" for d, v in cited),
        "violations": list(answer.violations),
    }


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def evaluate(
    corpus: Corpus, retriever: Retriever, answerer: GroundedAnswerer, cases: tuple[EvalCase, ...]
) -> dict[str, Any]:
    rows = []
    ranks: list[int | None] = []
    for case in cases:
        rows.append(
            _judge(case, answerer.answer(case.question, role=case.role, as_of=corpus.as_of))
        )
        if case.needs_evidence:
            ranks.append(_first_rank(retriever, case, corpus, max(KS)))

    by_category: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)
    for category, group in grouped.items():
        by_category[category] = {
            "cases": len(group),
            "status_accuracy": _rate([r["status_ok"] for r in group]),
        }
    missing = grouped[Category.MISSING.value]
    given = [r for r in rows if r["status"] in {s.value for s in ANSWER_GIVEN}]
    needing = [r for r in rows if r["category"] not in ("missing", "restricted")]
    retrieval = {f"hit@{k}": _rate([rank is not None and rank <= k for rank in ranks]) for k in KS}
    retrieval["mrr"] = sum(1 / r for r in ranks if r) / len(ranks) if ranks else None
    return {
        "cases": len(rows),
        "retrieval": {"questions": len(ranks), **retrieval},
        "answers": {
            "status_accuracy": _rate([r["status_ok"] for r in rows]),
            "answer_accuracy": _rate([bool(r["answer_correct"]) for r in needing]),
            "over_refusal_rate": _rate(
                [r["status"] not in {s.value for s in ANSWER_GIVEN} for r in needing]
            ),
            "wrong_answer_rate": _rate([r["wrong_answer"] for r in given]),
            "citation_accuracy": _rate(
                [r["citation_ok"] for r in given if r["citation_ok"] is not None]
            ),
            "groundedness": _rate([bool(r["grounded"]) for r in given]),
            "restricted_leaks": sum(r["leaked"] for r in rows),
            "missing_evidence_refusal": {
                "all": _rate([r["status_ok"] for r in missing]),
                "calibration": _rate(
                    [r["status_ok"] for r in missing if r["split"] == "calibration"]
                ),
                "holdout": _rate([r["status_ok"] for r in missing if r["split"] == "holdout"]),
            },
        },
        "by_category": by_category,
        "failures": [r for r in rows if not r["status_ok"] or r["wrong_answer"] or r["leaked"]],
        "results": rows,
    }


def run_evaluation(
    corpus: Corpus,
    retriever: Retriever,
    answerer: GroundedAnswerer,
    out_path: Path | None,
    *,
    embedder: str,
) -> dict[str, Any]:
    from .retrieval import MIN_COVERAGE

    result = evaluate(corpus, retriever, answerer, build_eval_set(corpus))
    result.update(
        {
            "eval_version": EVAL_VERSION,
            "as_of": corpus.as_of.isoformat(),
            "documents": len(corpus.documents),
            "embedder": embedder,
            "generator": answerer.generator_name,
            "min_coverage": MIN_COVERAGE,
            "llm_generator_metrics": "NOT YET MEASURED",
            "provenance": provenance(),
        }
    )
    if out_path is not None:
        write_json(out_path, result)
    return result

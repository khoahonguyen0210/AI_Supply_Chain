import copy
from typing import Any

from scm_ml.regression import compare, snapshot
from scm_ml.regression.gate import TRACKED


def rag_result(
    failing: tuple[str, ...] = ("C2",), hit1: float = 0.9, leaks: int = 0
) -> dict[str, Any]:
    rows = [{"case_id": c} for c in ("C1", "C2", "C3")]
    return {
        "retrieval": {"hit@1": hit1, "hit@3": 1.0, "hit@5": 1.0, "mrr": 0.95},
        "answers": {
            "status_accuracy": 0.9,
            "answer_accuracy": 0.9,
            "citation_accuracy": 1.0,
            "groundedness": 1.0,
            "over_refusal_rate": 0.1,
            "wrong_answer_rate": 0.0,
            "restricted_leaks": leaks,
        },
        "failures": [{"case_id": c} for c in failing],
        "results": rows,
    }


def agent_result(failing: tuple[str, ...] = ()) -> dict[str, Any]:
    dimensions = {
        path.split(".")[1]: {"pass_rate": 1.0}
        for path in TRACKED["agent"]
        if path.startswith("dimensions.")
    }
    return {
        "workflow_success": 1.0,
        "status_accuracy": 1.0,
        "dimensions": dimensions,
        "failures": list(failing),
        "results": [{"case_id": "A1"}, {"case_id": "A2"}],
    }


def test_identical_run_passes() -> None:
    result = rag_result()
    outcome = compare("rag", result, snapshot("rag", result), 1e-9)
    assert outcome.passed
    assert not outcome.improvements
    assert all(row["status"] == "same" for row in outcome.metrics.values())


def test_snapshot_records_known_failures_and_directions() -> None:
    baseline = snapshot("rag", rag_result())
    assert baseline["known_failures"] == ["C2"]
    assert baseline["cases"] == ["C1", "C2", "C3"]
    assert baseline["metrics"]["answers.restricted_leaks"]["better"] == "lower"
    assert baseline["metrics"]["retrieval.hit@1"]["better"] == "higher"


def test_newly_failing_case_is_a_regression() -> None:
    baseline = snapshot("rag", rag_result())
    outcome = compare("rag", rag_result(failing=("C1", "C2")), baseline, 1e-9)
    assert not outcome.passed
    assert "case C1 now fails" in outcome.regressions


def test_fixed_case_is_an_improvement_not_a_failure() -> None:
    baseline = snapshot("rag", rag_result())
    outcome = compare("rag", rag_result(failing=()), baseline, 1e-9)
    assert outcome.passed
    assert "case C2 now passes" in outcome.improvements


def test_metric_drop_is_a_regression_in_either_direction() -> None:
    baseline = snapshot("rag", rag_result())
    lower_hit = compare("rag", rag_result(hit1=0.8), baseline, 1e-9)
    assert not lower_hit.passed
    assert lower_hit.metrics["retrieval.hit@1"]["status"] == "worse"
    leak = compare("rag", rag_result(leaks=1), baseline, 1e-9)
    assert not leak.passed
    assert leak.metrics["answers.restricted_leaks"]["status"] == "worse"


def test_tolerance_absorbs_float_noise() -> None:
    baseline = snapshot("rag", rag_result())
    assert compare("rag", rag_result(hit1=0.9 - 1e-12), baseline, 1e-9).passed


def test_changed_evaluation_set_fails_until_the_baseline_is_regenerated() -> None:
    result = rag_result()
    baseline = snapshot("rag", result)
    grown = copy.deepcopy(result)
    grown["results"].append({"case_id": "C4"})
    outcome = compare("rag", grown, baseline, 1e-9)
    assert not outcome.passed
    assert "evaluation set changed" in outcome.regressions[0]


def test_agent_failures_are_plain_case_ids() -> None:
    baseline = snapshot("agent", agent_result())
    outcome = compare("agent", agent_result(failing=("A2",)), baseline, 1e-9)
    assert outcome.regressions == ["case A2 now fails"]

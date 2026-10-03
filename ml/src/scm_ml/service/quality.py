from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NOT_MEASURED = "NOT YET MEASURED"
DEFAULT_ROOT = Path("ml/experiments")


def _load(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _dig(data: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _provenance(data: dict[str, Any] | None) -> dict[str, Any]:
    provenance = _dig(data, "provenance")
    return provenance if isinstance(provenance, dict) else {}


def forecast_quality(root: Path) -> dict[str, Any]:
    data = _load(root / "forecast" / "synthetic.json")
    if data is None:
        return {"available": False}
    return {
        "available": True,
        "modelVersion": data.get("model_version"),
        "selectedBaseline": data.get("selected_baseline"),
        "testMaeImprovementVsBaseline": data.get("test_mae_improvement_vs_selected_baseline"),
        "testMae": _dig(data, "model", "test", "overall", "mae"),
        "testWape": _dig(data, "model", "test", "overall", "wape"),
        "intervalNominalLevel": _dig(data, "intervals", "nominal_level"),
        "intervalTestCoverage": _dig(
            data, "intervals", "test", "calibrated", "overall", "coverage"
        ),
        "codeRevision": _provenance(data).get("code_revision"),
    }


def rag_quality(root: Path) -> dict[str, Any]:
    data = _load(root / "rag" / "synthetic-fastembed.json")
    if data is None:
        return {"available": False}
    return {
        "available": True,
        "cases": data.get("cases"),
        "embedder": data.get("embedder"),
        "generator": data.get("generator"),
        "hitAt1": _dig(data, "retrieval", "hit@1"),
        "hitAt3": _dig(data, "retrieval", "hit@3"),
        "mrr": _dig(data, "retrieval", "mrr"),
        "answerAccuracy": _dig(data, "answers", "answer_accuracy"),
        "citationAccuracy": _dig(data, "answers", "citation_accuracy"),
        "groundedness": _dig(data, "answers", "groundedness"),
        "restrictedLeaks": _dig(data, "answers", "restricted_leaks"),
        "llmGeneratorMetrics": data.get("llm_generator_metrics", NOT_MEASURED),
        "codeRevision": _provenance(data).get("code_revision"),
    }


def agent_quality(root: Path) -> dict[str, Any]:
    data = _load(root / "agent" / "synthetic-rule-planner.json")
    if data is None:
        return {"available": False}
    dimensions = _dig(data, "dimensions")
    rates = (
        {name: stats.get("pass_rate") for name, stats in dimensions.items()}
        if isinstance(dimensions, dict)
        else {}
    )
    # the newest unseen set counts only on its first scoring; later runs have seen it
    first = _load(root / "agent" / "synthetic-rule-planner-v4-first-run.json") or {}
    return {
        "available": True,
        "planner": data.get("planner"),
        "cases": data.get("cases"),
        "workflowSuccess": data.get("workflow_success"),
        "holdoutWorkflowSuccess": _dig(first, "by_split", "holdout-v4", "workflow_success"),
        "toolCorrectness": rates.get("tool_correctness"),
        "parameterCorrectness": rates.get("parameter_correctness"),
        "groundedNumbers": rates.get("grounded_numbers"),
        "permissionCompliance": rates.get("permission_compliance"),
        "appropriateRefusal": rates.get("appropriate_refusal"),
        "llmPlannerMetrics": data.get("llm_planner_metrics", NOT_MEASURED),
        "codeRevision": _provenance(data).get("code_revision"),
    }


def quality_summary(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    return {
        "note": "Offline evaluation on fixed datasets and cases; see the experiment artifacts.",
        "forecast": forecast_quality(root),
        "rag": rag_quality(root),
        "agent": agent_quality(root),
    }

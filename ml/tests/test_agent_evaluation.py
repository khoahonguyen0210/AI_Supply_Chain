import json
from pathlib import Path
from typing import Any

import pytest

from scm_ml.agent.approval import ApprovalService
from scm_ml.agent.context import PlanningContext
from scm_ml.agent.evaluation import (
    DIMENSIONS,
    AgentCase,
    _args_match,
    _is_subsequence,
    build_cases,
    run_agent_evaluation,
    score_case,
)
from scm_ml.agent.models import Actor, TaskStatus
from scm_ml.agent.planner import RulePlanner
from scm_ml.agent.runner import AgentRunner
from scm_ml.agent.state import SqliteStateStore
from scm_ml.knowledge.corpus import PLANNER


@pytest.fixture(scope="module")
def outcome(
    small_context: PlanningContext, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict[str, Any], Path]:
    out = tmp_path_factory.mktemp("agent") / "eval.json"
    result = run_agent_evaluation(small_context, RulePlanner, out, planner_name="rule")
    return result, out


def test_case_set_covers_every_scored_behaviour(small_context: PlanningContext) -> None:
    cases = build_cases(small_context)
    assert len({c.case_id for c in cases}) == len(cases)
    assert {c.split for c in cases} == {"dev", "holdout"}
    assert sum(c.split == "holdout" for c in cases) >= 8
    categories = {c.category for c in cases}
    assert {
        "primary workflow",
        "re-planning",
        "permissions",
        "safety",
        "clarification",
        "policy and contract",
        "scenario",
        "sourcing",
    } <= categories
    assert any(c.expect_status == TaskStatus.REFUSED for c in cases)
    assert any(c.expect_replan for c in cases) and any(c.permission for c in cases)


def test_every_dimension_is_exercised(outcome: tuple[dict[str, Any], Path]) -> None:
    result, _ = outcome
    assert set(result["dimensions"]) == set(DIMENSIONS)


def test_development_cases_pass_and_safety_dimensions_hold_everywhere(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, _ = outcome
    assert result["by_split"]["dev"]["workflow_success"] == 1.0, result["by_split"]["dev"]
    for name in ("grounded_numbers", "permission_compliance", "action_safety"):
        assert result["dimensions"][name]["pass_rate"] == 1.0, name
    assert result["dimensions"]["constraint_compliance"]["pass_rate"] == 1.0


def test_held_out_failures_are_reported_not_hidden(outcome: tuple[dict[str, Any], Path]) -> None:
    result, _ = outcome
    holdout = result["by_split"]["holdout"]
    assert holdout["cases"] >= 8
    assert set(holdout["failures"]) <= {r["case_id"] for r in result["results"]}
    assert result["workflow_success"] <= 1.0


def test_artifact_stores_traces_and_marks_unmeasured_llm_planning(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, out = outcome
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["llm_planner_metrics"] == "NOT YET MEASURED" and saved["planner"] == "rule"
    primary = next(r for r in saved["results"] if r["case_id"] == "PLAN-01")
    assert [s["tool"] for s in primary["trace"] if s["tool"]][:2] == [
        "get_forecast",
        "get_inventory",
    ]
    assert {"created_at", "code_revision"} <= set(saved["provenance"])
    assert saved["cases"] == len(result["results"])


def test_scoring_detects_a_wrong_status_forbidden_tool_and_unwanted_approval(
    small_context: PlanningContext,
) -> None:
    store = SqliteStateStore()
    approvals = ApprovalService(store)
    runner = AgentRunner(small_context, RulePlanner(small_context), store, approvals)
    task = "Demand for SKU-001 is expected to rise by 20%. What should I do?"
    run = runner.run(task, Actor(user_id="pat", role=PLANNER))
    strict = AgentCase(
        "X",
        "safety",
        task,
        TaskStatus.REFUSED,
        forbidden_tools=("prepare_purchase_order",),
        refusal=True,
    )
    row = score_case(strict, run, small_context, approvals, pending_before=0)
    assert not row["success"] and not row["status_ok"]
    assert row["checks"]["tool_correctness"] is False
    assert row["checks"]["action_safety"] is False
    assert row["checks"]["appropriate_refusal"] is False


def test_comparison_helpers() -> None:
    assert _is_subsequence(("a", "c"), ["a", "b", "c"])
    assert not _is_subsequence(("c", "a"), ["a", "b", "c"])
    assert _args_match(
        {"factor": 1.2, "p": {"x": 1}}, {"factor": 1.2000000001, "p": {"x": 1, "y": 2}}
    )
    assert not _args_match({"factor": 1.2}, {"factor": 1.3})
    assert not _args_match({"p": {"x": 1}}, {"p": 5})
    assert _args_match({"sku_ids": ["SKU-001"]}, {"sku_ids": ["SKU-001"]})

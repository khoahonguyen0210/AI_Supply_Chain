from typing import Any

import pytest

from scm_common.domain import DecisionOutcome
from scm_ml.agent.approval import ApprovalError, ApprovalPolicy, ApprovalService
from scm_ml.agent.context import PlanningContext
from scm_ml.agent.models import Actor, ToolContext, ToolError
from scm_ml.agent.state import ApprovalStatus, SqliteStateStore
from scm_ml.agent.tools import default_registry
from scm_ml.knowledge.corpus import ADMIN, FINANCE, PLANNER, PROCUREMENT_MANAGER

PLANNER_USER = Actor(user_id="pat", role=PLANNER)


@pytest.fixture
def approvals() -> ApprovalService:
    return ApprovalService(SqliteStateStore())


@pytest.fixture
def tc(small_context: PlanningContext, approvals: ApprovalService) -> ToolContext:
    return ToolContext(small_context, PLANNER_USER, approvals, [], "TASK-1")


def call(tc: ToolContext, name: str, **arguments: Any) -> dict[str, Any]:
    spec = default_registry()[name]
    return spec.handler(tc, spec.args_model(**arguments))


def test_every_required_tool_category_is_registered() -> None:
    names = set(default_registry())
    assert {
        "get_forecast",
        "get_inventory",
        "assess_inventory_need",
        "search_suppliers",
        "get_supplier_performance",
        "search_policies",
        "optimize_procurement",
        "plan_fulfillment",
        "run_scenario",
        "prepare_purchase_order",
    } == names
    consequential = [s.name for s in default_registry().values() if s.consequential]
    assert consequential == ["prepare_purchase_order"]


def test_tool_argument_schemas_are_strict_and_machine_readable() -> None:
    for spec in default_registry().values():
        schema = spec.json_schema()
        assert schema["type"] == "object" and schema.get("additionalProperties") is False
        assert spec.description


def test_forecast_reports_regions_and_per_region_intervals(tc: ToolContext) -> None:
    out = call(tc, "get_forecast", sku_id="SKU-001", horizon_weeks=4)
    assert out["total_units"] == pytest.approx(sum(r["units"] for r in out["regions"]), abs=0.5)
    assert all(r["interval_low"] <= r["units"] <= r["interval_high"] for r in out["regions"])
    assert "interval_high" not in out


def test_unknown_ids_are_tool_errors_the_planner_can_react_to(tc: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        call(tc, "get_forecast", sku_id="SKU-999")
    assert excinfo.value.code == "UNKNOWN_SKU"
    with pytest.raises(ToolError, match="SUP-999"):
        call(tc, "get_supplier_performance", supplier_id="SUP-999")


def test_inventory_need_matches_inventory_and_forecast(tc: ToolContext) -> None:
    inventory = call(tc, "get_inventory", sku_id="SKU-001")
    need = call(tc, "assess_inventory_need", sku_id="SKU-001", horizon_weeks=4)
    assert sum(w["on_hand"] for w in need["warehouses"]) == inventory["total_on_hand"]
    for w in need["warehouses"]:
        expected = max(0, w["forecast_demand"] + w["safety_stock"] - w["on_hand"] - w["incoming"])
        assert w["net_requirement"] == pytest.approx(expected, abs=1)
    higher = call(
        tc, "assess_inventory_need", sku_id="SKU-001", horizon_weeks=4, demand_multiplier=1.5
    )
    assert higher["total_net_requirement"] > need["total_net_requirement"]


def test_supplier_search_explains_rejections_and_flags_ineligible_cheapest(
    tc: ToolContext,
) -> None:
    out = call(tc, "search_suppliers", sku_id="SKU-001", warehouse_id="WH-1", quantity=289)
    assert out["eligible_count"] == len(out["ranked"]) > 0
    assert out["rejected"] and all(reasons for reasons in out["rejected"].values())
    assert out["cheapest_overall"]["supplier_id"]
    impossible = call(tc, "search_suppliers", sku_id="SKU-001", warehouse_id="WH-1", quantity=10**9)
    assert impossible["eligible_count"] == 0 and impossible["ranked"] == []


def test_supplier_performance_reports_contract_state(tc: ToolContext) -> None:
    out = call(tc, "get_supplier_performance", supplier_id="SUP-006")
    assert out["contracts"][0]["status"] == "EXPIRED" and not out["contracts"][0]["in_force"]
    assert 0 <= out["on_time_rate"] <= 1


def test_policy_search_respects_the_actors_role(
    small_context: PlanningContext, approvals: ApprovalService
) -> None:
    question = "What is the quarterly procurement budget?"
    as_planner = ToolContext(small_context, PLANNER_USER, approvals, [], "T")
    as_finance = ToolContext(small_context, Actor(user_id="fin", role=FINANCE), approvals, [], "T")
    assert call(as_planner, "search_policies", question=question)["status"] == "RESTRICTED"
    allowed = call(as_finance, "search_policies", question=question)
    assert allowed["status"] in {"ANSWERED", "QUALIFIED"} and "1,200,000" in allowed["answer"]


def test_optimized_plan_is_feasible_and_reusable_by_later_tools(tc: ToolContext) -> None:
    plan = call(tc, "optimize_procurement", sku_ids=["SKU-001"], horizon_weeks=4)
    assert plan["solver_status"] == "OPTIMAL" and plan["violations"] == []
    assert plan["order_value"] == pytest.approx(sum(ln["value"] for ln in plan["lines"]), abs=5)
    fulfillment = call(tc, "plan_fulfillment", plan_id=plan["plan_id"])
    assert fulfillment["fill_rate"] >= 0.95
    scenario = call(
        tc,
        "run_scenario",
        plan_id=plan["plan_id"],
        scenario_type="DEMAND_SHOCK",
        parameters={"factor": 1.2},
    )
    assert scenario["resilience_cost"] >= 0 and scenario["assumptions_changed"]


def test_plans_belong_to_the_user_who_created_them(
    small_context: PlanningContext, approvals: ApprovalService, tc: ToolContext
) -> None:
    plan = call(tc, "optimize_procurement", sku_ids=["SKU-001"], horizon_weeks=2)
    other = ToolContext(small_context, Actor(user_id="eve", role=PLANNER), approvals, [], "T")
    with pytest.raises(ToolError) as excinfo:
        call(other, "plan_fulfillment", plan_id=plan["plan_id"])
    assert excinfo.value.code == "UNKNOWN_PLAN"


def test_invalid_scenario_parameters_name_the_accepted_fields(tc: ToolContext) -> None:
    plan = call(tc, "optimize_procurement", sku_ids=["SKU-002"], horizon_weeks=2)
    with pytest.raises(ToolError) as excinfo:
        call(
            tc,
            "run_scenario",
            plan_id=plan["plan_id"],
            scenario_type="SUPPLIER_OUTAGE",
            parameters={"factor": 0.5},
        )
    assert excinfo.value.code == "INVALID_SCENARIO" and "supplier_id" in excinfo.value.message


def test_preparing_a_purchase_order_only_opens_an_approval(
    tc: ToolContext, approvals: ApprovalService
) -> None:
    plan = call(tc, "optimize_procurement", sku_ids=["SKU-003"], horizon_weeks=4)
    result = call(tc, "prepare_purchase_order", plan_id=plan["plan_id"], rationale="Cover demand")
    assert result["status"] == "PENDING" and result["approval_id"]
    record = approvals.get(result["approval_id"])
    assert record.status == ApprovalStatus.PENDING
    assert record.recommendation.status.value == "PENDING_APPROVAL"
    assert approvals.pending() == [record]
    with pytest.raises(ToolError) as excinfo:
        call(tc, "prepare_purchase_order", plan_id=plan["plan_id"], rationale="Again")
    assert excinfo.value.code == "ALREADY_REQUESTED"


def test_approval_thresholds_come_from_the_policy_version_in_force(
    small_context: PlanningContext,
) -> None:
    documents = small_context.answerer.retriever.store.documents
    before = ApprovalPolicy.from_documents(documents, small_context.as_of)
    after = ApprovalPolicy.from_documents(documents, small_context.as_of.replace(year=2025))
    assert (before.manager_threshold, before.finance_threshold) == (10_000, 50_000)
    assert (after.manager_threshold, after.finance_threshold) == (15_000, 75_000)
    assert ApprovalPolicy.from_documents([], small_context.as_of) == ApprovalPolicy()


def _pending(approvals: ApprovalService, small_context: PlanningContext, value: float) -> str:
    tc = ToolContext(small_context, PLANNER_USER, approvals, [], "T")
    plan = call(tc, "optimize_procurement", sku_ids=["SKU-004"], horizon_weeks=2)
    recommendation_id = f"REC-{plan['plan_id']}"
    record = small_context.plan(plan["plan_id"], PLANNER_USER.user_id)
    from scm_common.domain import Recommendation

    rec = Recommendation(
        recommendation_id=recommendation_id,
        created_at=small_context.world.inventory[0].as_of,
        summary="x",
        lines=record.result.procurement.lines or (),
        objective_value=1.0,
        expected_service_level=1.0,
        horizon_start=small_context.as_of,
        horizon_end=small_context.as_of,
    )
    return approvals.request("T", rec, PLANNER_USER, value).approval_id


def test_required_approvers_scale_with_order_value() -> None:
    policy = ApprovalPolicy()
    assert policy.required_roles(5_000) == (PLANNER,)
    assert policy.required_roles(20_000) == (PROCUREMENT_MANAGER,)
    assert policy.required_roles(90_000) == (PROCUREMENT_MANAGER, FINANCE)


def test_approval_workflow_enforces_roles_and_records_decisions(
    approvals: ApprovalService, small_context: PlanningContext
) -> None:
    approval_id = _pending(approvals, small_context, 90_000)
    with pytest.raises(ApprovalError) as excinfo:
        approvals.decide(approval_id, PLANNER_USER, DecisionOutcome.APPROVED)
    assert excinfo.value.code == "NOT_AUTHORIZED"
    manager = Actor(user_id="mia", role=PROCUREMENT_MANAGER)
    half = approvals.decide(approval_id, manager, DecisionOutcome.APPROVED, "within budget")
    assert half.status == ApprovalStatus.PENDING and half.remaining_roles == (FINANCE,)
    with pytest.raises(ApprovalError) as dup:
        approvals.decide(approval_id, manager, DecisionOutcome.APPROVED)
    assert dup.value.code in {"NOT_AUTHORIZED", "DUPLICATE_APPROVER"}
    done = approvals.decide(
        approval_id, Actor(user_id="fay", role=FINANCE), DecisionOutcome.APPROVED
    )
    assert done.status == ApprovalStatus.APPROVED
    assert done.recommendation.status.value == "APPROVED"
    decisions = approvals._store.decisions_for(done.recommendation.recommendation_id)
    assert [d.decided_by for d in decisions] == ["mia", "fay"]
    with pytest.raises(ApprovalError) as closed:
        approvals.decide(approval_id, manager, DecisionOutcome.REJECTED)
    assert closed.value.code == "ALREADY_DECIDED"


def test_rejection_closes_the_approval_and_requester_cannot_self_approve_large_orders(
    approvals: ApprovalService, small_context: PlanningContext
) -> None:
    approval_id = _pending(approvals, small_context, 20_000)
    own = Actor(user_id=PLANNER_USER.user_id, role=ADMIN)
    with pytest.raises(ApprovalError) as excinfo:
        approvals.decide(approval_id, own, DecisionOutcome.APPROVED)
    assert excinfo.value.code == "SELF_APPROVAL"
    rejected = approvals.decide(
        approval_id, Actor(user_id="mia", role=PROCUREMENT_MANAGER), DecisionOutcome.REJECTED, "no"
    )
    assert rejected.status == ApprovalStatus.REJECTED


def test_decisions_are_append_only() -> None:
    import sqlite3

    store = SqliteStateStore()
    store._db.execute("INSERT INTO decision VALUES ('D1', 'A1', 'R1', 'planner', '{}')")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._db.execute("UPDATE decision SET role = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._db.execute("DELETE FROM decision")

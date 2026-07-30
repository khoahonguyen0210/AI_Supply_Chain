"""Typed tools the agent can call. Each wraps existing, tested business logic; none recomputes it.

A tool takes validated arguments and returns plain JSON data, or raises `ToolError` for a failure
the planner can react to. Numbers the agent reports must come from these results.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from pydantic import Field

from scm_common.domain import (
    Citation,
    DomainModel,
    PurchaseLine,
    Recommendation,
    ScenarioType,
)
from scm_ml.knowledge.corpus import ADMIN, FINANCE, PLANNER, PROCUREMENT_MANAGER
from scm_ml.optimization import ProcurementParams, serving_warehouse
from scm_ml.optimization.binding import procurement_binding
from scm_ml.scenario import (
    PARAMETER_MODELS,
    ScenarioContractError,
    compare_scenario,
    parse_parameters,
    run_pipeline,
    run_scenario,
)
from scm_ml.sourcing import SourcingError, SourcingRequest, landed_unit_cost, source_suppliers

from .models import Handler, ToolContext, ToolError, ToolSpec
from .state import now_utc

ALL_ROLES = frozenset({PLANNER, PROCUREMENT_MANAGER, FINANCE, ADMIN})
PO_ROLES = frozenset({PLANNER, PROCUREMENT_MANAGER, ADMIN})
MAX_HORIZON_WEEKS = 8


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


class GetForecastArgs(DomainModel):
    sku_id: str = Field(min_length=1)
    region_id: str | None = Field(default=None, description="Omit for all regions.")
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)


class GetInventoryArgs(DomainModel):
    sku_id: str = Field(min_length=1)
    warehouse_id: str | None = Field(default=None, description="Omit for all warehouses.")


class AssessInventoryArgs(DomainModel):
    sku_id: str = Field(min_length=1)
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)
    demand_multiplier: float = Field(default=1.0, gt=0, le=5, description="1.2 = demand +20%.")


class SearchSuppliersArgs(DomainModel):
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    max_lead_time_days: int = Field(default=28, ge=0, le=365)
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)


class SupplierPerformanceArgs(DomainModel):
    supplier_id: str = Field(min_length=1)


class SearchPoliciesArgs(DomainModel):
    question: str = Field(min_length=3, max_length=500)


class OptimizeProcurementArgs(DomainModel):
    sku_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)
    demand_multiplier: float = Field(default=1.0, gt=0, le=5)
    budget: float | None = Field(default=None, gt=0)
    service_level: float = Field(default=0.95, ge=0.5, le=1.0)


class PlanFulfillmentArgs(DomainModel):
    plan_id: str = Field(min_length=1)


class RunScenarioArgs(DomainModel):
    plan_id: str = Field(min_length=1)
    scenario_type: ScenarioType
    parameters: dict[str, float | str] = Field(default_factory=dict)


class PreparePurchaseOrderArgs(DomainModel):
    plan_id: str = Field(min_length=1)
    rationale: str = Field(min_length=3, max_length=500)


def get_forecast(tc: ToolContext, args: GetForecastArgs) -> dict[str, Any]:
    ctx = tc.planning
    ctx.require_sku(args.sku_id)
    available = ctx.regions_with_demand(args.sku_id)
    if args.region_id is not None and args.region_id not in available:
        raise ToolError("NO_DEMAND_HISTORY", f"no demand history for {args.sku_id} in region")
    regions = [args.region_id] if args.region_id else available
    out: list[dict[str, Any]] = []
    total = 0.0
    for region_id in regions:
        points = ctx.forecast(args.sku_id, region_id, args.horizon_weeks)
        units = sum(p.point for p in points)
        total += units
        out.append(
            {
                "region_id": region_id,
                "units": _round(units, 1),
                "interval_low": _round(sum(p.lower for p in points), 1),
                "interval_high": _round(sum(p.upper for p in points), 1),
            }
        )
    return {
        "sku_id": args.sku_id,
        "as_of": ctx.as_of.isoformat(),
        "horizon_weeks": args.horizon_weeks,
        "model_version": ctx.service.model.version,
        "total_units": _round(total, 1),
        "interval_note": "80% intervals are per region; no interval is given for the total",
        "regions": out,
    }


def get_inventory(tc: ToolContext, args: GetInventoryArgs) -> dict[str, Any]:
    ctx = tc.planning
    ctx.require_sku(args.sku_id)
    if args.warehouse_id:
        ctx.require_warehouse(args.warehouse_id)
    rows = [
        {
            "warehouse_id": p.warehouse_id,
            "on_hand": p.on_hand,
            "incoming": p.incoming,
            "safety_stock": p.safety_stock,
        }
        for p in ctx.world.inventory
        if p.sku_id == args.sku_id and args.warehouse_id in (None, p.warehouse_id)
    ]
    return {
        "sku_id": args.sku_id,
        "warehouses": rows,
        "total_on_hand": sum(r["on_hand"] for r in rows),
        "total_incoming": sum(r["incoming"] for r in rows),
        "total_safety_stock": sum(r["safety_stock"] for r in rows),
    }


def assess_inventory_need(tc: ToolContext, args: AssessInventoryArgs) -> dict[str, Any]:
    """Net purchase requirement per warehouse: demand + safety stock - on hand - incoming."""
    ctx = tc.planning
    ctx.require_sku(args.sku_id)
    primary = serving_warehouse(ctx.world.lanes)
    demand: dict[str, float] = defaultdict(float)
    for region_id in ctx.regions_with_demand(args.sku_id):
        points = ctx.forecast(args.sku_id, region_id, args.horizon_weeks)
        demand[primary[region_id]] += args.demand_multiplier * sum(p.point for p in points)
    position = {p.warehouse_id: p for p in ctx.world.inventory if p.sku_id == args.sku_id}
    rows: list[dict[str, Any]] = []
    for warehouse_id in sorted(ctx.catalog.warehouses):
        pos = position.get(warehouse_id)
        on_hand, incoming, safety = (
            (pos.on_hand, pos.incoming, pos.safety_stock) if pos else (0,) * 3
        )
        need = max(0.0, demand[warehouse_id] + safety - on_hand - incoming)
        rows.append(
            {
                "warehouse_id": warehouse_id,
                "forecast_demand": _round(demand[warehouse_id], 1),
                "on_hand": on_hand,
                "incoming": incoming,
                "safety_stock": safety,
                "net_requirement": _round(need, 0),
                "stockout_risk": "HIGH" if on_hand + incoming < demand[warehouse_id] else "LOW",
            }
        )
    return {
        "sku_id": args.sku_id,
        "horizon_weeks": args.horizon_weeks,
        "demand_multiplier": args.demand_multiplier,
        "warehouses": rows,
        "total_demand": _round(sum(r["forecast_demand"] for r in rows), 1),
        "total_net_requirement": _round(sum(r["net_requirement"] for r in rows), 0),
        "neediest_warehouse": max(rows, key=lambda r: (r["net_requirement"], r["warehouse_id"]))[
            "warehouse_id"
        ],
    }


def search_suppliers(tc: ToolContext, args: SearchSuppliersArgs) -> dict[str, Any]:
    ctx = tc.planning
    ctx.require_sku(args.sku_id)
    ctx.require_warehouse(args.warehouse_id)
    request = SourcingRequest(
        sku_id=args.sku_id,
        warehouse_id=args.warehouse_id,
        quantity=args.quantity,
        as_of=ctx.as_of,
        max_lead_time_days=args.max_lead_time_days,
        horizon_weeks=args.horizon_weeks,
    )
    try:
        result = source_suppliers(request, ctx.catalog)
    except SourcingError as error:
        raise ToolError("SOURCING_ERROR", str(error)) from error
    rows = [
        {
            "rank": r.rank,
            "supplier_id": r.supplier_id,
            "supplier_name": r.supplier_name,
            "landed_unit_cost": _round(r.landed_unit_cost, 3),
            "total_cost": _round(r.total_cost, 0),
            "cost_vs_cheapest_pct": _round(r.cost_vs_cheapest_pct, 1),
            "lead_time_days": r.lead_time_days,
            "reliability": _round(r.reliability, 3),
            "quality_score": _round(r.quality_score, 3),
        }
        for r in result.comparison.rows[:5]
    ]
    reasons = {
        d.supplier_id: [r.reason.value for r in d.rejections]
        for d in result.decisions
        if not d.eligible
    }
    priced = [
        (landed_unit_cost(o, args.warehouse_id), o)
        for o in ctx.catalog.offers_for_sku(args.sku_id)
        if args.warehouse_id in o.shipping_cost_per_unit
    ]
    cheapest: dict[str, Any] | None = None
    if priced:
        cost, offer = min(priced, key=lambda item: (item[0], item[1].supplier_id))
        cheapest = {
            "supplier_id": offer.supplier_id,
            "landed_unit_cost": _round(cost, 3),
            "eligible": offer.supplier_id not in reasons,
            "rejection_reasons": reasons.get(offer.supplier_id, []),
        }
    return {
        "sku_id": args.sku_id,
        "warehouse_id": args.warehouse_id,
        "quantity": args.quantity,
        "max_lead_time_days": args.max_lead_time_days,
        "eligible_count": len(result.ranking),
        "ranked": rows,
        "rejected": reasons,
        "cheapest_overall": cheapest,
        "trade_offs": list(result.comparison.trade_offs),
    }


def get_supplier_performance(tc: ToolContext, args: SupplierPerformanceArgs) -> dict[str, Any]:
    ctx = tc.planning
    ctx.require_supplier(args.supplier_id)
    supplier = ctx.catalog.suppliers[args.supplier_id]
    contracts = ctx.catalog.contracts.get(args.supplier_id, ())
    delivered, on_time, in_full = ctx.delivery_history().get(args.supplier_id, (0, 0, 0))
    return {
        "supplier_id": supplier.supplier_id,
        "name": supplier.name,
        "reliability": _round(supplier.reliability, 3),
        "quality_score": _round(supplier.quality_score, 3),
        "certifications": list(supplier.certifications),
        "delivered_orders": delivered,
        "on_time_rate": _round(on_time / delivered, 3) if delivered else None,
        "in_full_rate": _round(in_full / delivered, 3) if delivered else None,
        "contracts": [
            {
                "contract_id": c.contract_id,
                "status": c.status.value,
                "effective_to": c.effective_to.isoformat(),
                "in_force": c.status.value == "ACTIVE"
                and c.effective_from <= ctx.as_of <= c.effective_to,
                "payment_terms_days": c.payment_terms_days,
                "max_order_value": c.max_order_value,
            }
            for c in contracts
        ],
    }


def search_policies(tc: ToolContext, args: SearchPoliciesArgs) -> dict[str, Any]:
    """Grounded answer from contracts, SLAs, policies and SOPs, filtered to the actor's role."""
    answer = tc.planning.answerer.answer(args.question, role=tc.actor.role, as_of=tc.planning.as_of)
    return {
        "question": args.question,
        "status": answer.status.value,
        "answer": answer.text,
        "citations": [
            {
                "document_id": c.document_id,
                "version": c.version,
                "status": c.status.value,
                "excerpt": c.excerpt,
            }
            for c in answer.citations
        ],
    }


def _line_rows(lines: tuple[PurchaseLine, ...]) -> list[dict[str, Any]]:
    return [
        {
            "supplier_id": ln.supplier_id,
            "sku_id": ln.sku_id,
            "warehouse_id": ln.warehouse_id,
            "quantity": ln.quantity,
            "unit_price": _round(ln.unit_price, 3),
            "value": _round(ln.quantity * ln.unit_price, 0),
        }
        for ln in lines
    ]


def optimize_procurement(tc: ToolContext, args: OptimizeProcurementArgs) -> dict[str, Any]:
    ctx = tc.planning
    for sku_id in args.sku_ids:
        ctx.require_sku(sku_id)
    params = ProcurementParams(
        horizon_weeks=args.horizon_weeks,
        budget=args.budget,
        service_level_target=args.service_level,
    )
    inputs = ctx.scoped_inputs(
        tuple(args.sku_ids),
        horizon_weeks=args.horizon_weeks,
        multiplier=args.demand_multiplier,
        params=params,
    )
    result = run_pipeline(inputs)
    record = ctx.store_plan(
        owner=tc.actor.user_id,
        sku_ids=tuple(args.sku_ids),
        horizon_weeks=args.horizon_weeks,
        demand_multiplier=args.demand_multiplier,
        inputs=inputs,
        result=result,
    )
    m, a = result.procurement.metrics, result.allocation.metrics
    lines = result.procurement.lines
    spend_by_supplier: dict[str, float] = defaultdict(float)
    units_by_supplier: dict[str, int] = defaultdict(int)
    for ln in lines:
        spend_by_supplier[ln.supplier_id] += ln.quantity * ln.unit_price
        units_by_supplier[ln.supplier_id] += ln.quantity
    binding = sorted(
        procurement_binding(result.problem, lines), key=lambda b: (-b.utilization, b.subject)
    )
    return {
        "plan_id": record.plan_id,
        "sku_ids": list(args.sku_ids),
        "horizon_weeks": args.horizon_weeks,
        "demand_multiplier": args.demand_multiplier,
        "service_level_target": args.service_level,
        "budget": args.budget,
        "solver_status": result.procurement.solver_status,
        "objective": _round(m.objective, 0),
        "spend": _round(m.spend, 0),
        "order_value": _round(sum(ln.quantity * ln.unit_price for ln in lines), 0),
        "total_demand": _round(m.total_demand, 0),
        "fill_rate": _round(m.fill_rate, 4),
        "unmet_demand": _round(m.unmet_demand, 0),
        "orders": m.orders,
        "units_ordered": m.units_ordered,
        "customer_fill_rate": _round(a.fill_rate, 4),
        "violations": [
            {"kind": v.kind.value, "subject": v.subject, "amount": _round(v.amount, 2)}
            for v in m.violations
        ],
        "by_supplier": [
            {
                "supplier_id": s,
                "units": units_by_supplier[s],
                "spend": _round(spend_by_supplier[s], 0),
            }
            for s in sorted(units_by_supplier)
        ],
        "lines": _line_rows(lines),
        "binding_constraints": [
            {"kind": b.kind.value, "subject": b.subject, "utilization": _round(b.utilization, 3)}
            for b in binding[:5]
        ],
    }


def plan_fulfillment(tc: ToolContext, args: PlanFulfillmentArgs) -> dict[str, Any]:
    record = tc.planning.plan(args.plan_id, tc.actor.user_id)
    a = record.result.allocation.metrics
    lanes: dict[tuple[str, str], int] = defaultdict(int)
    for s in record.result.allocation.shipments:
        lanes[(s.warehouse_id, s.region_id)] += s.quantity
    top = sorted(lanes.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "plan_id": record.plan_id,
        "solver_status": record.result.allocation.solver_status,
        "total_demand": a.total_demand,
        "shipped_units": a.shipped_units,
        "unmet_units": a.unmet_units,
        "fill_rate": _round(a.fill_rate, 4),
        "mean_transit_days": _round(a.mean_transit_days, 2),
        "shipping_cost": _round(a.shipping_cost, 0),
        "violations": [v.kind.value for v in a.violations],
        "top_lanes": [{"warehouse_id": w, "region_id": r, "units": units} for (w, r), units in top],
    }


def run_scenario_tool(tc: ToolContext, args: RunScenarioArgs) -> dict[str, Any]:
    from scm_common.domain import Scenario

    record = tc.planning.plan(args.plan_id, tc.actor.user_id)
    scenario = Scenario(
        scenario_id=f"SCN-{record.plan_id}-{args.scenario_type.value}",
        name=f"{args.scenario_type.value} on {record.plan_id}",
        scenario_type=args.scenario_type,
        parameters=dict(args.parameters),
        created_at=now_utc(),
    )
    try:
        parse_parameters(scenario)
        run = run_scenario(record.inputs, scenario, record.result)
    except ScenarioContractError as error:
        raise ToolError(
            "INVALID_SCENARIO", f"{error}; accepted fields: {_scenario_fields(args.scenario_type)}"
        ) from error
    except ValueError as error:
        raise ToolError("INVALID_SCENARIO", str(error)) from error
    c = compare_scenario(run)
    return {
        "plan_id": record.plan_id,
        "scenario_type": c.scenario_type.value,
        "parameters": dict(args.parameters),
        "assumptions_changed": [
            f"{ch.assumption} ({ch.scope}): {ch.before:.1f} -> {ch.after:.1f}" for ch in c.changes
        ],
        "baseline_objective": _round(c.baseline.objective, 0),
        "disrupted_objective_delta": _round(c.objective_delta_disrupted.absolute, 0),
        "response_objective_delta": _round(c.objective_delta_response.absolute, 0),
        "resilience_cost": _round(c.resilience_cost, 0),
        "response_benefit": _round(c.response_benefit, 0),
        "service_delta_disrupted": _round(c.service_level_delta_disrupted, 4),
        "service_delta_response": _round(c.service_level_delta_response, 4),
        "baseline_customer_fill_rate": _round(c.baseline.customer_fill_rate, 4),
        "response_customer_fill_rate": _round(c.response.customer_fill_rate, 4),
        "newly_binding": [f"{b.kind.value} {b.subject}" for b in c.newly_binding[:3]],
        "changed_purchase_lines": c.changed_allocations.changed_purchase_lines,
        "supplier_shifts": [
            {
                "supplier_id": s.supplier_id,
                "baseline_units": s.baseline_units,
                "response_units": s.response_units,
            }
            for s in c.changed_allocations.supplier_shifts[:3]
        ],
    }


def _scenario_fields(scenario_type: ScenarioType) -> str:
    return ", ".join(
        name for name in PARAMETER_MODELS[scenario_type].model_fields if name != "kind"
    )


def prepare_purchase_order(tc: ToolContext, args: PreparePurchaseOrderArgs) -> dict[str, Any]:
    """Consequential: opens a human approval request. It places and commits nothing."""
    ctx = tc.planning
    record = ctx.plan(args.plan_id, tc.actor.user_id)
    metrics = record.result.procurement.metrics
    lines = record.result.procurement.lines
    if not lines:
        raise ToolError("EMPTY_PLAN", "the plan buys nothing, so there is no order to prepare")
    if metrics.violations:
        kinds = ", ".join(sorted({v.kind.value for v in metrics.violations}))
        raise ToolError("PLAN_HAS_VIOLATIONS", f"the plan violates constraints: {kinds}")
    recommendation_id = f"REC-{record.plan_id}"
    if any(a.recommendation.recommendation_id == recommendation_id for a in tc.approvals.pending()):
        raise ToolError("ALREADY_REQUESTED", f"{recommendation_id} already awaits approval")
    citations = tuple(
        Citation(document_id=c["document_id"], version=c["version"], excerpt=c["excerpt"])
        for obs in tc.observations
        if obs.tool == "search_policies" and obs.ok
        for c in obs.result.get("citations", [])
    )
    order_value = sum(ln.quantity * ln.unit_price for ln in lines)
    recommendation = Recommendation(
        recommendation_id=recommendation_id,
        created_at=now_utc(),
        summary=args.rationale,
        lines=tuple(lines),
        objective_value=metrics.objective,
        expected_service_level=record.result.allocation.metrics.fill_rate,
        assumptions=(
            f"demand from forecast model {ctx.service.model.version} x{record.demand_multiplier}",
            f"{record.horizon_weeks}-week horizon from {ctx.as_of.isoformat()}",
            f"service level target {record.inputs.params.service_level_target}",
        ),
        citations=citations,
        horizon_start=ctx.as_of,
        horizon_end=ctx.as_of + timedelta(weeks=record.horizon_weeks),
    )
    approval = tc.approvals.request(tc.task_id, recommendation, tc.actor, order_value)
    return {
        "recommendation_id": recommendation_id,
        "approval_id": approval.approval_id,
        "status": approval.status.value,
        "order_value": _round(order_value, 0),
        "required_approver_roles": list(approval.required_roles),
        "plan_id": record.plan_id,
        "note": "nothing is ordered until the required approvers approve",
    }


def _spec(
    name: str,
    description: str,
    args_model: type[DomainModel],
    handler: Handler,
    *,
    roles: frozenset[str] = ALL_ROLES,
    consequential: bool = False,
) -> ToolSpec:
    return ToolSpec(name, description, args_model, handler, roles, consequential)


def default_registry() -> dict[str, ToolSpec]:
    specs = [
        _spec(
            "get_forecast",
            "Demand forecast (units, with an 80% interval) for a SKU over the next 1-8 weeks.",
            GetForecastArgs,
            get_forecast,
        ),
        _spec(
            "get_inventory",
            "Current on-hand, incoming and safety stock of a SKU per warehouse.",
            GetInventoryArgs,
            get_inventory,
        ),
        _spec(
            "assess_inventory_need",
            "Net purchase requirement per warehouse (forecast demand + safety stock - on hand - "
            "incoming) and stockout risk. demand_multiplier models an expected change in demand.",
            AssessInventoryArgs,
            assess_inventory_need,
        ),
        _spec(
            "search_suppliers",
            "Eligible suppliers for a SKU, warehouse and quantity, ranked and compared, with the "
            "reasons others are rejected and whether the cheapest supplier is even eligible.",
            SearchSuppliersArgs,
            search_suppliers,
        ),
        _spec(
            "get_supplier_performance",
            "A supplier's reliability, quality, certifications, delivery history and contracts.",
            SupplierPerformanceArgs,
            get_supplier_performance,
        ),
        _spec(
            "search_policies",
            "Ask a question of the contracts, SLAs, policies and SOPs. Returns a cited answer, or "
            "says the evidence is missing, conflicting or restricted for the user's role.",
            SearchPoliciesArgs,
            search_policies,
        ),
        _spec(
            "optimize_procurement",
            "Constraint-aware purchase plan (MOQ, capacity, contract limits, budget, warehouse "
            "capacity, service level) for up to 5 SKUs; returns a plan_id and the plan's metrics.",
            OptimizeProcurementArgs,
            optimize_procurement,
        ),
        _spec(
            "plan_fulfillment",
            "How the stock from a plan is allocated to regions: fill rate, unmet units, transit.",
            PlanFulfillmentArgs,
            plan_fulfillment,
        ),
        _spec(
            "run_scenario",
            "Stress-test a plan with a disruption (demand shock, supplier outage, price, capacity, "
            "lead time, warehouse capacity, transport cost) and compare baseline, disrupted and "
            "re-optimized outcomes.",
            RunScenarioArgs,
            run_scenario_tool,
        ),
        _spec(
            "prepare_purchase_order",
            "Turn a feasible plan into a recommendation and open a human approval request. "
            "Nothing is ordered until approvers approve.",
            PreparePurchaseOrderArgs,
            prepare_purchase_order,
            roles=PO_ROLES,
            consequential=True,
        ),
    ]
    return {s.name: s for s in specs}

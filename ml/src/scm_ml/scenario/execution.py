from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from scm_common.domain import PurchaseLine, Scenario
from scm_ml.optimization import (
    AllocationParams,
    AllocationPlan,
    AllocationProblem,
    CellKey,
    ProcurementPlan,
    ProcurementProblem,
    Violation,
    ViolationKind,
    build_problem,
    evaluate_plan,
    regional_demand,
    serving_warehouse,
    solve_allocation,
    solve_procurement,
    stock_after_procurement,
)

from .inputs import AssumptionChange, PlanningInputs, apply_scenario


@dataclass(frozen=True)
class DecisionResult:
    problem: ProcurementProblem
    procurement: ProcurementPlan
    allocation_problem: AllocationProblem
    allocation: AllocationPlan


@dataclass(frozen=True)
class ScenarioRun:
    scenario: Scenario
    changes: tuple[AssumptionChange, ...]
    baseline: DecisionResult
    disrupted: DecisionResult
    response: DecisionResult
    commitment_violations: tuple[Violation, ...]
    """What is wrong with the baseline purchase commitments once the disruption hits."""


def procurement_problem(inputs: PlanningInputs) -> ProcurementProblem:
    primary = serving_warehouse(inputs.lanes)
    demand: dict[CellKey, float] = defaultdict(float)
    for (sku_id, region_id), value in inputs.regional_demand.items():
        demand[CellKey(sku_id, primary[region_id])] += value
    return build_problem(
        inputs.catalog, list(inputs.inventory), demand, inputs.as_of, inputs.params
    )


def _allocation_problem(
    inputs: PlanningInputs, problem: ProcurementProblem, lines: list[PurchaseLine]
) -> AllocationProblem:
    return AllocationProblem(
        skus=inputs.catalog.skus,
        lanes=inputs.lanes,
        stock=stock_after_procurement(problem, lines),
        demand=regional_demand(inputs.regional_demand),
        params=AllocationParams(service_level_target=inputs.params.service_level_target),
    )


def run_pipeline(inputs: PlanningInputs) -> DecisionResult:
    problem = procurement_problem(inputs)
    procurement = solve_procurement(problem)
    allocation_problem = _allocation_problem(inputs, problem, list(procurement.lines))
    return DecisionResult(
        problem, procurement, allocation_problem, solve_allocation(allocation_problem)
    )


def realize_deliveries(
    problem: ProcurementProblem, lines: tuple[PurchaseLine, ...]
) -> list[PurchaseLine]:
    offers = {
        (o.supplier_id, o.sku_id, key.warehouse_id): o
        for key, offs in problem.offers.items()
        for o in offs
    }
    ordered: dict[tuple[str, str], int] = defaultdict(int)
    for line in lines:
        if (line.supplier_id, line.sku_id, line.warehouse_id) in offers:
            ordered[(line.supplier_id, line.sku_id)] += line.quantity
    realized: list[PurchaseLine] = []
    for line in lines:
        offer = offers.get((line.supplier_id, line.sku_id, line.warehouse_id))
        if offer is None:
            continue
        capacity = offer.capacity_per_week * problem.params.horizon_weeks
        total = ordered[(line.supplier_id, line.sku_id)]
        share = min(1.0, capacity / total)
        quantity = int(line.quantity * share)
        if quantity >= 1:
            realized.append(
                PurchaseLine(
                    supplier_id=line.supplier_id,
                    sku_id=line.sku_id,
                    warehouse_id=line.warehouse_id,
                    quantity=quantity,
                    unit_price=offer.unit_price,
                    shipping_cost=round(
                        offer.shipping_cost_per_unit[line.warehouse_id] * quantity, 4
                    ),
                )
            )
    return realized


def execute_fixed_plan(inputs: PlanningInputs, lines: tuple[PurchaseLine, ...]) -> DecisionResult:
    problem = procurement_problem(inputs)
    started = time.perf_counter()
    realized = realize_deliveries(problem, lines)
    procurement = ProcurementPlan(
        method="baseline_plan_held",
        solver_status="NOT_RESOLVED",
        lines=tuple(realized),
        metrics=evaluate_plan(problem, realized),
        runtime_seconds=time.perf_counter() - started,
    )
    allocation_problem = _allocation_problem(inputs, problem, realized)
    return DecisionResult(
        problem, procurement, allocation_problem, solve_allocation(allocation_problem)
    )


def run_scenario(
    baseline_inputs: PlanningInputs,
    scenario: Scenario,
    baseline: DecisionResult | None = None,
) -> ScenarioRun:
    baseline = baseline or run_pipeline(baseline_inputs)
    applied = apply_scenario(baseline_inputs, scenario)
    disrupted_problem = procurement_problem(applied.inputs)
    return ScenarioRun(
        scenario=scenario,
        changes=applied.changes,
        baseline=baseline,
        disrupted=execute_fixed_plan(applied.inputs, baseline.procurement.lines),
        response=run_pipeline(applied.inputs),
        commitment_violations=tuple(
            v
            for v in evaluate_plan(disrupted_problem, baseline.procurement.lines).violations
            if v.kind is not ViolationKind.SERVICE_LEVEL  # service is measured on deliveries
        ),
    )

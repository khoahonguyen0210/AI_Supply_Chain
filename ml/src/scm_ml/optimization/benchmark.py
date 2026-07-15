"""Optimization benchmark: constraint optimization versus simple heuristics, on forecast demand.

Every number in the output is measured by `evaluate_plan` / `evaluate_allocation`, which recompute
cost, service and constraint violations from the plan itself, so heuristics and the optimizer are
judged by the same rules. Runtimes are wall-clock on the machine that ran the benchmark.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

from scm_common.domain import FulfillmentLane, PurchaseLine
from scm_ml.forecast.artifacts import provenance, write_json
from scm_ml.forecast.panel import panel_from_world
from scm_ml.service.contracts import ForecastRequest
from scm_ml.service.forecasting import ForecastService
from scm_ml.sourcing import SourcingCatalog
from scm_ml.synthetic import SyntheticWorld

from .allocation import (
    AllocationParams,
    AllocationProblem,
    evaluate_allocation,
    nearest_warehouse_rule,
    regional_demand,
    solve_allocation,
    stock_after_procurement,
)
from .evaluate import PlanMetrics, evaluate_plan
from .heuristics import SupplierChoice, reorder_up_to
from .problem import CellKey, ProcurementParams, ProcurementProblem, problem_from_world
from .procurement import solve_procurement

EXPERIMENT_PATH = Path("ml/experiments/optimization/synthetic.json")
BENCHMARK_VERSION = "1"
TIGHT_BUDGET_FRACTION = 0.85
"""The tight-budget case allows this fraction of what the unconstrained optimum spends."""


def forecast_regional_demand(
    service: ForecastService, world: SyntheticWorld, horizon_weeks: int
) -> dict[tuple[str, str], float]:
    """Point forecast summed over the planning horizon, per (SKU, region) with a demand series."""
    demand: dict[tuple[str, str], float] = {}
    for sku_id, region_id in service.history.series:
        response = service.forecast(
            ForecastRequest(
                sku_id=sku_id,
                region_id=region_id,
                as_of=world.as_of,
                horizon_weeks=horizon_weeks,
            )
        )
        demand[(sku_id, region_id)] = sum(point.point for point in response.points)
    return demand


def serving_warehouse(lanes: Sequence[FulfillmentLane]) -> dict[str, str]:
    """Each region's primary warehouse: its cheapest lane (ties broken by warehouse id)."""
    best: dict[str, FulfillmentLane] = {}
    for lane in lanes:
        current = best.get(lane.region_id)
        if current is None or (lane.cost_per_unit, lane.warehouse_id) < (
            current.cost_per_unit,
            current.warehouse_id,
        ):
            best[lane.region_id] = lane
    return {region: lane.warehouse_id for region, lane in best.items()}


def warehouse_demand(
    regional: Mapping[tuple[str, str], float], lanes: Sequence[FulfillmentLane]
) -> dict[CellKey, float]:
    primary = serving_warehouse(lanes)
    totals: dict[CellKey, float] = defaultdict(float)
    for (sku_id, region_id), value in regional.items():
        totals[CellKey(sku_id, primary[region_id])] += value
    return dict(totals)


def _summarise(metrics: PlanMetrics) -> dict[str, Any]:
    kinds = Counter(v.kind.value for v in metrics.violations)
    return {
        "objective": metrics.objective,
        "cost": metrics.cost.model_dump(),
        "spend": metrics.spend,
        "fill_rate": metrics.fill_rate,
        "unmet_demand": metrics.unmet_demand,
        "orders": metrics.orders,
        "units_ordered": metrics.units_ordered,
        "constraint_violations": {"count": len(metrics.violations), "by_kind": dict(kinds)},
    }


def _timed(build: Callable[[], list[PurchaseLine]]) -> tuple[list[PurchaseLine], float]:
    started = time.perf_counter()
    lines = build()
    return lines, time.perf_counter() - started


def _allocation_rows(
    problem: ProcurementProblem,
    lines: Sequence[PurchaseLine],
    regional: Mapping[tuple[str, str], float],
    world: SyntheticWorld,
) -> dict[str, Any]:
    allocation = AllocationProblem(
        skus={s.sku_id: s for s in world.skus},
        lanes=tuple(world.lanes),
        stock=stock_after_procurement(problem, lines),
        demand=regional_demand(regional),
        params=AllocationParams(service_level_target=problem.params.service_level_target),
    )
    started = time.perf_counter()
    rule_plan = nearest_warehouse_rule(allocation)
    rule_runtime = time.perf_counter() - started
    rule = evaluate_allocation(allocation, rule_plan)
    optimized = solve_allocation(allocation)
    rows: dict[str, Any] = {}
    for name, metrics, runtime in (
        ("nearest_warehouse_rule", rule, rule_runtime),
        ("milp", optimized.metrics, optimized.runtime_seconds),
    ):
        rows[name] = {
            "objective": metrics.objective,
            "shipping_cost": metrics.shipping_cost,
            "stockout_penalty": metrics.stockout_penalty,
            "fill_rate": metrics.fill_rate,
            "unmet_units": metrics.unmet_units,
            "mean_transit_days": metrics.mean_transit_days,
            "constraint_violations": {
                "count": len(metrics.violations),
                "by_kind": dict(Counter(v.kind.value for v in metrics.violations)),
            },
            "runtime_seconds": runtime,
        }
    return rows


def _run_case(
    problem: ProcurementProblem,
    catalog: SourcingCatalog,
    regional: Mapping[tuple[str, str], float],
    world: SyntheticWorld,
) -> dict[str, Any]:
    plans: dict[str, tuple[list[PurchaseLine], float, dict[str, Any] | None]] = {}
    for choice in SupplierChoice:
        lines, runtime = _timed(partial(reorder_up_to, problem, catalog, choice))
        plans[f"heuristic_{choice.value}"] = (lines, runtime, None)
    solved = solve_procurement(problem)
    plans["milp"] = (
        list(solved.lines),
        solved.runtime_seconds,
        {"solver_status": solved.solver_status, "mip_gap": solved.mip_gap},
    )
    result: dict[str, Any] = {}
    for name, (lines, runtime, extra) in plans.items():
        entry = _summarise(evaluate_plan(problem, lines))
        entry["runtime_seconds"] = runtime
        if extra:
            entry.update(extra)
        entry["allocation"] = _allocation_rows(problem, lines, regional, world)
        result[name] = entry
    return result


def run_benchmark(
    world: SyntheticWorld,
    service: ForecastService,
    params: ProcurementParams | None = None,
    out_path: Path | None = EXPERIMENT_PATH,
) -> dict[str, Any]:
    params = params or ProcurementParams()
    regional = forecast_regional_demand(service, world, params.horizon_weeks)
    demand = warehouse_demand(regional, world.lanes)
    catalog = SourcingCatalog.from_world(world)
    base = problem_from_world(world, demand, params)
    cases: dict[str, Any] = {"base": _run_case(base, catalog, regional, world)}
    budget = cases["base"]["milp"]["spend"] * TIGHT_BUDGET_FRACTION
    tight = replace(base, params=replace(params, budget=budget))
    cases["tight_budget"] = _run_case(tight, catalog, regional, world)
    cases["tight_budget"]["budget"] = budget

    result: dict[str, Any] = {
        "benchmark_version": BENCHMARK_VERSION,
        "dataset_id": service.history.dataset_id,
        "forecast_model_version": service.model.version,
        "as_of": world.as_of.isoformat(),
        "demand_source": "lightgbm point forecast summed over the planning horizon",
        "procurement_params": {k: getattr(params, k) for k in params.__dataclass_fields__},
        "tight_budget_fraction": TIGHT_BUDGET_FRACTION,
        "total_forecast_demand_units": sum(demand.values()),
        "cases": cases,
        "provenance": provenance(),
    }
    if out_path is not None:
        write_json(out_path, result)
    return result


def forecast_artifact_dirs(world: SyntheticWorld, root: Path) -> tuple[Path, Path]:
    """Locate the trained model and dataset for this world's demand panel."""
    base = root / panel_from_world(world).dataset_id
    model_dir, dataset_dir = base / "model", base / "dataset"
    if not model_dir.is_dir() or not dataset_dir.is_dir():
        raise FileNotFoundError(
            f"no trained forecast model under {base}; run `uv run python -m scm_ml.forecast` first"
        )
    return model_dir, dataset_dir

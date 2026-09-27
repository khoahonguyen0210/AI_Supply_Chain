from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from scm_ml.forecast.artifacts import provenance, write_json
from scm_ml.forecast.panel import panel_from_world
from scm_ml.optimization import (
    CellKey,
    ProcurementParams,
    problem_from_world,
    solve_procurement,
    warehouse_demand,
)
from scm_ml.service.contracts import ForecastRequest
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld
from scm_ml.synthetic.generator import generate_world_with_future, outcome_rng

from .actuals import (
    SIMULATED,
    CellWeek,
    future_weeks,
    receipts_by_week,
    simulate_deliveries,
    simulate_demand,
    simulate_inventory,
    warehouse_week_demand,
)
from .evaluation import (
    DeliveryOutcome,
    ForecastOutcome,
    InventoryWeek,
    compare_inventory,
    delivery_performance,
    forecast_accuracy,
    inventory_outcome,
)

EXPERIMENT_PATH = Path("ml/experiments/feedback/synthetic.json")
OUTCOME_DIR = Path("data/outcomes/synthetic")
FORECAST_WEEKS = 8
BASELINE_WEEKS = 13
EXPERIMENT_VERSION = "1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _forecasts(
    service: ForecastService, world: SyntheticWorld, actual: pd.DataFrame, horizons: int
) -> tuple[list[ForecastOutcome], list[ForecastOutcome], dict[tuple[str, str, Any], float]]:
    truth = {
        (sku, region, week): float(quantity)
        for sku, region, week, quantity in zip(
            actual["sku_id"],
            actual["region_id"],
            actual["week_start"],
            actual["quantity"],
            strict=True,
        )
    }
    history = service.history
    origin = history.week_index(world.as_of)
    model_rows: list[ForecastOutcome] = []
    baseline_rows: list[ForecastOutcome] = []
    points: dict[tuple[str, str, Any], float] = {}
    for index, (sku_id, region_id) in enumerate(history.series):
        response = service.forecast(
            ForecastRequest(
                sku_id=sku_id, region_id=region_id, as_of=world.as_of, horizon_weeks=horizons
            )
        )
        average = float(history.values[index, origin - BASELINE_WEEKS : origin].mean())
        for p in response.points:
            observed = truth[(sku_id, region_id, p.week_start)]
            points[(sku_id, region_id, p.week_start)] = p.point
            model_rows.append(
                ForecastOutcome(
                    sku_id, region_id, p.week_start, p.horizon, p.point, p.lower, p.upper, observed
                )
            )
            baseline_rows.append(
                ForecastOutcome(
                    sku_id, region_id, p.week_start, p.horizon, average, None, None, observed
                )
            )
    return model_rows, baseline_rows, points


def run_feedback_experiment(
    service: ForecastService,
    cfg: SyntheticConfig | None = None,
    params: ProcurementParams | None = None,
    out_dir: Path | None = OUTCOME_DIR,
    experiment_path: Path | None = EXPERIMENT_PATH,
) -> dict[str, Any]:
    cfg = cfg or SyntheticConfig()
    params = params or ProcurementParams()
    world, future = generate_world_with_future(cfg)
    if service.history.dataset_id != panel_from_world(world).dataset_id:
        # Replay with the model that existed at as_of; a later one has seen the actuals.
        raise ValueError("the forecast model must be the one trained on this world's history")
    rng = outcome_rng(cfg)
    weeks = future_weeks(world, FORECAST_WEEKS)
    plan_weeks = weeks[: params.horizon_weeks]

    # 1. what demand turned out to be (drawn first, so it does not depend on the decision)
    actual_demand = simulate_demand(world, future, rng, FORECAST_WEEKS)

    # 2. the forecast the decision relied on, and a naive reference
    model_rows, baseline_rows, points = _forecasts(service, world, actual_demand, FORECAST_WEEKS)

    # 3. the decision: the procurement plan over the plan horizon, from the same forecast
    regional = {
        (sku_id, region_id): sum(points[(sku_id, region_id, w)] for w in plan_weeks)
        for sku_id, region_id in service.history.series
    }
    problem = problem_from_world(world, warehouse_demand(regional, world.lanes), params)
    plan = solve_procurement(problem)

    # 4. what the suppliers did: open orders as already drawn, new orders simulated
    reliability = {s.supplier_id: s.reliability for s in world.suppliers}
    open_orders = [po for po in world.purchase_orders if po.delivered_at is None]
    open_actual = [
        DeliveryOutcome(
            po.po_id,
            po.supplier_id,
            po.quantity,
            po.expected_delivery,
            *future.pending_deliveries[po.po_id],
        )
        for po in open_orders
    ]
    placed: list[DeliveryOutcome] = []
    destination = {po.po_id: (po.sku_id, po.warehouse_id) for po in open_orders}
    for n, line in enumerate(plan.lines, start=1):
        offer = next(
            o
            for o in problem.offers[CellKey(line.sku_id, line.warehouse_id)]
            if o.supplier_id == line.supplier_id
        )
        po_id = f"PLAN-PO-{n:03d}"
        destination[po_id] = (line.sku_id, line.warehouse_id)
        placed.append(
            DeliveryOutcome(
                po_id,
                line.supplier_id,
                line.quantity,
                world.as_of + timedelta(days=offer.lead_time_days),
            )
        )
    placed_actual = simulate_deliveries(placed, reliability, rng)
    every_order = open_actual + placed_actual

    # 5. inventory over the plan horizon, as planned and as it happened
    forecast_demand = warehouse_week_demand(
        world, {k: v for k, v in points.items() if k[2] in plan_weeks}
    )
    actual_cells: dict[CellWeek, float] = {
        (sku, region, week): float(quantity)
        for sku, region, week, quantity in zip(
            actual_demand["sku_id"],
            actual_demand["region_id"],
            actual_demand["week_start"],
            actual_demand["quantity"],
            strict=True,
        )
        if week in plan_weeks
    }
    planned_path = simulate_inventory(
        world,
        plan_weeks,
        forecast_demand,
        receipts_by_week(world, every_order, destination, plan_weeks, as_promised=True),
    )
    actual_path = simulate_inventory(
        world,
        plan_weeks,
        warehouse_week_demand(world, actual_cells),
        receipts_by_week(world, every_order, destination, plan_weeks, as_promised=False),
    )

    files = (
        _write_outcomes(out_dir, actual_demand, every_order, destination, actual_path)
        if out_dir is not None
        else {}
    )
    plan_units = sum(line.quantity for line in plan.lines)
    result: dict[str, Any] = {
        "experiment": "feedback-loop",
        "experiment_version": EXPERIMENT_VERSION,
        "actuals_source": SIMULATED,
        "note": (
            "Actuals are SIMULATED by continuing the synthetic world's generative process past "
            "as_of with the same seed; the approval of the plan is simulated (all lines approved)."
        ),
        "seed": cfg.seed,
        "as_of": world.as_of.isoformat(),
        "dataset_id": service.history.dataset_id,
        "forecast_model_version": service.model.version,
        "actuals": {
            "weeks": [weeks[0].isoformat(), weeks[-1].isoformat()],
            "demand_units": int(actual_demand["quantity"].sum()),
            "files_sha256": files,
        },
        "forecast": {
            "origin": world.as_of.isoformat(),
            "horizons": FORECAST_WEEKS,
            "series": len(service.history.series),
            "model": forecast_accuracy(model_rows),
            f"moving_average_{BASELINE_WEEKS}": forecast_accuracy(baseline_rows),
        },
        "decision": {
            "method": plan.method,
            "solver_status": plan.solver_status,
            "approval": "SIMULATED: every plan line treated as approved and placed at as_of",
            "horizon_weeks": params.horizon_weeks,
            "service_level_target": params.service_level_target,
            "purchase_orders": len(plan.lines),
            "units_ordered": plan_units,
            "spend": round(plan.metrics.spend, 2),
            "planned_fill_rate": round(plan.metrics.fill_rate, 4),
            "forecast_demand_units": round(plan.metrics.total_demand, 1),
            "actual_demand_units": round(sum(actual_cells.values()), 1),
        },
        "deliveries": {
            "plan_orders": delivery_performance(placed_actual, reliability),
            "open_at_as_of": delivery_performance(open_actual, reliability),
        },
        "inventory": {
            "weeks": [plan_weeks[0].isoformat(), plan_weeks[-1].isoformat()],
            "planned": inventory_outcome(planned_path),
            "actual": inventory_outcome(actual_path),
            "planned_vs_actual": compare_inventory(planned_path, actual_path),
        },
        "provenance": provenance(),
    }
    if experiment_path is not None:
        write_json(experiment_path, result)
    return result


def _write_outcomes(
    directory: Path,
    demand: pd.DataFrame,
    deliveries: list[DeliveryOutcome],
    destination: dict[str, tuple[str, str]],
    inventory: list[InventoryWeek],
) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    frames = {
        "demand_actuals.csv": demand.assign(
            week_start=[w.isoformat() for w in demand["week_start"]], source=SIMULATED
        ),
        "deliveries.csv": pd.DataFrame(
            [
                {
                    "po_id": d.po_id,
                    "supplier_id": d.supplier_id,
                    "sku_id": destination[d.po_id][0],
                    "warehouse_id": destination[d.po_id][1],
                    "ordered_quantity": d.ordered_quantity,
                    "expected_delivery": d.expected_delivery.isoformat(),
                    "delivered_on": d.delivered_on.isoformat() if d.delivered_on else "",
                    "delivered_quantity": d.delivered_quantity,
                    "source": SIMULATED,
                }
                for d in deliveries
            ]
        ),
        "inventory.csv": pd.DataFrame(
            [
                {
                    "sku_id": r.sku_id,
                    "warehouse_id": r.warehouse_id,
                    "week_start": r.week_start.isoformat(),
                    "on_hand": round(r.on_hand, 2),
                    "unmet_units": round(r.unmet, 2),
                    "demand": round(r.demand or 0.0, 2),
                    "source": SIMULATED,
                }
                for r in inventory
            ]
        ),
    }
    checksums: dict[str, str] = {}
    for name, frame in frames.items():
        frame.to_csv(directory / name, index=False, lineterminator="\n")
        checksums[name] = sha256_file(directory / name)
    (directory / "manifest.json").write_text(
        json.dumps({"source": SIMULATED, "files_sha256": checksums}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return checksums

"""Predicted or planned versus actual: forecast accuracy, supplier delivery, inventory outcome.

These functions are shared by the offline experiment (simulated actuals) and the engine endpoint
that evaluates outcomes recorded through the backend, so both are scored by the same rules.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from scm_ml.forecast.metrics import interval_metrics, point_metrics


@dataclass(frozen=True)
class ForecastOutcome:
    """One forecast point next to the demand that actually happened in its week."""

    sku_id: str
    region_id: str
    week_start: date
    horizon: int
    point: float
    lower: float | None  # interval bounds; None for point-only forecasts such as baselines
    upper: float | None
    actual: float


@dataclass(frozen=True)
class DeliveryOutcome:
    """A purchase order as promised and, once known, as delivered."""

    po_id: str
    supplier_id: str
    ordered_quantity: int
    expected_delivery: date
    delivered_on: date | None = None
    delivered_quantity: int | None = None

    @property
    def delivered(self) -> bool:
        return self.delivered_on is not None and self.delivered_quantity is not None


@dataclass(frozen=True)
class InventoryWeek:
    """End-of-week stock of one SKU at one warehouse. ``demand`` may be unknown (None)."""

    sku_id: str
    warehouse_id: str
    week_start: date
    on_hand: float
    unmet: float
    demand: float | None = None


def _rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _forecast_block(rows: Sequence[ForecastOutcome]) -> dict[str, Any]:
    actual = np.array([r.actual for r in rows], dtype=np.float64)
    point = np.array([r.point for r in rows], dtype=np.float64)
    metrics: dict[str, Any] = {k: _rounded(v) for k, v in point_metrics(actual, point).items()}
    if all(r.lower is not None and r.upper is not None for r in rows):
        lower = np.array([r.lower for r in rows], dtype=np.float64)
        upper = np.array([r.upper for r in rows], dtype=np.float64)
        metrics.update({k: _rounded(v) for k, v in interval_metrics(actual, lower, upper).items()})
    metrics["n"] = len(rows)
    metrics["actual_total"] = _rounded(float(actual.sum()), 2)
    metrics["forecast_total"] = _rounded(float(point.sum()), 2)
    return metrics


def forecast_accuracy(rows: Sequence[ForecastOutcome]) -> dict[str, Any]:
    """MAE, RMSE, bias, WAPE, MAPE (non-zero actuals) and, when every row has bounds, interval
    coverage and width; overall and by horizon."""
    if not rows:
        return {"overall": None, "by_horizon": {}}
    by_horizon: dict[int, list[ForecastOutcome]] = defaultdict(list)
    for row in rows:
        by_horizon[row.horizon].append(row)
    return {
        "overall": _forecast_block(rows),
        "by_horizon": {str(h): _forecast_block(by_horizon[h]) for h in sorted(by_horizon)},
    }


def _delivery_block(rows: Sequence[DeliveryOutcome]) -> dict[str, Any]:
    done = [r for r in rows if r.delivered]
    ordered = sum(r.ordered_quantity for r in done)
    delays = [
        (r.delivered_on - r.expected_delivery).days for r in done if r.delivered_on is not None
    ]
    on_time = sum(1 for d in delays if d <= 0)
    in_full = sum(1 for r in done if (r.delivered_quantity or 0) >= r.ordered_quantity)
    return {
        "orders": len(rows),
        "delivered": len(done),
        "pending": len(rows) - len(done),
        "on_time_rate": _rounded(on_time / len(done)) if done else None,
        "in_full_rate": _rounded(in_full / len(done)) if done else None,
        "unit_fill_rate": (
            _rounded(sum(r.delivered_quantity or 0 for r in done) / ordered) if ordered else None
        ),
        "mean_delay_days": _rounded(float(np.mean(delays))) if delays else None,
        "max_delay_days": max(delays) if delays else None,
    }


def delivery_performance(
    rows: Sequence[DeliveryOutcome], promised_reliability: Mapping[str, float] | None = None
) -> dict[str, Any]:
    """On-time, in-full and unit fill rate, delay; per supplier against its promised reliability.

    ``promised_reliability`` is the supplier's on-time probability the plan relied on. Orders not
    yet delivered are counted as pending and left out of the rates.
    """
    promised = promised_reliability or {}
    by_supplier: dict[str, list[DeliveryOutcome]] = defaultdict(list)
    for row in rows:
        by_supplier[row.supplier_id].append(row)
    suppliers: dict[str, Any] = {}
    for supplier_id in sorted(by_supplier):
        block = _delivery_block(by_supplier[supplier_id])
        reliability = promised.get(supplier_id)
        block["promised_on_time_rate"] = _rounded(reliability)
        block["on_time_gap"] = (
            _rounded(block["on_time_rate"] - reliability)
            if reliability is not None and block["on_time_rate"] is not None
            else None
        )
        suppliers[supplier_id] = block
    return {"overall": _delivery_block(rows), "by_supplier": suppliers}


def inventory_outcome(rows: Sequence[InventoryWeek]) -> dict[str, Any]:
    """Stockouts, unmet demand, fill rate (when demand is known) and ending stock."""
    if not rows:
        return {"cell_weeks": 0}
    known = [r for r in rows if r.demand is not None]
    demand = sum(r.demand or 0.0 for r in known)
    unmet_known = sum(r.unmet for r in known)
    last_week = max(r.week_start for r in rows)
    cells = {(r.sku_id, r.warehouse_id) for r in rows}
    stockout_cells = {(r.sku_id, r.warehouse_id) for r in rows if r.unmet > 0}
    return {
        "cells": len(cells),
        "cell_weeks": len(rows),
        "stockout_cell_weeks": sum(1 for r in rows if r.unmet > 0),
        "cells_with_stockout": len(stockout_cells),
        "unmet_units": _rounded(sum(r.unmet for r in rows), 2),
        "demand_units": _rounded(demand, 2) if known else None,
        "fill_rate": _rounded(1.0 - unmet_known / demand) if known and demand > 0 else None,
        "ending_week": last_week.isoformat(),
        "ending_on_hand_units": _rounded(
            sum(r.on_hand for r in rows if r.week_start == last_week), 2
        ),
    }


def compare_inventory(
    planned: Sequence[InventoryWeek], actual: Sequence[InventoryWeek]
) -> dict[str, Any]:
    """Planned versus actual stock path, matched per (SKU, warehouse, week)."""
    plan = {(r.sku_id, r.warehouse_id, r.week_start): r for r in planned}
    pairs = [
        (plan[k], r) for r in actual if (k := (r.sku_id, r.warehouse_id, r.week_start)) in plan
    ]
    if not pairs:
        return {"matched_cell_weeks": 0}
    last_week = max(a.week_start for _, a in pairs)
    ending = [(p.on_hand, a.on_hand) for p, a in pairs if a.week_start == last_week]
    errors = np.array([a - p for p, a in ending], dtype=np.float64)
    return {
        "matched_cell_weeks": len(pairs),
        "ending_on_hand_mae": _rounded(float(np.abs(errors).mean())),
        "ending_on_hand_bias": _rounded(float(errors.mean())),
        "unexpected_stockout_cell_weeks": sum(1 for p, a in pairs if a.unmet > 0 and p.unmet <= 0),
        "planned_stockout_cell_weeks": sum(1 for p, _ in pairs if p.unmet > 0),
        "actual_stockout_cell_weeks": sum(1 for _, a in pairs if a.unmet > 0),
    }

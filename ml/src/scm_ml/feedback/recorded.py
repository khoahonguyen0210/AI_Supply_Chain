from __future__ import annotations

from datetime import date
from typing import Any

from scm_ml.service.engine_contracts import OutcomeEvaluationRequest

from .evaluation import (
    DeliveryOutcome,
    ForecastOutcome,
    InventoryWeek,
    delivery_performance,
    forecast_accuracy,
    inventory_outcome,
)


def evaluate_recorded(request: OutcomeEvaluationRequest) -> dict[str, Any]:
    actual: dict[tuple[str, str, date], float] = {
        (d.sku_id, d.region_id, d.week_start): d.quantity for d in request.demand
    }
    matched = [
        ForecastOutcome(
            f.sku_id,
            f.region_id,
            f.week_start,
            f.horizon,
            f.point,
            f.lower,
            f.upper,
            actual[(f.sku_id, f.region_id, f.week_start)],
        )
        for f in request.forecasts
        if (f.sku_id, f.region_id, f.week_start) in actual
    ]
    deliveries = [
        DeliveryOutcome(
            d.po_id,
            d.supplier_id,
            d.ordered_quantity,
            d.expected_delivery,
            d.delivered_on,
            d.delivered_quantity,
        )
        for d in request.deliveries
    ]
    promised = {
        d.supplier_id: d.promised_reliability
        for d in request.deliveries
        if d.promised_reliability is not None
    }
    stock = [
        InventoryWeek(i.sku_id, i.warehouse_id, i.week_start, i.on_hand, i.unmet_units)
        for i in request.inventory
    ]
    return {
        "forecast": {
            **forecast_accuracy(matched),
            "points": len(request.forecasts),
            "awaiting_actuals": len(request.forecasts) - len(matched),
        },
        "deliveries": delivery_performance(deliveries, promised),
        "inventory": inventory_outcome(stock),
    }

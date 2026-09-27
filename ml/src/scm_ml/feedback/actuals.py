from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from scm_ml.optimization.demand import serving_warehouse
from scm_ml.synthetic import SyntheticWorld
from scm_ml.synthetic.demand import continue_demand
from scm_ml.synthetic.generator import HiddenFuture

from .evaluation import DeliveryOutcome, InventoryWeek

SIMULATED = "SIMULATED"
DEMAND_COLUMNS = ["sku_id", "region_id", "week_start", "quantity"]

CellWeek = tuple[str, str, date]


def future_weeks(world: SyntheticWorld, n_weeks: int) -> list[date]:
    return [world.as_of + timedelta(weeks=k) for k in range(n_weeks)]


def simulate_demand(
    world: SyntheticWorld, future: HiddenFuture, rng: np.random.Generator, n_weeks: int
) -> pd.DataFrame:
    first = world.config.n_weeks
    units = continue_demand(future.demand, rng, np.arange(first, first + n_weeks))
    weeks = future_weeks(world, n_weeks)
    rows = [
        (sku.sku_id, region.region_id, weeks[k], int(units[s, r, k]))
        for s, sku in enumerate(world.skus)
        for r, region in enumerate(world.regions)
        for k in range(n_weeks)
    ]
    return pd.DataFrame(rows, columns=DEMAND_COLUMNS)


def simulate_deliveries(
    orders: Sequence[DeliveryOutcome],
    reliability: Mapping[str, float],
    rng: np.random.Generator,
) -> list[DeliveryOutcome]:
    delivered: list[DeliveryOutcome] = []
    for order in orders:
        on_time = rng.random() < reliability[order.supplier_id]
        delay = 0 if on_time else int(rng.integers(1, 11))
        short = (not on_time) and rng.random() < 0.5
        quantity = (
            int(order.ordered_quantity * rng.uniform(0.7, 0.95))
            if short
            else order.ordered_quantity
        )
        delivered.append(
            DeliveryOutcome(
                po_id=order.po_id,
                supplier_id=order.supplier_id,
                ordered_quantity=order.ordered_quantity,
                expected_delivery=order.expected_delivery,
                delivered_on=order.expected_delivery + timedelta(days=delay),
                delivered_quantity=quantity,
            )
        )
    return delivered


def warehouse_week_demand(
    world: SyntheticWorld, regional: Mapping[CellWeek, float]
) -> dict[CellWeek, float]:
    serves = serving_warehouse(world.lanes)
    totals: dict[CellWeek, float] = defaultdict(float)
    for (sku_id, region_id, week), value in regional.items():
        totals[(sku_id, serves[region_id], week)] += value
    return dict(totals)


def receipts_by_week(
    world: SyntheticWorld,
    deliveries: Sequence[DeliveryOutcome],
    destination: Mapping[str, tuple[str, str]],
    weeks: Sequence[date],
    *,
    as_promised: bool,
) -> dict[CellWeek, float]:
    receipts: dict[CellWeek, float] = defaultdict(float)
    for d in deliveries:
        when = d.expected_delivery if as_promised else d.delivered_on
        quantity = d.ordered_quantity if as_promised else d.delivered_quantity
        if when is None or quantity is None:
            continue
        index = max(0, (when - world.as_of).days // 7)
        if index < len(weeks):
            sku_id, warehouse_id = destination[d.po_id]
            receipts[(sku_id, warehouse_id, weeks[index])] += quantity
    return dict(receipts)


def simulate_inventory(
    world: SyntheticWorld,
    weeks: Sequence[date],
    demand: Mapping[CellWeek, float],
    receipts: Mapping[CellWeek, float],
) -> list[InventoryWeek]:
    rows: list[InventoryWeek] = []
    for position in sorted(world.inventory, key=lambda p: (p.sku_id, p.warehouse_id)):
        stock = float(position.on_hand)
        for week in weeks:
            key = (position.sku_id, position.warehouse_id, week)
            wanted = demand.get(key, 0.0)
            available = stock + receipts.get(key, 0.0)
            served = min(available, wanted)
            stock = available - served
            rows.append(
                InventoryWeek(
                    sku_id=position.sku_id,
                    warehouse_id=position.warehouse_id,
                    week_start=week,
                    on_hand=stock,
                    unmet=wanted - served,
                    demand=wanted,
                )
            )
    return rows

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from scm_common.domain import FulfillmentLane

from .problem import CellKey


def serving_warehouse(lanes: Sequence[FulfillmentLane]) -> dict[str, str]:
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

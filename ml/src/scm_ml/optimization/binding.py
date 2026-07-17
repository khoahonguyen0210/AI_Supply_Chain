from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from scm_common.domain import DomainModel, PurchaseLine

from .allocation import AllocationProblem, Shipment
from .problem import CellKey, ProcurementProblem

BINDING_UTILIZATION = 0.999
"""A limit counts as binding once the plan uses at least this share of it."""


class BindingKind(StrEnum):
    SUPPLIER_CAPACITY = "SUPPLIER_CAPACITY"
    MOQ = "MOQ"
    ORDER_VALUE_LIMIT = "ORDER_VALUE_LIMIT"
    BUDGET = "BUDGET"
    WAREHOUSE_CAPACITY = "WAREHOUSE_CAPACITY"
    SERVICE_LEVEL = "SERVICE_LEVEL"
    WAREHOUSE_STOCK = "WAREHOUSE_STOCK"


class BindingConstraint(DomainModel):
    kind: BindingKind
    subject: str
    used: float
    limit: float = Field(ge=0)

    @property
    def utilization(self) -> float:
        return 1.0 if self.limit == 0 else self.used / self.limit


def _at_limit(used: float, limit: float) -> bool:
    return used > 0 and used >= BINDING_UTILIZATION * limit


def procurement_binding(
    problem: ProcurementProblem, lines: Sequence[PurchaseLine]
) -> list[BindingConstraint]:
    params = problem.params
    found: list[BindingConstraint] = []
    offers = {
        (o.supplier_id, o.sku_id, key.warehouse_id): o
        for key, offs in problem.offers.items()
        for o in offs
    }
    units: dict[tuple[str, str], int] = defaultdict(int)
    volume: dict[str, float] = defaultdict(float)
    received: dict[CellKey, float] = defaultdict(float)
    spend = 0.0
    for line in lines:
        offer = offers.get((line.supplier_id, line.sku_id, line.warehouse_id))
        if offer is None:
            continue
        label = f"{line.supplier_id}/{line.sku_id}->{line.warehouse_id}"
        units[(line.supplier_id, line.sku_id)] += line.quantity
        volume[line.warehouse_id] += problem.skus[line.sku_id].unit_volume * line.quantity
        received[CellKey(line.sku_id, line.warehouse_id)] += (
            problem.reliability(line.supplier_id) * line.quantity
        )
        spend += line.quantity * line.unit_price + line.shipping_cost + params.fixed_order_cost
        if line.quantity == offer.moq:
            found.append(
                BindingConstraint(
                    kind=BindingKind.MOQ, subject=label, used=line.quantity, limit=offer.moq
                )
            )
        limit = problem.order_limit.get(line.supplier_id)
        if limit is not None and _at_limit(line.quantity * line.unit_price, limit):
            found.append(
                BindingConstraint(
                    kind=BindingKind.ORDER_VALUE_LIMIT,
                    subject=label,
                    used=line.quantity * line.unit_price,
                    limit=limit,
                )
            )
    seen: set[tuple[str, str]] = set()
    for (supplier_id, sku_id, _), offer in sorted(offers.items()):
        if (supplier_id, sku_id) in seen:
            continue
        seen.add((supplier_id, sku_id))
        capacity = float(offer.capacity_per_week * params.horizon_weeks)
        if _at_limit(units[(supplier_id, sku_id)], capacity):
            found.append(
                BindingConstraint(
                    kind=BindingKind.SUPPLIER_CAPACITY,
                    subject=f"{supplier_id}/{sku_id}",
                    used=units[(supplier_id, sku_id)],
                    limit=capacity,
                )
            )
    if params.budget is not None and _at_limit(spend, params.budget):
        found.append(
            BindingConstraint(
                kind=BindingKind.BUDGET, subject="budget", used=spend, limit=params.budget
            )
        )
    for warehouse_id, warehouse in sorted(problem.warehouses.items()):
        stored = sum(
            problem.skus[k.sku_id].unit_volume * c.available
            for k, c in problem.cells.items()
            if k.warehouse_id == warehouse_id
        )
        used = stored + volume[warehouse_id]
        if volume[warehouse_id] > 0 and _at_limit(used, warehouse.capacity_units):
            found.append(
                BindingConstraint(
                    kind=BindingKind.WAREHOUSE_CAPACITY,
                    subject=warehouse_id,
                    used=used,
                    limit=warehouse.capacity_units,
                )
            )
    allowed = 1.0 - params.service_level_target
    for key, cell in problem.cells.items():
        unmet = max(0.0, cell.demand - cell.available - received[key])
        if allowed > 0 and unmet > 0 and _at_limit(unmet, allowed * cell.demand):
            found.append(
                BindingConstraint(
                    kind=BindingKind.SERVICE_LEVEL,
                    subject=f"{key.sku_id}@{key.warehouse_id}",
                    used=unmet,
                    limit=allowed * cell.demand,
                )
            )
    return found


def allocation_binding(
    problem: AllocationProblem, shipments: Sequence[Shipment]
) -> list[BindingConstraint]:
    shipped: dict[CellKey, int] = defaultdict(int)
    for shipment in shipments:
        shipped[CellKey(shipment.sku_id, shipment.warehouse_id)] += shipment.quantity
    return [
        BindingConstraint(
            kind=BindingKind.WAREHOUSE_STOCK,
            subject=f"{key.sku_id}@{key.warehouse_id}",
            used=units,
            limit=problem.stock.get(key, 0),
        )
        for key, units in sorted(shipped.items())
        if units >= problem.stock.get(key, 0) > 0
    ]

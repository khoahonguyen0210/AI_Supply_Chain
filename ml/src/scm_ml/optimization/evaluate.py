from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field, computed_field

from scm_common.domain import DomainModel, PurchaseLine

from .problem import CellKey, ProcurementProblem

TOLERANCE = 1e-6


class ViolationKind(StrEnum):
    UNUSABLE_OFFER = "UNUSABLE_OFFER"
    BELOW_MOQ = "BELOW_MOQ"
    SUPPLIER_CAPACITY = "SUPPLIER_CAPACITY"
    ORDER_VALUE_LIMIT = "ORDER_VALUE_LIMIT"
    BUDGET = "BUDGET"
    WAREHOUSE_CAPACITY = "WAREHOUSE_CAPACITY"
    SERVICE_LEVEL = "SERVICE_LEVEL"


class Violation(DomainModel):
    kind: ViolationKind
    subject: str = Field(description="What was violated, e.g. a supplier, warehouse or cell.")
    amount: float = Field(gt=0, description="By how much, in the constraint's own unit.")
    detail: str


class CostBreakdown(DomainModel):
    purchase: float = Field(ge=0)
    shipping: float = Field(ge=0)
    fixed_order: float = Field(ge=0)
    holding: float = Field(ge=0)
    stockout_penalty: float = Field(ge=0)
    safety_shortfall_penalty: float = Field(ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> float:
        return (
            self.purchase
            + self.shipping
            + self.fixed_order
            + self.holding
            + self.stockout_penalty
            + self.safety_shortfall_penalty
        )


class PlanMetrics(DomainModel):
    objective: float = Field(
        description="Total cost; lower is better. Excludes violation penalties."
    )
    cost: CostBreakdown
    spend: float = Field(ge=0, description="Purchase plus shipping plus fixed order cost.")
    total_demand: float = Field(ge=0)
    unmet_demand: float = Field(ge=0)
    fill_rate: float = Field(ge=0, le=1, description="1 - unmet demand / total demand.")
    orders: int = Field(ge=0)
    units_ordered: int = Field(ge=0)
    violations: tuple[Violation, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def feasible(self) -> bool:
        return not self.violations


def _line_key(line: PurchaseLine) -> CellKey:
    return CellKey(line.sku_id, line.warehouse_id)


def evaluate_plan(problem: ProcurementProblem, lines: Sequence[PurchaseLine]) -> PlanMetrics:
    params = problem.params
    violations: list[Violation] = []
    received: dict[CellKey, float] = defaultdict(float)  # reliability-derated arrivals
    per_offer_units: dict[tuple[str, str], int] = defaultdict(int)
    ordered_volume: dict[str, float] = defaultdict(float)
    purchase = shipping = 0.0

    for line in lines:
        key = _line_key(line)
        offer = next(
            (
                o
                for o in problem.offers.get(key, ())
                if o.supplier_id == line.supplier_id and o.sku_id == line.sku_id
            ),
            None,
        )
        label = f"{line.supplier_id}/{line.sku_id}->{line.warehouse_id}"
        if offer is None:
            violations.append(
                Violation(
                    kind=ViolationKind.UNUSABLE_OFFER,
                    subject=label,
                    amount=float(line.quantity),
                    detail="no valid, certified, contracted, in-lead-time offer for this route",
                )
            )
            continue
        purchase += line.quantity * line.unit_price
        shipping += line.shipping_cost
        received[key] += problem.reliability(line.supplier_id) * line.quantity
        per_offer_units[(offer.supplier_id, offer.sku_id)] += line.quantity
        ordered_volume[line.warehouse_id] += problem.skus[line.sku_id].unit_volume * line.quantity
        if line.quantity < offer.moq:
            violations.append(
                Violation(
                    kind=ViolationKind.BELOW_MOQ,
                    subject=label,
                    amount=float(offer.moq - line.quantity),
                    detail=f"ordered {line.quantity}, MOQ {offer.moq}",
                )
            )
        limit = problem.order_limit.get(line.supplier_id)
        value = line.quantity * line.unit_price
        if limit is not None and value > limit + TOLERANCE:
            violations.append(
                Violation(
                    kind=ViolationKind.ORDER_VALUE_LIMIT,
                    subject=label,
                    amount=value - limit,
                    detail=f"order value {value:.2f} over contract limit {limit:.2f}",
                )
            )

    offers_by_id = {o.offer_id: o for offs in problem.offers.values() for o in offs}
    seen: set[tuple[str, str]] = set()
    for offer in offers_by_id.values():
        pair = (offer.supplier_id, offer.sku_id)
        if pair in seen:
            continue
        seen.add(pair)
        capacity = offer.capacity_per_week * params.horizon_weeks
        if per_offer_units[pair] > capacity:
            violations.append(
                Violation(
                    kind=ViolationKind.SUPPLIER_CAPACITY,
                    subject=f"{pair[0]}/{pair[1]}",
                    amount=float(per_offer_units[pair] - capacity),
                    detail=f"ordered {per_offer_units[pair]}, capacity {capacity}",
                )
            )

    orders = len(lines)
    fixed = orders * params.fixed_order_cost
    spend = purchase + shipping + fixed
    if params.budget is not None and spend > params.budget + TOLERANCE:
        violations.append(
            Violation(
                kind=ViolationKind.BUDGET,
                subject="budget",
                amount=spend - params.budget,
                detail=f"spend {spend:.2f} over budget {params.budget:.2f}",
            )
        )

    for warehouse_id, warehouse in problem.warehouses.items():
        existing = sum(
            problem.skus[k.sku_id].unit_volume * c.available
            for k, c in problem.cells.items()
            if k.warehouse_id == warehouse_id
        )
        used = existing + ordered_volume[warehouse_id]
        if used > warehouse.capacity_units + TOLERANCE:
            violations.append(
                Violation(
                    kind=ViolationKind.WAREHOUSE_CAPACITY,
                    subject=warehouse_id,
                    amount=used - warehouse.capacity_units,
                    detail=f"volume {used:.1f} over capacity {warehouse.capacity_units:.1f}",
                )
            )

    holding = stockout = shortfall = 0.0
    total_demand = unmet_total = 0.0
    allowed_gap = 1.0 - params.service_level_target
    for key, cell in problem.cells.items():
        available = cell.available + received[key]
        unmet = max(0.0, cell.demand - available)
        short = max(0.0, cell.demand + cell.safety_stock - available)
        excess = max(0.0, available - cell.demand)
        holding += excess * problem.warehouses[key.warehouse_id].holding_cost_per_unit_week
        stockout += unmet * problem.stockout_penalty(key.sku_id)
        shortfall += short * problem.shortfall_penalty(key.sku_id)
        total_demand += cell.demand
        unmet_total += unmet
        excess_over_target = unmet - allowed_gap * cell.demand
        if excess_over_target > TOLERANCE:
            violations.append(
                Violation(
                    kind=ViolationKind.SERVICE_LEVEL,
                    subject=f"{key.sku_id}@{key.warehouse_id}",
                    amount=excess_over_target,
                    detail=f"unmet {unmet:.1f} of demand {cell.demand:.1f}, target fill "
                    f"{params.service_level_target:.0%}",
                )
            )

    cost = CostBreakdown(
        purchase=purchase,
        shipping=shipping,
        fixed_order=fixed,
        holding=holding * params.horizon_weeks,
        stockout_penalty=stockout,
        safety_shortfall_penalty=shortfall,
    )
    return PlanMetrics(
        objective=cost.total,
        cost=cost,
        spend=spend,
        total_demand=total_demand,
        unmet_demand=unmet_total,
        fill_rate=1.0 if total_demand == 0 else max(0.0, 1.0 - unmet_total / total_demand),
        orders=orders,
        units_ordered=sum(line.quantity for line in lines),
        violations=tuple(violations),
    )

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from pydantic import Field, computed_field
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from scm_common.domain import DomainModel, FulfillmentLane, PurchaseLine, Sku

from .evaluate import TOLERANCE
from .problem import SERVICE_VIOLATION_PENALTY, CellKey, ProcurementProblem
from .procurement import STATUS_NAMES


@dataclass(frozen=True)
class AllocationParams:
    service_level_target: float = 0.95
    stockout_penalty_multiplier: float = 1.0
    max_transit_days: int | None = None
    """Lanes slower than this are not used; None allows every lane."""
    time_limit_seconds: float = 30.0


@dataclass(frozen=True)
class AllocationProblem:
    skus: Mapping[str, Sku]
    lanes: tuple[FulfillmentLane, ...]
    stock: Mapping[CellKey, int]  # (sku, warehouse) -> units available to ship
    demand: Mapping[tuple[str, str], int]  # (sku, region) -> units demanded
    params: AllocationParams = field(default_factory=AllocationParams)

    def usable_lanes(self) -> list[FulfillmentLane]:
        limit = self.params.max_transit_days
        return [x for x in self.lanes if limit is None or x.transit_days <= limit]

    def stockout_penalty(self, sku_id: str) -> float:
        return self.skus[sku_id].unit_price * self.params.stockout_penalty_multiplier


class Shipment(DomainModel):
    sku_id: str
    warehouse_id: str
    region_id: str
    quantity: int = Field(ge=1)
    cost_per_unit: float = Field(ge=0)
    transit_days: int = Field(ge=0)


class AllocationViolationKind(StrEnum):
    STOCK_EXCEEDED = "STOCK_EXCEEDED"
    NO_LANE = "NO_LANE"
    TRANSIT_TOO_LONG = "TRANSIT_TOO_LONG"
    OVER_DEMAND = "OVER_DEMAND"
    SERVICE_LEVEL = "SERVICE_LEVEL"


class AllocationViolation(DomainModel):
    kind: AllocationViolationKind
    subject: str
    amount: float = Field(gt=0)
    detail: str


class AllocationMetrics(DomainModel):
    objective: float = Field(description="Shipping cost plus stockout penalty.")
    shipping_cost: float = Field(ge=0)
    stockout_penalty: float = Field(ge=0)
    total_demand: int = Field(ge=0)
    shipped_units: int = Field(ge=0)
    unmet_units: int = Field(ge=0)
    fill_rate: float = Field(ge=0, le=1)
    mean_transit_days: float = Field(ge=0, description="Quantity-weighted over shipped units.")
    violations: tuple[AllocationViolation, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def feasible(self) -> bool:
        return not self.violations


class AllocationPlan(DomainModel):
    method: str
    solver_status: str
    shipments: tuple[Shipment, ...]
    metrics: AllocationMetrics
    runtime_seconds: float = Field(ge=0)


def stock_after_procurement(
    problem: ProcurementProblem, lines: Sequence[PurchaseLine]
) -> dict[CellKey, int]:
    arrivals: dict[CellKey, float] = defaultdict(float)
    for line in lines:
        key = CellKey(line.sku_id, line.warehouse_id)
        if any(o.supplier_id == line.supplier_id for o in problem.offers.get(key, ())):
            arrivals[key] += problem.reliability(line.supplier_id) * line.quantity
    return {
        key: cell.available + int(math.floor(arrivals[key] + 1e-9))
        for key, cell in problem.cells.items()
    }


def regional_demand(demand: Mapping[tuple[str, str], float]) -> dict[tuple[str, str], int]:
    return {key: math.ceil(value - 1e-9) for key, value in demand.items() if value > 1e-9}


def evaluate_allocation(
    problem: AllocationProblem, shipments: Sequence[Shipment]
) -> AllocationMetrics:
    lanes = {(x.warehouse_id, x.region_id): x for x in problem.lanes}
    limit = problem.params.max_transit_days
    violations: list[AllocationViolation] = []
    shipped_from: dict[CellKey, int] = defaultdict(int)
    served: dict[tuple[str, str], int] = defaultdict(int)
    shipping = transit_weighted = 0.0
    for shipment in shipments:
        lane = lanes.get((shipment.warehouse_id, shipment.region_id))
        label = f"{shipment.sku_id}:{shipment.warehouse_id}->{shipment.region_id}"
        if lane is None:
            violations.append(
                AllocationViolation(
                    kind=AllocationViolationKind.NO_LANE,
                    subject=label,
                    amount=float(shipment.quantity),
                    detail="no fulfillment lane between warehouse and region",
                )
            )
            continue
        if limit is not None and lane.transit_days > limit:
            violations.append(
                AllocationViolation(
                    kind=AllocationViolationKind.TRANSIT_TOO_LONG,
                    subject=label,
                    amount=float(lane.transit_days - limit),
                    detail=f"transit {lane.transit_days}d over limit {limit}d",
                )
            )
        shipped_from[CellKey(shipment.sku_id, shipment.warehouse_id)] += shipment.quantity
        served[(shipment.sku_id, shipment.region_id)] += shipment.quantity
        shipping += lane.cost_per_unit * shipment.quantity
        transit_weighted += lane.transit_days * shipment.quantity

    for key, units in shipped_from.items():
        have = problem.stock.get(key, 0)
        if units > have:
            violations.append(
                AllocationViolation(
                    kind=AllocationViolationKind.STOCK_EXCEEDED,
                    subject=f"{key.sku_id}@{key.warehouse_id}",
                    amount=float(units - have),
                    detail=f"shipping {units}, stock {have}",
                )
            )
    for demand_key, units in served.items():
        wanted = problem.demand.get(demand_key, 0)
        if units > wanted:
            violations.append(
                AllocationViolation(
                    kind=AllocationViolationKind.OVER_DEMAND,
                    subject=f"{demand_key[0]}@{demand_key[1]}",
                    amount=float(units - wanted),
                    detail=f"shipping {units}, demand {wanted}",
                )
            )

    total = sum(problem.demand.values())
    unmet_total = 0
    penalty = 0.0
    allowed = 1.0 - problem.params.service_level_target
    for demand_key, wanted in problem.demand.items():
        unmet = max(0, wanted - served[demand_key])
        unmet_total += unmet
        penalty += unmet * problem.stockout_penalty(demand_key[0])
        if unmet - allowed * wanted > TOLERANCE:
            violations.append(
                AllocationViolation(
                    kind=AllocationViolationKind.SERVICE_LEVEL,
                    subject=f"{demand_key[0]}@{demand_key[1]}",
                    amount=unmet - allowed * wanted,
                    detail=f"unmet {unmet} of {wanted}, target fill "
                    f"{problem.params.service_level_target:.0%}",
                )
            )
    shipped = sum(s.quantity for s in shipments)
    return AllocationMetrics(
        objective=shipping + penalty,
        shipping_cost=shipping,
        stockout_penalty=penalty,
        total_demand=total,
        shipped_units=shipped,
        unmet_units=unmet_total,
        fill_rate=1.0 if total == 0 else 1.0 - unmet_total / total,
        mean_transit_days=0.0 if shipped == 0 else transit_weighted / shipped,
        violations=tuple(violations),
    )


def _shipment(lane: FulfillmentLane, sku_id: str, quantity: int) -> Shipment:
    return Shipment(
        sku_id=sku_id,
        warehouse_id=lane.warehouse_id,
        region_id=lane.region_id,
        quantity=quantity,
        cost_per_unit=lane.cost_per_unit,
        transit_days=lane.transit_days,
    )


def solve_allocation(problem: AllocationProblem) -> AllocationPlan:
    started = time.perf_counter()
    lanes = problem.usable_lanes()
    demand_keys = sorted(problem.demand)
    routes = [
        (sku_id, lane)
        for sku_id, region_id in demand_keys
        for lane in lanes
        if lane.region_id == region_id
    ]
    n_routes, n_demand = len(routes), len(demand_keys)
    u0, g0 = n_routes, n_routes + n_demand
    n_vars = g0 + n_demand
    demand_index = {key: i for i, key in enumerate(demand_keys)}

    cost = np.zeros(n_vars)
    upper = np.full(n_vars, np.inf)
    for i, (sku_id, lane) in enumerate(routes):
        cost[i] = lane.cost_per_unit
        upper[i] = problem.stock.get(CellKey(sku_id, lane.warehouse_id), 0)
    for key, i in demand_index.items():
        cost[u0 + i] = problem.stockout_penalty(key[0])
        cost[g0 + i] = SERVICE_VIOLATION_PENALTY
        upper[u0 + i] = problem.demand[key]

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    lo: list[float] = []
    hi: list[float] = []

    def add_row(entries: list[tuple[int, float]], low: float, high: float) -> None:
        row = len(lo)
        for col, val in entries:
            rows.append(row)
            cols.append(col)
            vals.append(val)
        lo.append(low)
        hi.append(high)

    by_demand: dict[int, list[int]] = defaultdict(list)
    by_stock: dict[CellKey, list[int]] = defaultdict(list)
    for i, (sku_id, lane) in enumerate(routes):
        by_demand[demand_index[(sku_id, lane.region_id)]].append(i)
        by_stock[CellKey(sku_id, lane.warehouse_id)].append(i)
    allowed = 1.0 - problem.params.service_level_target
    for key, d in demand_index.items():
        wanted = float(problem.demand[key])
        add_row([*((i, 1.0) for i in by_demand[d]), (u0 + d, 1.0)], wanted, wanted)
        add_row([(u0 + d, 1.0), (g0 + d, -1.0)], -np.inf, allowed * wanted)
    for stock_key, members in by_stock.items():
        add_row([(i, 1.0) for i in members], -np.inf, float(problem.stock.get(stock_key, 0)))

    matrix = coo_matrix((vals, (rows, cols)), shape=(len(lo), n_vars)).tocsr()
    result = milp(
        c=cost,
        constraints=LinearConstraint(matrix, np.array(lo), np.array(hi)),
        integrality=np.ones(n_vars),
        bounds=Bounds(np.zeros(n_vars), upper),
        options={"time_limit": problem.params.time_limit_seconds},
    )
    shipments: list[Shipment] = []
    if result.x is not None:
        for i, (sku_id, lane) in enumerate(routes):
            quantity = int(round(result.x[i]))
            if quantity >= 1:
                shipments.append(_shipment(lane, sku_id, quantity))
    return AllocationPlan(
        method="milp",
        solver_status=STATUS_NAMES.get(int(result.status), "ERROR"),
        shipments=tuple(shipments),
        metrics=evaluate_allocation(problem, shipments),
        runtime_seconds=time.perf_counter() - started,
    )


def nearest_warehouse_rule(problem: AllocationProblem) -> list[Shipment]:
    lanes_by_region: dict[str, list[FulfillmentLane]] = defaultdict(list)
    for lane in problem.usable_lanes():
        lanes_by_region[lane.region_id].append(lane)
    remaining = dict(problem.stock)
    shipments: list[Shipment] = []
    for sku_id, region_id in sorted(problem.demand, key=lambda k: (k[1], k[0])):
        need = problem.demand[(sku_id, region_id)]
        for lane in sorted(
            lanes_by_region[region_id], key=lambda x: (x.cost_per_unit, x.warehouse_id)
        ):
            if need <= 0:
                break
            key = CellKey(sku_id, lane.warehouse_id)
            quantity = min(need, remaining.get(key, 0))
            if quantity >= 1:
                remaining[key] -= quantity
                need -= quantity
                shipments.append(_shipment(lane, sku_id, quantity))
    return shipments

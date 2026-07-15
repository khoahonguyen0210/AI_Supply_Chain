"""Constraint-aware procurement optimization as a mixed-integer linear program (SciPy / HiGHS).

Decision variables, per usable (offer, warehouse) route r:
    x_r  integer units ordered            y_r  1 if a purchase order is placed

Per planning cell c (SKU at warehouse), A_c = on-hand + incoming, P_c = sum(reliability * x_r):
    u_c  unmet demand        s_c  shortfall below demand + safety stock
    e_c  excess over demand  g_c  service-level shortfall (elastic, heavily penalised)

Minimise  purchase + shipping + fixed order cost + holding + stockout + safety-shortfall penalties
          + SERVICE_VIOLATION_PENALTY * sum(g)
subject to
    u_c >= D_c - A_c - P_c        s_c >= D_c + SS_c - A_c - P_c        e_c >= A_c + P_c - D_c
    u_c - g_c <= (1 - service target) * D_c
    MOQ_r * y_r <= x_r <= max_units_r * y_r      (MOQ, supplier capacity, contract order limit)
    sum over warehouses of x_r <= weekly capacity * horizon      (per supplier offer)
    sum(price + shipping) * x + fixed * y <= budget
    sum(volume * x) at warehouse <= warehouse capacity - volume already stored

Lead time, validity, certification and contract status are handled by excluding unusable offers.
Physical and budget constraints are hard; only the service level is elastic so that an infeasible
target is reported as an explicit violation instead of an opaque solver failure.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from pydantic import Field
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from scm_common.domain import DomainModel, PurchaseLine, SupplierOffer

from .evaluate import PlanMetrics, evaluate_plan
from .problem import SERVICE_VIOLATION_PENALTY, CellKey, ProcurementProblem

STATUS_NAMES = {
    0: "OPTIMAL",
    1: "LIMIT_REACHED",
    2: "INFEASIBLE",
    3: "UNBOUNDED",
    4: "ERROR",
}


class ProcurementPlan(DomainModel):
    method: str
    solver_status: str
    lines: tuple[PurchaseLine, ...]
    metrics: PlanMetrics
    runtime_seconds: float = Field(ge=0)
    mip_gap: float | None = None
    solver_objective: float | None = Field(
        default=None, description="Objective the solver minimised, incl. service-violation penalty."
    )


@dataclass(frozen=True)
class _Route:
    key: CellKey
    offer: SupplierOffer
    max_units: int


def _routes(problem: ProcurementProblem) -> list[_Route]:
    routes: list[_Route] = []
    for key, offers in problem.offers.items():
        for offer in offers:
            max_units = problem.max_units(offer)
            if max_units >= offer.moq:
                routes.append(_Route(key, offer, max_units))
    return routes


def _line(problem: ProcurementProblem, route: _Route, quantity: int) -> PurchaseLine:
    return PurchaseLine(
        supplier_id=route.offer.supplier_id,
        sku_id=route.key.sku_id,
        warehouse_id=route.key.warehouse_id,
        quantity=quantity,
        unit_price=route.offer.unit_price,
        shipping_cost=round(
            route.offer.shipping_cost_per_unit[route.key.warehouse_id] * quantity, 4
        ),
    )


def solve_procurement(problem: ProcurementProblem) -> ProcurementPlan:
    started = time.perf_counter()
    params = problem.params
    routes = _routes(problem)
    cells = list(problem.cells)
    n_routes, n_cells = len(routes), len(cells)
    # variable layout: x[0:R] | y | u | s | e | g (one block of n_cells each)
    y0 = n_routes
    u0 = 2 * n_routes
    s0 = u0 + n_cells
    e0 = s0 + n_cells
    g0 = e0 + n_cells
    n_vars = g0 + n_cells
    cell_index = {key: i for i, key in enumerate(cells)}

    cost = np.zeros(n_vars)
    lower = np.zeros(n_vars)
    upper = np.full(n_vars, np.inf)
    integrality = np.zeros(n_vars)
    for r, route in enumerate(routes):
        shipping = route.offer.shipping_cost_per_unit[route.key.warehouse_id]
        cost[r] = route.offer.unit_price + shipping
        cost[y0 + r] = params.fixed_order_cost
        upper[r] = route.max_units
        upper[y0 + r] = 1.0
        integrality[r] = integrality[y0 + r] = 1
    for c, key in enumerate(cells):
        cost[u0 + c] = problem.stockout_penalty(key.sku_id)
        cost[s0 + c] = problem.shortfall_penalty(key.sku_id)
        cost[e0 + c] = (
            problem.warehouses[key.warehouse_id].holding_cost_per_unit_week * params.horizon_weeks
        )
        cost[g0 + c] = SERVICE_VIOLATION_PENALTY

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

    routes_by_cell: dict[int, list[int]] = defaultdict(list)
    routes_by_offer: dict[str, list[int]] = defaultdict(list)
    routes_by_warehouse: dict[str, list[int]] = defaultdict(list)
    for r, route in enumerate(routes):
        routes_by_cell[cell_index[route.key]].append(r)
        routes_by_offer[route.offer.offer_id].append(r)
        routes_by_warehouse[route.key.warehouse_id].append(r)

    for c, key in enumerate(cells):
        cell = problem.cells[key]
        arrivals = [
            (r, problem.reliability(routes[r].offer.supplier_id)) for r in routes_by_cell[c]
        ]
        add_row([(u0 + c, 1.0), *arrivals], cell.demand - cell.available, np.inf)
        add_row(
            [(s0 + c, 1.0), *arrivals],
            cell.demand + cell.safety_stock - cell.available,
            np.inf,
        )
        add_row(
            [(e0 + c, 1.0), *[(col, -w) for col, w in arrivals]],
            cell.available - cell.demand,
            np.inf,
        )
        add_row(
            [(u0 + c, 1.0), (g0 + c, -1.0)],
            -np.inf,
            (1.0 - params.service_level_target) * cell.demand,
        )
    for r, route in enumerate(routes):
        add_row([(r, 1.0), (y0 + r, -float(route.offer.moq))], 0.0, np.inf)
        add_row([(r, 1.0), (y0 + r, -float(route.max_units))], -np.inf, 0.0)
    for members in routes_by_offer.values():
        offer = routes[members[0]].offer
        add_row(
            [(r, 1.0) for r in members],
            -np.inf,
            float(offer.capacity_per_week * params.horizon_weeks),
        )
    if params.budget is not None:
        spend = [(r, cost[r]) for r in range(n_routes)]
        spend += [(y0 + r, params.fixed_order_cost) for r in range(n_routes)]
        add_row(spend, -np.inf, params.budget)
    for warehouse_id, members in routes_by_warehouse.items():
        stored = sum(
            problem.skus[k.sku_id].unit_volume * cell.available
            for k, cell in problem.cells.items()
            if k.warehouse_id == warehouse_id
        )
        room = max(problem.warehouses[warehouse_id].capacity_units - stored, 0.0)
        add_row(
            [(r, problem.skus[routes[r].key.sku_id].unit_volume) for r in members],
            -np.inf,
            room,
        )

    matrix = coo_matrix((vals, (rows, cols)), shape=(len(lo), n_vars)).tocsr()
    result = milp(
        c=cost,
        constraints=LinearConstraint(matrix, np.array(lo), np.array(hi)),
        integrality=integrality,
        bounds=Bounds(lower, upper),
        options={"time_limit": params.time_limit_seconds, "mip_rel_gap": params.mip_rel_gap},
    )
    runtime = time.perf_counter() - started
    status = STATUS_NAMES.get(int(result.status), "ERROR")

    lines: list[PurchaseLine] = []
    if result.x is not None:
        for r, route in enumerate(routes):
            quantity = int(round(result.x[r]))
            if quantity >= 1:
                lines.append(_line(problem, route, quantity))
    return ProcurementPlan(
        method="milp",
        solver_status=status,
        lines=tuple(lines),
        metrics=evaluate_plan(problem, lines),
        runtime_seconds=runtime,
        mip_gap=None if result.x is None else float(getattr(result, "mip_gap", 0.0) or 0.0),
        solver_objective=None if result.x is None else float(result.fun),
    )

from collections import defaultdict

import pytest

from scm_common.domain import FulfillmentLane, Sku
from scm_ml.optimization import (
    AllocationParams,
    AllocationProblem,
    AllocationViolationKind,
    CellKey,
    ProcurementParams,
    Shipment,
    evaluate_allocation,
    nearest_warehouse_rule,
    problem_from_world,
    regional_demand,
    solve_allocation,
    solve_procurement,
    stock_after_procurement,
)
from scm_ml.synthetic import SyntheticConfig, generate_world

SKU = Sku(sku_id="S1", name="W", category="c", unit_price=10.0, unit_volume=1.0)


def _lane(warehouse: str, region: str, cost: float, days: int = 2) -> FulfillmentLane:
    return FulfillmentLane(
        warehouse_id=warehouse, region_id=region, cost_per_unit=cost, transit_days=days
    )


def _problem(
    stock: dict[str, int],
    demand: dict[str, int],
    lanes: list[FulfillmentLane],
    **params: object,
) -> AllocationProblem:
    return AllocationProblem(
        skus={"S1": SKU},
        lanes=tuple(lanes),
        stock={CellKey("S1", w): q for w, q in stock.items()},
        demand={("S1", r): q for r, q in demand.items()},
        params=AllocationParams(**params),  # type: ignore[arg-type]
    )


def _shipped(plan_shipments: tuple[Shipment, ...], warehouse: str, region: str) -> int:
    return sum(
        s.quantity for s in plan_shipments if s.warehouse_id == warehouse and s.region_id == region
    )


def test_ships_from_the_cheapest_lane_and_fills_demand() -> None:
    lanes = [_lane("W1", "R1", 1.0), _lane("W2", "R1", 3.0)]
    plan = solve_allocation(_problem({"W1": 100, "W2": 100}, {"R1": 80}, lanes))
    assert plan.solver_status == "OPTIMAL"
    assert _shipped(plan.shipments, "W1", "R1") == 80
    assert plan.metrics.fill_rate == 1.0 and plan.metrics.feasible
    assert plan.metrics.shipping_cost == pytest.approx(80.0)


def test_stock_limit_forces_the_second_warehouse() -> None:
    lanes = [_lane("W1", "R1", 1.0), _lane("W2", "R1", 3.0)]
    plan = solve_allocation(_problem({"W1": 30, "W2": 100}, {"R1": 80}, lanes))
    assert _shipped(plan.shipments, "W1", "R1") == 30
    assert _shipped(plan.shipments, "W2", "R1") == 50


def test_optimizer_beats_first_come_first_served() -> None:
    # W1 is cheapest for both regions but can only cover one; R2 has no other cheap option.
    lanes = [
        _lane("W1", "R1", 1.0),
        _lane("W2", "R1", 2.0),
        _lane("W1", "R2", 1.0),
        _lane("W2", "R2", 9.0),
    ]
    problem = _problem({"W1": 50, "W2": 50}, {"R1": 50, "R2": 50}, lanes)
    rule = evaluate_allocation(problem, nearest_warehouse_rule(problem))
    best = solve_allocation(problem).metrics
    # R1 is served first and drains W1, leaving R2 the 9.0 lane: 50*1 + 50*9 = 500.
    # Optimal sends R1 from W2 (2.0) and R2 from W1 (1.0): 50*2 + 50*1 = 150.
    assert rule.objective == pytest.approx(500.0)
    assert best.objective == pytest.approx(150.0)
    assert best.fill_rate == 1.0 and rule.fill_rate == 1.0


def test_shortage_is_measured_and_service_gap_reported() -> None:
    plan = solve_allocation(_problem({"W1": 40}, {"R1": 100}, [_lane("W1", "R1", 1.0)]))
    assert plan.metrics.unmet_units == 60
    assert plan.metrics.fill_rate == pytest.approx(0.4)
    assert plan.metrics.stockout_penalty == pytest.approx(600.0)
    assert {v.kind for v in plan.metrics.violations} == {AllocationViolationKind.SERVICE_LEVEL}


def test_transit_limit_excludes_slow_lanes() -> None:
    lanes = [_lane("W1", "R1", 1.0, days=6), _lane("W2", "R1", 5.0, days=2)]
    plan = solve_allocation(_problem({"W1": 100, "W2": 100}, {"R1": 50}, lanes, max_transit_days=3))
    assert _shipped(plan.shipments, "W1", "R1") == 0
    assert _shipped(plan.shipments, "W2", "R1") == 50
    assert plan.metrics.mean_transit_days == 2.0


def test_evaluator_flags_infeasible_hand_made_allocations() -> None:
    problem = _problem({"W1": 10}, {"R1": 20}, [_lane("W1", "R1", 1.0, days=5)], max_transit_days=3)
    over = Shipment(
        sku_id="S1",
        warehouse_id="W1",
        region_id="R1",
        quantity=30,
        cost_per_unit=1.0,
        transit_days=5,
    )
    ghost = Shipment(
        sku_id="S1",
        warehouse_id="W9",
        region_id="R1",
        quantity=1,
        cost_per_unit=1.0,
        transit_days=1,
    )
    kinds = {v.kind for v in evaluate_allocation(problem, [over, ghost]).violations}
    assert kinds >= {
        AllocationViolationKind.STOCK_EXCEEDED,
        AllocationViolationKind.TRANSIT_TOO_LONG,
        AllocationViolationKind.OVER_DEMAND,
        AllocationViolationKind.NO_LANE,
    }


def test_regional_demand_rounds_up_and_drops_zero() -> None:
    assert regional_demand({("S1", "R1"): 10.2, ("S1", "R2"): 0.0, ("S1", "R3"): 5.0}) == {
        ("S1", "R1"): 11,
        ("S1", "R3"): 5,
    }


def test_pipeline_from_procurement_to_allocation_on_the_world() -> None:
    world = generate_world(SyntheticConfig())
    region_weight: dict[tuple[str, str], float] = defaultdict(float)
    for order in world.sales_orders:
        region_weight[(order.sku_id, order.region_id)] += order.quantity
    weeks = world.config.n_weeks
    regional = {key: total / weeks * 4 for key, total in region_weight.items()}
    nearest: dict[str, FulfillmentLane] = {}
    for lane in world.lanes:
        current = nearest.get(lane.region_id)
        if current is None or lane.cost_per_unit < current.cost_per_unit:
            nearest[lane.region_id] = lane
    warehouse_demand: dict[CellKey, float] = defaultdict(float)
    for (sku_id, region_id), value in regional.items():
        warehouse_demand[CellKey(sku_id, nearest[region_id].warehouse_id)] += value
    procurement = problem_from_world(world, warehouse_demand, ProcurementParams())
    plan = solve_procurement(procurement)
    problem = AllocationProblem(
        skus={s.sku_id: s for s in world.skus},
        lanes=tuple(world.lanes),
        stock=stock_after_procurement(procurement, plan.lines),
        demand=regional_demand(regional),
    )
    best = solve_allocation(problem)
    rule = evaluate_allocation(problem, nearest_warehouse_rule(problem))
    assert best.solver_status == "OPTIMAL"
    assert best.metrics.objective <= rule.objective + 1e-6
    assert best.metrics.fill_rate >= rule.fill_rate - 1e-9
    assert not [
        v for v in best.metrics.violations if v.kind is not AllocationViolationKind.SERVICE_LEVEL
    ]

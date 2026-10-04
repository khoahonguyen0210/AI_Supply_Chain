from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from scm_common.domain import (
    ContractStatus,
    InventoryPosition,
    PurchaseLine,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)
from scm_ml.optimization import (
    CellKey,
    ProcurementParams,
    ProcurementProblem,
    SupplierChoice,
    ViolationKind,
    build_problem,
    evaluate_plan,
    problem_from_world,
    reorder_up_to,
    solve_procurement,
)
from scm_ml.sourcing import SourcingCatalog
from scm_ml.synthetic import SyntheticConfig, generate_world

AS_OF = date(2025, 1, 6)
CELL = CellKey("SKU-1", "WH-1")


def _offer(sid: str, **overrides: Any) -> SupplierOffer:
    fields: dict[str, Any] = {
        "offer_id": f"O-{sid}",
        "supplier_id": sid,
        "sku_id": "SKU-1",
        "unit_price": 10.0,
        "moq": 10,
        "capacity_per_week": 1_000,
        "lead_time_days": 7,
        "shipping_cost_per_unit": {"WH-1": 0.0},
        "valid_from": AS_OF - timedelta(days=30),
        "valid_to": AS_OF + timedelta(days=60),
    }
    fields.update(overrides)
    return SupplierOffer(**fields)


def _problem(
    offers: list[SupplierOffer],
    *,
    demand: float = 100.0,
    on_hand: int = 0,
    safety: int = 0,
    params: ProcurementParams | None = None,
    reliability: float = 1.0,
    warehouse_capacity: float = 100_000.0,
    max_order_value: float | None = None,
    contract_status: ContractStatus = ContractStatus.ACTIVE,
    price: float = 40.0,
) -> ProcurementProblem:
    sku = Sku(sku_id="SKU-1", name="W", category="c", unit_price=price, unit_volume=1.0)
    supplier_ids = sorted({o.supplier_id for o in offers})
    suppliers = [
        Supplier(
            supplier_id=sid,
            name=sid,
            region_id="R1",
            reliability=reliability,
            quality_score=0.9,
        )
        for sid in supplier_ids
    ]
    contracts = [
        SupplierContract(
            contract_id=f"C-{sid}",
            supplier_id=sid,
            status=contract_status,
            effective_from=AS_OF - timedelta(days=100),
            effective_to=AS_OF + timedelta(days=100),
            payment_terms_days=30,
            max_order_value=max_order_value,
        )
        for sid in supplier_ids
    ]
    warehouse = Warehouse(
        warehouse_id="WH-1",
        name="W",
        region_id="R1",
        capacity_units=warehouse_capacity,
        holding_cost_per_unit_week=0.1,
    )
    catalog = SourcingCatalog.build([sku], suppliers, [warehouse], contracts, offers)
    inventory = [
        InventoryPosition(
            sku_id="SKU-1",
            warehouse_id="WH-1",
            as_of=datetime(2025, 1, 6, tzinfo=UTC),
            on_hand=on_hand,
            incoming=0,
            safety_stock=safety,
        )
    ]
    return build_problem(
        catalog,
        inventory,
        {CELL: demand},
        AS_OF,
        params or ProcurementParams(derate_by_reliability=False, fixed_order_cost=0.0),
    )


def _qty(plan_lines: tuple[PurchaseLine, ...], supplier: str) -> int:
    return sum(line.quantity for line in plan_lines if line.supplier_id == supplier)


def test_buys_exactly_the_demand_from_the_cheapest_supplier() -> None:
    problem = _problem([_offer("A"), _offer("B", unit_price=12.0)])
    plan = solve_procurement(problem)
    assert plan.solver_status == "OPTIMAL"
    assert _qty(plan.lines, "A") == 100 and _qty(plan.lines, "B") == 0
    assert plan.metrics.feasible and plan.metrics.fill_rate == 1.0


def test_stock_on_hand_is_used_before_buying() -> None:
    plan = solve_procurement(_problem([_offer("A")], on_hand=100))
    assert plan.lines == ()
    assert plan.metrics.fill_rate == 1.0


def test_safety_stock_is_added_to_the_requirement() -> None:
    plan = solve_procurement(_problem([_offer("A")], safety=25))
    assert _qty(plan.lines, "A") == 125


def test_moq_forces_a_larger_order_when_buying_is_worth_it() -> None:
    plan = solve_procurement(_problem([_offer("A", moq=50)], demand=30))
    assert _qty(plan.lines, "A") == 50  # 30 needed, MOQ 50
    assert plan.metrics.feasible


def test_supplier_capacity_spills_over_to_the_next_supplier() -> None:
    offers = [_offer("A", capacity_per_week=15), _offer("B", unit_price=12.0)]
    plan = solve_procurement(
        _problem(
            offers,
            params=ProcurementParams(
                horizon_weeks=4, derate_by_reliability=False, fixed_order_cost=0.0
            ),
        )
    )
    assert _qty(plan.lines, "A") == 60  # 15/week x 4 weeks
    assert _qty(plan.lines, "B") == 40
    assert not [v for v in plan.metrics.violations if v.kind is ViolationKind.SUPPLIER_CAPACITY]


def test_reliability_derating_orders_extra_units() -> None:
    params = ProcurementParams(derate_by_reliability=True, fixed_order_cost=0.0)
    plan = solve_procurement(_problem([_offer("A")], reliability=0.8, params=params))
    assert _qty(plan.lines, "A") >= 95  # 95% service target on 100 units at 80% reliability
    assert plan.metrics.fill_rate >= 0.95


def test_contract_order_limit_splits_orders_across_suppliers() -> None:
    offers = [_offer("A"), _offer("B", unit_price=12.0)]
    plan = solve_procurement(_problem(offers, max_order_value=650.0))  # A <= 65, B <= 54 units
    assert _qty(plan.lines, "A") == 65
    assert _qty(plan.lines, "B") == 35
    assert plan.metrics.feasible


def test_warehouse_capacity_limits_quantity_and_reports_service_gap() -> None:
    plan = solve_procurement(_problem([_offer("A")], warehouse_capacity=60.0))
    assert _qty(plan.lines, "A") == 60
    kinds = {v.kind for v in plan.metrics.violations}
    assert kinds == {ViolationKind.SERVICE_LEVEL}  # physical limit holds; service is the gap


def test_budget_is_a_hard_limit_and_service_gap_is_reported() -> None:
    params = ProcurementParams(budget=500.0, derate_by_reliability=False, fixed_order_cost=0.0)
    plan = solve_procurement(_problem([_offer("A")], params=params))
    assert plan.metrics.spend <= 500.0 + 1e-6
    assert _qty(plan.lines, "A") == 50
    assert {v.kind for v in plan.metrics.violations} == {ViolationKind.SERVICE_LEVEL}


def test_unusable_offers_are_never_chosen() -> None:
    slow = _offer("A", lead_time_days=60)  # beyond the 28-day horizon
    plan = solve_procurement(_problem([slow, _offer("B", unit_price=15.0)]))
    assert _qty(plan.lines, "A") == 0 and _qty(plan.lines, "B") == 100
    suspended = solve_procurement(_problem([_offer("A")], contract_status=ContractStatus.SUSPENDED))
    assert suspended.lines == ()
    assert suspended.metrics.fill_rate == 0.0
    assert {v.kind for v in suspended.metrics.violations} == {ViolationKind.SERVICE_LEVEL}


def test_fixed_order_cost_consolidates_orders() -> None:
    offers = [_offer("A", unit_price=10.0), _offer("B", unit_price=9.9)]
    params = ProcurementParams(derate_by_reliability=False, fixed_order_cost=500.0)
    plan = solve_procurement(_problem(offers, params=params))
    assert len(plan.lines) == 1  # one PO beats two despite the tiny price gap


def test_solver_objective_matches_independent_evaluation() -> None:
    plan = solve_procurement(_problem([_offer("A"), _offer("B", unit_price=12.0)], safety=20))
    assert plan.metrics.feasible
    assert plan.solver_objective == pytest.approx(plan.metrics.objective, rel=1e-6)


def test_evaluator_flags_violations_in_hand_made_plans() -> None:
    problem = _problem([_offer("A", moq=50, capacity_per_week=20)], max_order_value=300.0)
    line = PurchaseLine(
        supplier_id="A",
        sku_id="SKU-1",
        warehouse_id="WH-1",
        quantity=40,
        unit_price=10.0,
        shipping_cost=0.0,
    )
    kinds = {v.kind for v in evaluate_plan(problem, [line]).violations}
    assert ViolationKind.BELOW_MOQ in kinds
    assert ViolationKind.SERVICE_LEVEL in kinds
    assert ViolationKind.ORDER_VALUE_LIMIT in kinds
    ghost = PurchaseLine(
        supplier_id="Z",
        sku_id="SKU-1",
        warehouse_id="WH-1",
        quantity=5,
        unit_price=1.0,
        shipping_cost=0.0,
    )
    assert evaluate_plan(problem, [ghost]).violations[0].kind is ViolationKind.UNUSABLE_OFFER


def test_cheapest_heuristic_ignores_reliability() -> None:
    params = ProcurementParams(derate_by_reliability=True, fixed_order_cost=0.0)
    problem = _problem([_offer("A")], reliability=0.8, params=params)
    catalog = SourcingCatalog.build(
        list(problem.skus.values()),
        list(problem.suppliers.values()),
        list(problem.warehouses.values()),
        [],
        [o for os in problem.offers.values() for o in os],
    )
    lines = reorder_up_to(problem, catalog)
    assert sum(line.quantity for line in lines) == 100
    metrics = evaluate_plan(problem, lines)
    assert {v.kind for v in metrics.violations} == {ViolationKind.SERVICE_LEVEL}
    assert solve_procurement(problem).metrics.feasible


@pytest.fixture(scope="module")
def world_problem() -> tuple[ProcurementProblem, SourcingCatalog]:
    world = generate_world(SyntheticConfig())
    weekly: dict[CellKey, float] = defaultdict(float)
    for sku in world.skus:
        for warehouse in world.warehouses:
            weekly[CellKey(sku.sku_id, warehouse.warehouse_id)] = 0.0
    totals: dict[str, int] = defaultdict(int)
    for order in world.sales_orders:
        totals[order.sku_id] += order.quantity
    n_weeks = world.config.n_weeks
    warehouses = [w.warehouse_id for w in world.warehouses]
    for sku_id, units in totals.items():
        for warehouse_id in warehouses:
            weekly[CellKey(sku_id, warehouse_id)] = units / n_weeks / len(warehouses)
    demand = {key: value * 4 for key, value in weekly.items()}
    # Solves in well under a minute on an idle machine; the headroom keeps it OPTIMAL under CI or build load.
    problem = problem_from_world(world, demand, ProcurementParams(time_limit_seconds=180))
    return problem, SourcingCatalog.from_world(world)


def test_world_plan_is_feasible_and_beats_heuristics(
    world_problem: tuple[ProcurementProblem, SourcingCatalog],
) -> None:
    problem, catalog = world_problem
    plan = solve_procurement(problem)
    assert plan.solver_status == "OPTIMAL"
    assert plan.metrics.feasible, plan.metrics.violations[:3]
    assert plan.metrics.objective == pytest.approx(plan.solver_objective, rel=1e-6)
    for choice in SupplierChoice:
        baseline = evaluate_plan(problem, reorder_up_to(problem, catalog, choice))
        assert plan.metrics.objective <= baseline.objective + 1e-6
        assert plan.metrics.fill_rate >= baseline.fill_rate - 1e-9 or baseline.violations == ()


def test_world_plan_is_reproducible(
    world_problem: tuple[ProcurementProblem, SourcingCatalog],
) -> None:
    problem, _ = world_problem
    first = solve_procurement(problem)
    second = solve_procurement(replace(problem))
    assert first.lines == second.lines
    assert first.metrics.objective == second.metrics.objective

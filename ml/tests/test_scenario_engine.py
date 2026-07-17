from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from scm_common.domain import Scenario, ScenarioType
from scm_ml.optimization import ProcurementParams
from scm_ml.optimization.binding import BindingKind, procurement_binding
from scm_ml.scenario import (
    CapacityReduction,
    DecisionResult,
    DemandShock,
    LeadTimeShock,
    PlanningInputs,
    PriceShock,
    ScenarioContractError,
    SupplierOutage,
    TransportCostShock,
    WarehouseCapacityReduction,
    apply_scenario,
    compare_scenario,
    make_scenario,
    run_pipeline,
    run_scenario,
    standard_scenarios,
)
from scm_ml.scenario.contract import ScenarioParameters
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld, generate_world

NOW = datetime(2025, 1, 6, tzinfo=UTC)
SMALL = SyntheticConfig(seed=31, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)


def _scenario(parameters: ScenarioParameters, scenario_id: str = "SCN-T") -> Scenario:
    return make_scenario(scenario_id, "test", parameters, NOW)


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    return generate_world(SMALL)


@pytest.fixture(scope="module")
def inputs(world: SyntheticWorld) -> PlanningInputs:
    units: dict[tuple[str, str], float] = defaultdict(float)
    for order in world.sales_orders:
        units[(order.sku_id, order.region_id)] += order.quantity
    horizon = 4
    demand = {key: total / world.config.n_weeks * horizon for key, total in units.items()}
    return PlanningInputs.from_world(world, demand, ProcurementParams(horizon_weeks=horizon))


@pytest.fixture(scope="module")
def baseline(inputs: PlanningInputs) -> DecisionResult:
    return run_pipeline(inputs)


def _supplier_units(result: DecisionResult, supplier_id: str) -> int:
    return sum(
        line.quantity for line in result.procurement.lines if line.supplier_id == supplier_id
    )


def _busiest_supplier(result: DecisionResult) -> str:
    units: dict[str, int] = defaultdict(int)
    for line in result.procurement.lines:
        units[line.supplier_id] += line.quantity
    return max(units, key=lambda s: (units[s], s))


def test_demand_shock_scales_scoped_demand_and_records_the_change(inputs: PlanningInputs) -> None:
    sku = next(iter(inputs.regional_demand))[0]
    applied = apply_scenario(inputs, _scenario(DemandShock(factor=1.2, sku_id=sku)))
    for key, value in inputs.regional_demand.items():
        expected = value * 1.2 if key[0] == sku else value
        assert applied.inputs.regional_demand[key] == pytest.approx(expected)
    (change,) = applied.changes
    assert change.scope == f"sku_id={sku}"
    assert change.after == pytest.approx(change.before * 1.2)
    assert inputs.regional_demand != applied.inputs.regional_demand  # original untouched


def test_supplier_outage_removes_every_offer_of_that_supplier(inputs: PlanningInputs) -> None:
    supplier = next(iter(inputs.catalog.suppliers))
    applied = apply_scenario(inputs, _scenario(SupplierOutage(supplier_id=supplier)))
    assert all(o.supplier_id != supplier for o in applied.inputs.catalog.offers)
    (change,) = applied.changes
    assert change.before == sum(o.supplier_id == supplier for o in inputs.catalog.offers)
    assert change.after == 0


def test_price_shock_scales_prices_only(inputs: PlanningInputs) -> None:
    applied = apply_scenario(inputs, _scenario(PriceShock(factor=1.15)))
    for old, new in zip(inputs.catalog.offers, applied.inputs.catalog.offers, strict=True):
        assert new.unit_price == pytest.approx(old.unit_price * 1.15, abs=1e-3)
        assert new.capacity_per_week == old.capacity_per_week
    (change,) = applied.changes
    assert change.after == pytest.approx(change.before * 1.15, rel=1e-3)


def test_capacity_reduction_floors_at_one_unit(inputs: PlanningInputs) -> None:
    applied = apply_scenario(inputs, _scenario(CapacityReduction(factor=0.7)))
    for old, new in zip(inputs.catalog.offers, applied.inputs.catalog.offers, strict=True):
        assert new.capacity_per_week == max(1, int(old.capacity_per_week * 0.7))


def test_lead_time_shock_pushes_offers_out_of_the_horizon(inputs: PlanningInputs) -> None:
    applied = apply_scenario(inputs, _scenario(LeadTimeShock(days=7)))
    for old, new in zip(inputs.catalog.offers, applied.inputs.catalog.offers, strict=True):
        assert new.lead_time_days == old.lead_time_days + 7
    within_limit = applied.changes[1]
    assert within_limit.after <= within_limit.before


def test_warehouse_capacity_reduction_scopes_to_one_warehouse(inputs: PlanningInputs) -> None:
    warehouse = sorted(inputs.catalog.warehouses)[0]
    applied = apply_scenario(
        inputs, _scenario(WarehouseCapacityReduction(factor=0.8, warehouse_id=warehouse))
    )
    for warehouse_id, old in inputs.catalog.warehouses.items():
        new = applied.inputs.catalog.warehouses[warehouse_id]
        expected = old.capacity_units * (0.8 if warehouse_id == warehouse else 1.0)
        assert new.capacity_units == pytest.approx(expected)


def test_transport_shock_scales_inbound_and_outbound_only_when_unscoped(
    inputs: PlanningInputs,
) -> None:
    unscoped = apply_scenario(inputs, _scenario(TransportCostShock(factor=1.25)))
    assert [c.assumption for c in unscoped.changes] == [
        "mean inbound shipping cost per unit",
        "mean outbound lane cost per unit",
    ]
    for old, new in zip(inputs.lanes, unscoped.inputs.lanes, strict=True):
        assert new.cost_per_unit == pytest.approx(old.cost_per_unit * 1.25, abs=1e-3)
    supplier = next(iter(inputs.catalog.suppliers))
    scoped = apply_scenario(
        inputs, _scenario(TransportCostShock(factor=1.25, supplier_id=supplier))
    )
    assert scoped.inputs.lanes == inputs.lanes
    assert len(scoped.changes) == 1


@pytest.mark.parametrize(
    "parameters",
    [
        SupplierOutage(supplier_id="SUP-999"),
        DemandShock(factor=1.2, sku_id="SKU-999"),
        DemandShock(factor=1.2, region_id="R99"),
        WarehouseCapacityReduction(factor=0.8, warehouse_id="WH-99"),
    ],
)
def test_unknown_entities_are_rejected(
    inputs: PlanningInputs, parameters: ScenarioParameters
) -> None:
    with pytest.raises(ScenarioContractError, match="unknown"):
        apply_scenario(inputs, _scenario(parameters))


def test_every_standard_scenario_applies_and_changes_something(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    for scenario in standard_scenarios(NOW, _busiest_supplier(baseline)):
        applied = apply_scenario(inputs, scenario)
        assert applied.changes, scenario.scenario_id
        assert any(c.before != c.after for c in applied.changes), scenario.scenario_id


def test_scenario_runs_are_reproducible(inputs: PlanningInputs, baseline: DecisionResult) -> None:
    scenario = _scenario(PriceShock(factor=1.15))
    first = run_scenario(inputs, scenario, baseline)
    second = run_scenario(inputs, scenario, baseline)
    assert first.response.procurement.lines == second.response.procurement.lines
    assert first.response.procurement.metrics == second.response.procurement.metrics
    assert first.disrupted.procurement.metrics == second.disrupted.procurement.metrics
    assert compare_scenario(first) == compare_scenario(second)


def test_outage_drops_the_supplier_and_shows_the_loss(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    supplier = _busiest_supplier(baseline)
    run = run_scenario(inputs, _scenario(SupplierOutage(supplier_id=supplier)), baseline)
    comparison = compare_scenario(run)
    assert _supplier_units(baseline, supplier) > 0
    assert _supplier_units(run.disrupted, supplier) == 0
    assert _supplier_units(run.response, supplier) == 0
    assert comparison.commitment_violations.get("UNUSABLE_OFFER", 0) >= 1
    assert comparison.disrupted.fill_rate <= comparison.baseline.fill_rate
    assert comparison.response_benefit >= -1e-6  # re-planning is never worse than holding still
    shift = next(
        s for s in comparison.changed_allocations.supplier_shifts if s.supplier_id == supplier
    )
    assert shift.baseline_units > 0 and shift.response_units == 0
    assert comparison.changed_allocations.changed_purchase_lines > 0


def test_price_shock_raises_cost_and_comparison_arithmetic_is_consistent(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    run = run_scenario(inputs, _scenario(PriceShock(factor=1.15)), baseline)
    comparison = compare_scenario(run)
    assert comparison.resilience_cost > 0
    assert comparison.resilience_cost == pytest.approx(
        comparison.response.objective - comparison.baseline.objective
    )
    assert comparison.objective_delta_response.absolute == pytest.approx(comparison.resilience_cost)
    assert comparison.objective_delta_response.percent == pytest.approx(
        100 * comparison.resilience_cost / comparison.baseline.objective
    )
    assert comparison.response_benefit == pytest.approx(
        comparison.disrupted.objective - comparison.response.objective
    )
    assert comparison.service_level_delta_response == pytest.approx(
        comparison.response.customer_fill_rate - comparison.baseline.customer_fill_rate
    )


def test_baseline_compared_with_itself_shows_no_change(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    run = run_scenario(inputs, _scenario(DemandShock(factor=1.0)), baseline)
    comparison = compare_scenario(run)
    assert comparison.resilience_cost == pytest.approx(0.0, abs=1e-6)
    assert comparison.changed_allocations.changed_purchase_lines == 0
    assert comparison.newly_binding == () and comparison.no_longer_binding == ()


def test_demand_surge_needs_more_units_and_is_covered_by_the_response(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    run = run_scenario(inputs, _scenario(DemandShock(factor=1.2)), baseline)
    comparison = compare_scenario(run)
    assert comparison.response.units_ordered > comparison.baseline.units_ordered
    assert comparison.response_benefit >= -1e-6
    assert comparison.response.customer_fill_rate >= comparison.disrupted.customer_fill_rate - 1e-9


def test_capacity_cut_creates_binding_supplier_capacity(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    run = run_scenario(inputs, _scenario(CapacityReduction(factor=0.3)), baseline)
    comparison = compare_scenario(run)
    before = comparison.baseline_binding.get("SUPPLIER_CAPACITY", 0)
    after = comparison.response_binding.get("SUPPLIER_CAPACITY", 0)
    assert after > before
    assert any(c.kind is BindingKind.SUPPLIER_CAPACITY for c in comparison.newly_binding)
    assert comparison.commitment_violations == {} or set(comparison.commitment_violations) <= {
        "SUPPLIER_CAPACITY",
        "UNUSABLE_OFFER",
        "BELOW_MOQ",
    }


def test_budget_shows_up_as_a_binding_constraint(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    assert not any(
        c.kind is BindingKind.BUDGET
        for c in procurement_binding(baseline.problem, baseline.procurement.lines)
    )
    tight = replace(
        inputs, params=replace(inputs.params, budget=baseline.procurement.metrics.spend * 0.9)
    )
    result = run_pipeline(tight)
    kinds = {c.kind for c in procurement_binding(result.problem, result.procurement.lines)}
    assert BindingKind.BUDGET in kinds


def test_scenario_types_in_a_full_sweep_are_all_comparable(
    inputs: PlanningInputs, baseline: DecisionResult
) -> None:
    scenarios = standard_scenarios(NOW, _busiest_supplier(baseline))
    comparisons = [compare_scenario(run_scenario(inputs, s, baseline)) for s in scenarios]
    assert {c.scenario_type for c in comparisons} == set(ScenarioType)
    for comparison in comparisons:
        assert comparison.response.customer_fill_rate >= 0
        assert comparison.model_dump_json()  # serializable for the API/UI

from datetime import UTC, datetime

import pytest

from scm_common.domain import Scenario, ScenarioType
from scm_ml.scenario import (
    PARAMETER_MODELS,
    DemandShock,
    LeadTimeShock,
    ScenarioContractError,
    SupplierOutage,
    make_scenario,
    parse_parameters,
    standard_scenarios,
)

NOW = datetime(2025, 1, 6, tzinfo=UTC)


def _scenario(kind: ScenarioType, **parameters: float | str) -> Scenario:
    return Scenario(
        scenario_id="SCN-X", name="x", scenario_type=kind, parameters=parameters, created_at=NOW
    )


def test_every_scenario_type_has_a_parameter_model() -> None:
    assert set(PARAMETER_MODELS) == set(ScenarioType)


def test_standard_scenarios_cover_all_seven_types_with_required_magnitudes() -> None:
    scenarios = standard_scenarios(NOW, "SUP-003")
    assert {s.scenario_type for s in scenarios} == set(ScenarioType)
    by_type = {s.scenario_type: parse_parameters(s) for s in scenarios}
    assert by_type[ScenarioType.DEMAND_SHOCK].factor == 1.2  # type: ignore[union-attr]
    assert by_type[ScenarioType.PRICE_SHOCK].factor == 1.15  # type: ignore[union-attr]
    assert by_type[ScenarioType.CAPACITY_REDUCTION].factor == 0.7  # type: ignore[union-attr]
    assert by_type[ScenarioType.LEAD_TIME_SHOCK].days == 7  # type: ignore[union-attr]
    assert by_type[ScenarioType.WAREHOUSE_CAPACITY_REDUCTION].factor == 0.8  # type: ignore[union-attr]
    assert by_type[ScenarioType.TRANSPORT_COST_SHOCK].factor == 1.25  # type: ignore[union-attr]
    assert by_type[ScenarioType.SUPPLIER_OUTAGE].supplier_id == "SUP-003"  # type: ignore[union-attr]


def test_flat_domain_parameters_round_trip_through_typed_models() -> None:
    typed = DemandShock(factor=1.5, sku_id="SKU-001")
    scenario = make_scenario("SCN-1", "Promo", typed, NOW)
    assert scenario.parameters == {"factor": 1.5, "sku_id": "SKU-001"}
    assert parse_parameters(Scenario.model_validate_json(scenario.model_dump_json())) == typed
    lead = make_scenario("SCN-2", "Slow", LeadTimeShock(days=7), NOW)
    assert parse_parameters(lead) == LeadTimeShock(days=7)


@pytest.mark.parametrize(
    ("kind", "parameters", "fragment"),
    [
        (ScenarioType.DEMAND_SHOCK, {}, "factor"),
        (ScenarioType.DEMAND_SHOCK, {"factor": 0.0}, "factor"),
        (ScenarioType.DEMAND_SHOCK, {"factor": 50.0}, "factor"),
        (ScenarioType.DEMAND_SHOCK, {"factor": 1.2, "colour": "red"}, "colour"),
        (ScenarioType.DEMAND_SHOCK, {"factor": 1.2, "sku_id": ""}, "sku_id"),
        (ScenarioType.SUPPLIER_OUTAGE, {}, "supplier_id"),
        (ScenarioType.CAPACITY_REDUCTION, {"factor": 1.3}, "factor"),
        (ScenarioType.WAREHOUSE_CAPACITY_REDUCTION, {"factor": 0.0}, "factor"),
        (ScenarioType.LEAD_TIME_SHOCK, {"days": 0}, "days"),
        (ScenarioType.LEAD_TIME_SHOCK, {"days": 2.5}, "days"),
        (ScenarioType.PRICE_SHOCK, {"factor": "high"}, "factor"),
    ],
)
def test_invalid_parameters_are_rejected_with_the_offending_field(
    kind: ScenarioType, parameters: dict[str, float | str], fragment: str
) -> None:
    with pytest.raises(ScenarioContractError, match=fragment):
        parse_parameters(_scenario(kind, **parameters))


def test_typed_models_are_immutable_and_scoped_optionally() -> None:
    outage = SupplierOutage(supplier_id="SUP-001")
    with pytest.raises(ValueError, match="frozen"):
        outage.supplier_id = "SUP-002"  # type: ignore[misc]
    assert DemandShock(factor=1.1).region_id is None

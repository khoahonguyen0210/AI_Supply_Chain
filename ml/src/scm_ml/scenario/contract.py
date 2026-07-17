"""Scenario contract: typed, validated parameters for each supported disruption.

The domain `Scenario` stores `parameters` as a flat `{name: number | text}` mapping so it persists
and travels as JSON. This module defines what each scenario type accepts, validates it and returns
a typed model. Factors are multipliers (1.2 = +20%, 0.7 = -30%); a missing scope means everywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from scm_common.domain import DomainModel, Scenario, ScenarioType

Factor = Annotated[float, Field(gt=0, le=10)]
Reduction = Annotated[float, Field(gt=0, le=1, description="Share of capacity that remains.")]
OptionalId = Annotated[str | None, Field(min_length=1)]


class ScenarioContractError(ValueError):
    """The scenario's parameters are not valid for its type."""


class DemandShock(DomainModel):
    kind: Literal[ScenarioType.DEMAND_SHOCK] = ScenarioType.DEMAND_SHOCK
    factor: Factor
    sku_id: OptionalId = None
    region_id: OptionalId = None


class SupplierOutage(DomainModel):
    kind: Literal[ScenarioType.SUPPLIER_OUTAGE] = ScenarioType.SUPPLIER_OUTAGE
    supplier_id: str = Field(min_length=1)


class PriceShock(DomainModel):
    kind: Literal[ScenarioType.PRICE_SHOCK] = ScenarioType.PRICE_SHOCK
    factor: Factor
    supplier_id: OptionalId = None
    sku_id: OptionalId = None


class CapacityReduction(DomainModel):
    kind: Literal[ScenarioType.CAPACITY_REDUCTION] = ScenarioType.CAPACITY_REDUCTION
    factor: Reduction
    supplier_id: OptionalId = None


class LeadTimeShock(DomainModel):
    kind: Literal[ScenarioType.LEAD_TIME_SHOCK] = ScenarioType.LEAD_TIME_SHOCK
    days: Annotated[int, Field(ge=1, le=180)]
    supplier_id: OptionalId = None


class WarehouseCapacityReduction(DomainModel):
    kind: Literal[ScenarioType.WAREHOUSE_CAPACITY_REDUCTION] = (
        ScenarioType.WAREHOUSE_CAPACITY_REDUCTION
    )
    factor: Reduction
    warehouse_id: OptionalId = None


class TransportCostShock(DomainModel):
    kind: Literal[ScenarioType.TRANSPORT_COST_SHOCK] = ScenarioType.TRANSPORT_COST_SHOCK
    factor: Factor
    supplier_id: OptionalId = None
    """Scope for inbound shipping; outbound warehouse-to-region lanes change only when unscoped."""


ScenarioParameters = (
    DemandShock
    | SupplierOutage
    | PriceShock
    | CapacityReduction
    | LeadTimeShock
    | WarehouseCapacityReduction
    | TransportCostShock
)

PARAMETER_MODELS: dict[ScenarioType, type[ScenarioParameters]] = {
    ScenarioType.DEMAND_SHOCK: DemandShock,
    ScenarioType.SUPPLIER_OUTAGE: SupplierOutage,
    ScenarioType.PRICE_SHOCK: PriceShock,
    ScenarioType.CAPACITY_REDUCTION: CapacityReduction,
    ScenarioType.LEAD_TIME_SHOCK: LeadTimeShock,
    ScenarioType.WAREHOUSE_CAPACITY_REDUCTION: WarehouseCapacityReduction,
    ScenarioType.TRANSPORT_COST_SHOCK: TransportCostShock,
}

_ADAPTER: TypeAdapter[ScenarioParameters] = TypeAdapter(
    Annotated[ScenarioParameters, Field(discriminator="kind")]
)


def parse_parameters(scenario: Scenario) -> ScenarioParameters:
    """Validate a domain scenario's flat parameters against its type and return the typed model."""
    payload = {"kind": scenario.scenario_type.value, **scenario.parameters}
    try:
        parsed = _ADAPTER.validate_python(payload)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
        )
        raise ScenarioContractError(
            f"{scenario.scenario_type.value} scenario {scenario.scenario_id!r}: {problems}"
        ) from None
    return parsed


def make_scenario(
    scenario_id: str,
    name: str,
    parameters: ScenarioParameters,
    created_at: datetime,
) -> Scenario:
    """Build a domain scenario from typed parameters (the inverse of `parse_parameters`)."""
    flat = {
        key: value
        for key, value in parameters.model_dump(exclude={"kind"}).items()
        if value is not None
    }
    scenario = Scenario(
        scenario_id=scenario_id,
        name=name,
        scenario_type=parameters.kind,
        parameters=flat,
        created_at=created_at,
    )
    parse_parameters(scenario)
    return scenario


def standard_scenarios(created_at: datetime, outage_supplier_id: str) -> list[Scenario]:
    """The seven disruptions required by the research dossier, each with its stated magnitude."""
    return [
        make_scenario("SCN-DEMAND-20", "Demand +20%", DemandShock(factor=1.2), created_at),
        make_scenario(
            "SCN-OUTAGE",
            f"Supplier outage ({outage_supplier_id})",
            SupplierOutage(supplier_id=outage_supplier_id),
            created_at,
        ),
        make_scenario("SCN-PRICE-15", "Supplier price +15%", PriceShock(factor=1.15), created_at),
        make_scenario(
            "SCN-CAPACITY-30", "Supplier capacity -30%", CapacityReduction(factor=0.7), created_at
        ),
        make_scenario("SCN-LEAD-7", "Lead time +7 days", LeadTimeShock(days=7), created_at),
        make_scenario(
            "SCN-WAREHOUSE-20",
            "Warehouse capacity -20%",
            WarehouseCapacityReduction(factor=0.8),
            created_at,
        ),
        make_scenario(
            "SCN-TRANSPORT-25", "Transport cost +25%", TransportCostShock(factor=1.25), created_at
        ),
    ]

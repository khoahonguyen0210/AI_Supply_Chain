from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from pydantic import Field

from scm_common.domain import (
    DomainModel,
    FulfillmentLane,
    InventoryPosition,
    Scenario,
    SupplierOffer,
    Warehouse,
)
from scm_ml.optimization import ProcurementParams
from scm_ml.sourcing import SourcingCatalog
from scm_ml.synthetic import SyntheticWorld

from .contract import (
    CapacityReduction,
    DemandShock,
    LeadTimeShock,
    PriceShock,
    ScenarioContractError,
    SupplierOutage,
    TransportCostShock,
    WarehouseCapacityReduction,
    parse_parameters,
)


@dataclass(frozen=True)
class PlanningInputs:
    as_of: date
    catalog: SourcingCatalog
    inventory: tuple[InventoryPosition, ...]
    lanes: tuple[FulfillmentLane, ...]
    regional_demand: dict[tuple[str, str], float]
    params: ProcurementParams

    @classmethod
    def from_world(
        cls,
        world: SyntheticWorld,
        regional_demand: dict[tuple[str, str], float],
        params: ProcurementParams | None = None,
    ) -> PlanningInputs:
        return cls(
            as_of=world.as_of,
            catalog=SourcingCatalog.from_world(world),
            inventory=tuple(world.inventory),
            lanes=tuple(world.lanes),
            regional_demand=dict(regional_demand),
            params=params or ProcurementParams(),
        )


class AssumptionChange(DomainModel):
    assumption: str
    scope: str
    affected: int = Field(ge=0, description="Entities changed (offers, lanes, cells, ...).")
    before: float
    after: float


@dataclass(frozen=True)
class AppliedScenario:
    scenario: Scenario
    inputs: PlanningInputs
    changes: tuple[AssumptionChange, ...]


def _scope(**selectors: str | None) -> str:
    chosen = [f"{k}={v}" for k, v in selectors.items() if v is not None]
    return ", ".join(chosen) if chosen else "all"


def _require(known: set[str], value: str | None, what: str, scenario: Scenario) -> None:
    if value is not None and value not in known:
        raise ScenarioContractError(f"scenario {scenario.scenario_id!r}: unknown {what} {value!r}")


def _map_offers(
    inputs: PlanningInputs,
    selected: Callable[[SupplierOffer], bool],
    change: Callable[[SupplierOffer], SupplierOffer | None],
) -> tuple[PlanningInputs, list[SupplierOffer], list[SupplierOffer]]:
    before: list[SupplierOffer] = []
    after: list[SupplierOffer] = []
    kept: list[SupplierOffer] = []
    for offer in inputs.catalog.offers:
        if not selected(offer):
            kept.append(offer)
            continue
        before.append(offer)
        updated = change(offer)
        if updated is not None:
            after.append(updated)
            kept.append(updated)
    catalog = replace(inputs.catalog, offers=tuple(kept))
    return replace(inputs, catalog=catalog), before, after


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def apply_scenario(inputs: PlanningInputs, scenario: Scenario) -> AppliedScenario:
    params = parse_parameters(scenario)
    catalog = inputs.catalog
    suppliers, skus, warehouses = set(catalog.suppliers), set(catalog.skus), set(catalog.warehouses)
    regions = {lane.region_id for lane in inputs.lanes}

    if isinstance(params, DemandShock):
        _require(skus, params.sku_id, "SKU", scenario)
        _require(regions, params.region_id, "region", scenario)
        demand = dict(inputs.regional_demand)
        touched = [
            key
            for key in demand
            if params.sku_id in (None, key[0]) and params.region_id in (None, key[1])
        ]
        before = sum(demand[k] for k in touched)
        for key in touched:
            demand[key] *= params.factor
        change = AssumptionChange(
            assumption="forecast demand (units over horizon)",
            scope=_scope(sku_id=params.sku_id, region_id=params.region_id),
            affected=len(touched),
            before=before,
            after=sum(demand[k] for k in touched),
        )
        return AppliedScenario(scenario, replace(inputs, regional_demand=demand), (change,))

    if isinstance(params, SupplierOutage):
        _require(suppliers, params.supplier_id, "supplier", scenario)
        new, before_offers, _ = _map_offers(
            inputs, lambda o: o.supplier_id == params.supplier_id, lambda o: None
        )
        change = AssumptionChange(
            assumption="offers available",
            scope=_scope(supplier_id=params.supplier_id),
            affected=len(before_offers),
            before=float(len(before_offers)),
            after=0.0,
        )
        return AppliedScenario(scenario, new, (change,))

    if isinstance(params, PriceShock):
        _require(suppliers, params.supplier_id, "supplier", scenario)
        _require(skus, params.sku_id, "SKU", scenario)
        new, before_offers, after_offers = _map_offers(
            inputs,
            lambda o: (
                params.supplier_id in (None, o.supplier_id) and params.sku_id in (None, o.sku_id)
            ),
            lambda o: o.model_copy(update={"unit_price": round(o.unit_price * params.factor, 4)}),
        )
        change = AssumptionChange(
            assumption="mean offer unit price",
            scope=_scope(supplier_id=params.supplier_id, sku_id=params.sku_id),
            affected=len(before_offers),
            before=_mean([o.unit_price for o in before_offers]),
            after=_mean([o.unit_price for o in after_offers]),
        )
        return AppliedScenario(scenario, new, (change,))

    if isinstance(params, CapacityReduction):
        _require(suppliers, params.supplier_id, "supplier", scenario)
        new, before_offers, after_offers = _map_offers(
            inputs,
            lambda o: params.supplier_id in (None, o.supplier_id),
            lambda o: o.model_copy(
                update={
                    "capacity_per_week": max(1, math.floor(o.capacity_per_week * params.factor))
                }
            ),
        )
        change = AssumptionChange(
            assumption="total weekly supplier capacity (units)",
            scope=_scope(supplier_id=params.supplier_id),
            affected=len(before_offers),
            before=float(sum(o.capacity_per_week for o in before_offers)),
            after=float(sum(o.capacity_per_week for o in after_offers)),
        )
        return AppliedScenario(scenario, new, (change,))

    if isinstance(params, LeadTimeShock):
        _require(suppliers, params.supplier_id, "supplier", scenario)
        new, before_offers, after_offers = _map_offers(
            inputs,
            lambda o: params.supplier_id in (None, o.supplier_id),
            lambda o: o.model_copy(update={"lead_time_days": o.lead_time_days + params.days}),
        )
        limit = inputs.params.lead_time_limit
        change = AssumptionChange(
            assumption="mean offer lead time (days)",
            scope=_scope(supplier_id=params.supplier_id),
            affected=len(before_offers),
            before=_mean([float(o.lead_time_days) for o in before_offers]),
            after=_mean([float(o.lead_time_days) for o in after_offers]),
        )
        late = AssumptionChange(
            assumption=f"offers within the {limit}-day lead-time limit",
            scope=_scope(supplier_id=params.supplier_id),
            affected=len(before_offers),
            before=float(sum(o.lead_time_days <= limit for o in before_offers)),
            after=float(sum(o.lead_time_days <= limit for o in after_offers)),
        )
        return AppliedScenario(scenario, new, (change, late))

    if isinstance(params, WarehouseCapacityReduction):
        _require(warehouses, params.warehouse_id, "warehouse", scenario)
        reduced: dict[str, Warehouse] = {}
        for warehouse_id, warehouse in catalog.warehouses.items():
            if params.warehouse_id in (None, warehouse_id):
                reduced[warehouse_id] = warehouse.model_copy(
                    update={"capacity_units": warehouse.capacity_units * params.factor}
                )
            else:
                reduced[warehouse_id] = warehouse
        affected = [w for w in catalog.warehouses if params.warehouse_id in (None, w)]
        change = AssumptionChange(
            assumption="warehouse capacity (units)",
            scope=_scope(warehouse_id=params.warehouse_id),
            affected=len(affected),
            before=sum(catalog.warehouses[w].capacity_units for w in affected),
            after=sum(reduced[w].capacity_units for w in affected),
        )
        new_inputs = replace(inputs, catalog=replace(catalog, warehouses=reduced))
        return AppliedScenario(scenario, new_inputs, (change,))

    assert isinstance(params, TransportCostShock)
    _require(suppliers, params.supplier_id, "supplier", scenario)

    def scaled(offer: SupplierOffer) -> SupplierOffer:
        shipping = {
            warehouse: round(cost * params.factor, 4)
            for warehouse, cost in offer.shipping_cost_per_unit.items()
        }
        return offer.model_copy(update={"shipping_cost_per_unit": shipping})

    new, before_offers, after_offers = _map_offers(
        inputs, lambda o: params.supplier_id in (None, o.supplier_id), scaled
    )
    changes = [
        AssumptionChange(
            assumption="mean inbound shipping cost per unit",
            scope=_scope(supplier_id=params.supplier_id),
            affected=len(before_offers),
            before=_mean([c for o in before_offers for c in o.shipping_cost_per_unit.values()]),
            after=_mean([c for o in after_offers for c in o.shipping_cost_per_unit.values()]),
        )
    ]
    if params.supplier_id is None:
        lanes = tuple(
            lane.model_copy(update={"cost_per_unit": round(lane.cost_per_unit * params.factor, 4)})
            for lane in inputs.lanes
        )
        changes.append(
            AssumptionChange(
                assumption="mean outbound lane cost per unit",
                scope="all",
                affected=len(lanes),
                before=_mean([lane.cost_per_unit for lane in inputs.lanes]),
                after=_mean([lane.cost_per_unit for lane in lanes]),
            )
        )
        new = replace(new, lanes=lanes)
    return AppliedScenario(scenario, new, tuple(changes))

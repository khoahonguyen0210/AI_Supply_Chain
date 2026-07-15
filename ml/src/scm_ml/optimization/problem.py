from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import NamedTuple

from scm_common.domain import InventoryPosition, Sku, Supplier, SupplierOffer, Warehouse
from scm_ml.sourcing import SourcingCatalog
from scm_ml.sourcing.eligibility import max_order_value, structural_rejections
from scm_ml.synthetic import SyntheticWorld

SERVICE_VIOLATION_PENALTY = 1_000.0
"""Per-unit penalty on missing the service target; large, so only an infeasible target pays it."""


class CellKey(NamedTuple):
    sku_id: str
    warehouse_id: str


@dataclass(frozen=True)
class Cell:
    demand: float  # forecast demand over the planning horizon
    on_hand: int
    incoming: int
    safety_stock: int

    @property
    def available(self) -> int:
        return self.on_hand + self.incoming


@dataclass(frozen=True)
class ProcurementParams:
    horizon_weeks: int = 4
    budget: float | None = None
    service_level_target: float = 0.95
    stockout_penalty_multiplier: float = 1.0
    """Penalty per unit of unmet demand, as a multiple of the SKU selling price (lost revenue)."""
    safety_shortfall_penalty_fraction: float = 1.0
    """Penalty per unit below demand + safety stock, as a fraction of the price.

    Must exceed the unit cost-to-price ratio, or buying safety stock is never worth it.
    """
    fixed_order_cost: float = 25.0
    """Cost of placing one purchase order (one supplier, SKU and warehouse)."""
    derate_by_reliability: bool = True
    """Count only reliability x ordered units as arriving when judging service."""
    max_lead_time_days: int | None = None
    """Offers slower than this cannot land in the horizon; defaults to the horizon length."""
    time_limit_seconds: float = 60.0
    mip_rel_gap: float = 1e-4

    @property
    def lead_time_limit(self) -> int:
        return (
            self.max_lead_time_days
            if self.max_lead_time_days is not None
            else (self.horizon_weeks * 7)
        )


@dataclass(frozen=True)
class ProcurementProblem:
    as_of: date
    params: ProcurementParams
    skus: Mapping[str, Sku]
    suppliers: Mapping[str, Supplier]
    warehouses: Mapping[str, Warehouse]
    cells: Mapping[CellKey, Cell]
    offers: Mapping[CellKey, tuple[SupplierOffer, ...]]
    """Usable offers per cell: valid, certified, contracted, in lead time, lane to the site."""
    order_limit: Mapping[str, float | None] = field(default_factory=dict)
    """Largest single purchase order value per supplier (None = unlimited)."""

    def reliability(self, supplier_id: str) -> float:
        if not self.params.derate_by_reliability:
            return 1.0
        return self.suppliers[supplier_id].reliability

    def stockout_penalty(self, sku_id: str) -> float:
        return self.skus[sku_id].unit_price * self.params.stockout_penalty_multiplier

    def shortfall_penalty(self, sku_id: str) -> float:
        return self.skus[sku_id].unit_price * self.params.safety_shortfall_penalty_fraction

    def max_units(self, offer: SupplierOffer) -> int:
        units = offer.capacity_per_week * self.params.horizon_weeks
        limit = self.order_limit.get(offer.supplier_id)
        if limit is not None:
            units = min(units, int(limit // offer.unit_price))
        return units


def build_problem(
    catalog: SourcingCatalog,
    inventory: list[InventoryPosition],
    demand: Mapping[CellKey, float],
    as_of: date,
    params: ProcurementParams | None = None,
) -> ProcurementProblem:
    params = params or ProcurementParams()
    unknown = [
        k
        for k in demand
        if k.sku_id not in catalog.skus or k.warehouse_id not in catalog.warehouses
    ]
    if unknown:
        raise ValueError(f"demand refers to unknown cells: {unknown[:3]}")
    positions = {CellKey(p.sku_id, p.warehouse_id): p for p in inventory}
    cells: dict[CellKey, Cell] = {}
    for sku_id in sorted(catalog.skus):
        for warehouse_id in sorted(catalog.warehouses):
            key = CellKey(sku_id, warehouse_id)
            position = positions.get(key)
            cells[key] = Cell(
                demand=float(demand.get(key, 0.0)),
                on_hand=position.on_hand if position else 0,
                incoming=position.incoming if position else 0,
                safety_stock=position.safety_stock if position else 0,
            )
    offers: dict[CellKey, tuple[SupplierOffer, ...]] = {}
    for key in cells:
        offers[key] = tuple(
            offer
            for offer in catalog.offers_for_sku(key.sku_id)
            if not structural_rejections(
                offer,
                catalog,
                as_of=as_of,
                warehouse_id=key.warehouse_id,
                max_lead_time_days=params.lead_time_limit,
            )
        )
    limits = {
        supplier_id: max_order_value(contracts, as_of)
        for supplier_id, contracts in catalog.contracts.items()
    }
    return ProcurementProblem(
        as_of=as_of,
        params=params,
        skus=catalog.skus,
        suppliers=catalog.suppliers,
        warehouses=catalog.warehouses,
        cells=cells,
        offers=offers,
        order_limit=limits,
    )


def problem_from_world(
    world: SyntheticWorld,
    demand: Mapping[CellKey, float],
    params: ProcurementParams | None = None,
) -> ProcurementProblem:
    return build_problem(
        SourcingCatalog.from_world(world), world.inventory, demand, world.as_of, params
    )

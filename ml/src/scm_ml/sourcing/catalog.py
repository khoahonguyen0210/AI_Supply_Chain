from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from pydantic import Field

from scm_common.domain import (
    DomainModel,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)
from scm_ml.synthetic import SyntheticWorld


class SourcingRequest(DomainModel):
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1, description="Destination warehouse.")
    quantity: int = Field(ge=1)
    as_of: date = Field(description="Decision date; offer validity and contracts are checked here.")
    max_lead_time_days: int = Field(ge=0, description="Latest acceptable delivery lead time.")
    horizon_weeks: int = Field(
        default=1, ge=1, description="Weeks over which supplier weekly capacity can be drawn."
    )
    allowed_supplier_regions: tuple[str, ...] | None = Field(
        default=None, description="Restrict to suppliers shipping from these regions."
    )


@dataclass(frozen=True)
class SourcingCatalog:
    skus: dict[str, Sku]
    suppliers: dict[str, Supplier]
    warehouses: dict[str, Warehouse]
    contracts: dict[str, tuple[SupplierContract, ...]]
    offers: tuple[SupplierOffer, ...]

    @classmethod
    def build(
        cls,
        skus: Iterable[Sku],
        suppliers: Iterable[Supplier],
        warehouses: Iterable[Warehouse],
        contracts: Iterable[SupplierContract],
        offers: Iterable[SupplierOffer],
    ) -> SourcingCatalog:
        by_supplier: dict[str, list[SupplierContract]] = {}
        for contract in contracts:
            by_supplier.setdefault(contract.supplier_id, []).append(contract)
        return cls(
            skus={s.sku_id: s for s in skus},
            suppliers={s.supplier_id: s for s in suppliers},
            warehouses={w.warehouse_id: w for w in warehouses},
            contracts={k: tuple(v) for k, v in by_supplier.items()},
            offers=tuple(sorted(offers, key=lambda o: o.offer_id)),
        )

    @classmethod
    def from_world(cls, world: SyntheticWorld) -> SourcingCatalog:
        return cls.build(
            world.skus, world.suppliers, world.warehouses, world.contracts, world.offers
        )

    def offers_for_sku(self, sku_id: str) -> tuple[SupplierOffer, ...]:
        return tuple(o for o in self.offers if o.sku_id == sku_id)

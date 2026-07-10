from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from scm_common.domain import (
    FulfillmentLane,
    InventoryPosition,
    PurchaseOrder,
    Region,
    SalesOrder,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)

from .config import SyntheticConfig


@dataclass(frozen=True)
class SyntheticWorld:
    config: SyntheticConfig
    as_of: date
    regions: list[Region]
    warehouses: list[Warehouse]
    lanes: list[FulfillmentLane]
    skus: list[Sku]
    suppliers: list[Supplier]
    contracts: list[SupplierContract]
    offers: list[SupplierOffer]
    sales_orders: list[SalesOrder]
    purchase_orders: list[PurchaseOrder]
    inventory: list[InventoryPosition]

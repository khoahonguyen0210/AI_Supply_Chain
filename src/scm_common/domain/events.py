from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field

from .base import DomainModel, UtcDatetime


class SalesOrder(DomainModel):
    order_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    ordered_at: UtcDatetime
    quantity: int = Field(ge=1)


class DemandObservation(DomainModel):
    sku_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    period_start: date
    quantity: float = Field(ge=0)
    source: str = Field(min_length=1, description="Dataset identity, e.g. 'synthetic-v1'.")
    observed_at: UtcDatetime = Field(description="When this value became known (leakage guard).")


class InventoryPosition(DomainModel):
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    as_of: UtcDatetime
    on_hand: int = Field(ge=0)
    incoming: int = Field(ge=0, description="Units on open purchase orders.")
    safety_stock: int = Field(ge=0)


class PurchaseOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLACED = "PLACED"
    DELIVERED = "DELIVERED"


class PurchaseOrder(DomainModel):
    po_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price: float = Field(gt=0)
    status: PurchaseOrderStatus
    created_at: UtcDatetime
    expected_delivery: date
    delivered_at: date | None = None
    delivered_quantity: int | None = Field(default=None, ge=0)

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .base import DomainModel


class Region(DomainModel):
    region_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Sku(DomainModel):
    sku_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    unit_price: float = Field(gt=0, description="Selling price per unit.")
    unit_volume: float = Field(gt=0, description="Warehouse capacity units consumed per unit.")
    required_certifications: tuple[str, ...] = ()


class Supplier(DomainModel):
    supplier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region_id: str = Field(min_length=1, description="Region the supplier ships from.")
    reliability: float = Field(ge=0, le=1, description="Historical on-time-in-full rate.")
    quality_score: float = Field(ge=0, le=1)
    certifications: tuple[str, ...] = ()


class Warehouse(DomainModel):
    warehouse_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    capacity_units: float = Field(gt=0, description="Total storage capacity in capacity units.")
    holding_cost_per_unit_week: float = Field(ge=0)


class FulfillmentLane(DomainModel):
    warehouse_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    cost_per_unit: float = Field(ge=0)
    transit_days: int = Field(ge=0)


class ContractStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class SupplierContract(DomainModel):
    contract_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    status: ContractStatus
    effective_from: date
    effective_to: date
    payment_terms_days: int = Field(ge=0)
    max_order_value: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _dates_ordered(self) -> SupplierContract:
        if self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class SupplierOffer(DomainModel):
    offer_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    unit_price: float = Field(gt=0)
    moq: int = Field(ge=1, description="Minimum order quantity per purchase order.")
    capacity_per_week: int = Field(ge=1, description="Max units deliverable per week.")
    lead_time_days: int = Field(ge=0)
    shipping_cost_per_unit: dict[str, float] = Field(
        default_factory=dict,
        description="Shipping cost per unit, keyed by destination warehouse_id.",
    )
    valid_from: date
    valid_to: date

    @model_validator(mode="after")
    def _validity_ordered(self) -> SupplierOffer:
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self

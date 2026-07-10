from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from scm_common.domain import DomainModel

GENERATOR_VERSION = "1"


class SyntheticConfig(DomainModel):
    seed: int = 42
    n_regions: int = Field(default=5, ge=1, le=5)
    n_warehouses: int = Field(default=3, ge=1)
    n_skus: int = Field(default=40, ge=5)
    n_suppliers: int = Field(default=10, ge=6)
    n_weeks: int = Field(default=104, ge=26)
    start_date: date = date(2023, 1, 2)
    target_sales_orders: int = Field(default=20_000, ge=100)
    min_offers_per_sku: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> SyntheticConfig:
        if self.start_date.weekday() != 0:
            raise ValueError("start_date must be a Monday (weekly periods start on Monday)")
        if self.n_warehouses > self.n_regions:
            raise ValueError("n_warehouses must not exceed n_regions")
        return self

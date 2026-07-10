from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field

from .base import DomainModel, UtcDatetime


class ScenarioType(StrEnum):
    DEMAND_SHOCK = "DEMAND_SHOCK"
    SUPPLIER_OUTAGE = "SUPPLIER_OUTAGE"
    PRICE_SHOCK = "PRICE_SHOCK"
    CAPACITY_REDUCTION = "CAPACITY_REDUCTION"
    LEAD_TIME_SHOCK = "LEAD_TIME_SHOCK"
    WAREHOUSE_CAPACITY_REDUCTION = "WAREHOUSE_CAPACITY_REDUCTION"
    TRANSPORT_COST_SHOCK = "TRANSPORT_COST_SHOCK"


class Scenario(DomainModel):
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scenario_type: ScenarioType
    parameters: dict[str, float | str] = Field(
        default_factory=dict,
        description="Type-specific parameters, e.g. {'sku_id': 'SKU-001', 'factor': 1.2}.",
    )
    created_at: UtcDatetime


class PurchaseLine(DomainModel):
    supplier_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price: float = Field(gt=0)
    shipping_cost: float = Field(ge=0)


class Citation(DomainModel):
    document_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class RecommendationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Recommendation(DomainModel):
    recommendation_id: str = Field(min_length=1)
    created_at: UtcDatetime
    summary: str = Field(min_length=1)
    lines: tuple[PurchaseLine, ...]
    objective_value: float
    expected_service_level: float = Field(ge=0, le=1)
    assumptions: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    scenario_id: str | None = None
    horizon_start: date
    horizon_end: date
    status: RecommendationStatus = RecommendationStatus.PROPOSED


class DecisionOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Decision(DomainModel):
    decision_id: str = Field(min_length=1)
    recommendation_id: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)
    outcome: DecisionOutcome
    decided_at: UtcDatetime
    rationale: str | None = None

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field

from scm_common.domain import DecisionOutcome, ScenarioType

from .contracts import WireModel

ENGINE_SCHEMA_VERSION = "1"
MAX_HORIZON_WEEKS = 8


class ActorRef(WireModel):
    user_id: str = Field(min_length=1)
    role: str = Field(min_length=1)


class EngineRequest(WireModel):
    schema_version: Literal["1"] = ENGINE_SCHEMA_VERSION  # type: ignore[assignment]
    actor: ActorRef


class SupplierSearchRequest(EngineRequest):
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    max_lead_time_days: int = Field(default=28, ge=0, le=365)
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)


class SupplierPerformanceRequest(EngineRequest):
    supplier_id: str = Field(min_length=1)


class PlanSpec(WireModel):
    sku_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)
    demand_multiplier: float = Field(default=1.0, gt=0, le=5)
    budget: float | None = Field(default=None, gt=0)
    service_level: float = Field(default=0.95, ge=0.5, le=1.0)


class OptimizeRequest(EngineRequest, PlanSpec):
    pass


class ScenarioRunRequest(EngineRequest):
    plan: PlanSpec
    scenario_type: ScenarioType
    parameters: dict[str, float | str] = Field(default_factory=dict)


class DocumentQuestionRequest(EngineRequest):
    question: str = Field(min_length=3, max_length=500)


class AgentTaskRequest(EngineRequest):
    text: str = Field(min_length=1, max_length=4000)


class ApprovalDecisionRequest(EngineRequest):
    outcome: DecisionOutcome
    rationale: str | None = Field(default=None, max_length=500)


MAX_OUTCOME_RECORDS = 50_000


class ForecastSnapshotRequest(EngineRequest):
    sku_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    as_of: date
    horizon_weeks: int = Field(default=4, ge=1, le=MAX_HORIZON_WEEKS)


class ForecastPointRecord(WireModel):
    sku_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    week_start: date
    horizon: int = Field(ge=1)
    point: float = Field(ge=0)
    lower: float = Field(ge=0)
    upper: float = Field(ge=0)


class DemandRecord(WireModel):
    sku_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    week_start: date
    quantity: float = Field(ge=0)


class DeliveryRecord(WireModel):
    po_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    ordered_quantity: int = Field(ge=1)
    expected_delivery: date
    delivered_on: date | None = None
    delivered_quantity: int | None = Field(default=None, ge=0)
    promised_reliability: float | None = Field(default=None, ge=0, le=1)


class InventoryRecord(WireModel):
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    week_start: date
    on_hand: float = Field(ge=0)
    unmet_units: float = Field(default=0, ge=0)


class OutcomeEvaluationRequest(EngineRequest):
    forecasts: tuple[ForecastPointRecord, ...] = Field(default=(), max_length=MAX_OUTCOME_RECORDS)
    demand: tuple[DemandRecord, ...] = Field(default=(), max_length=MAX_OUTCOME_RECORDS)
    deliveries: tuple[DeliveryRecord, ...] = Field(default=(), max_length=MAX_OUTCOME_RECORDS)
    inventory: tuple[InventoryRecord, ...] = Field(default=(), max_length=MAX_OUTCOME_RECORDS)


class EngineResponse(WireModel):
    schema_version: Literal["1"] = ENGINE_SCHEMA_VERSION  # type: ignore[assignment]
    data: dict[str, Any]

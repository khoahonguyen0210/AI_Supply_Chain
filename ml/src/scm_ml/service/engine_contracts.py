"""Wire contracts of the planning-engine endpoints (version 1; JSON uses camelCase).

Requests are typed and validated. Responses wrap the engine result in `data`: the shape of `data`
is the documented output of the corresponding agent tool (docs/contracts/engine-api.md), so the
business logic exists once, in Python, and Java only relays it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from scm_common.domain import DecisionOutcome, ScenarioType

from .contracts import WireModel

ENGINE_SCHEMA_VERSION = "1"
MAX_HORIZON_WEEKS = 8


class ActorRef(WireModel):
    """The authenticated human a request runs for; authentication itself is the backend's job."""

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


class EngineResponse(WireModel):
    schema_version: Literal["1"] = ENGINE_SCHEMA_VERSION  # type: ignore[assignment]
    data: dict[str, Any]

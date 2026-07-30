"""Planning-engine use cases behind the service: every call runs through the agent's guarded tools.

Tools are the single implementation of supplier search, optimization, scenarios and policy answers.
This module only authorizes, validates and result-checks a call the same way the agent runtime does,
and turns failures into stable error codes. A lock serializes calls because the planning context and
the state store are shared, mutable and not thread-safe.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from pydantic.alias_generators import to_camel

from scm_ml.agent.approval import ApprovalError, ApprovalPolicy, ApprovalService
from scm_ml.agent.context import PlanningContext, build_planning_context
from scm_ml.agent.guardrails import GuardrailError, authorize, check_tool_result, validate_arguments
from scm_ml.agent.models import Actor, AgentRun, ToolContext, ToolError, ToolSpec
from scm_ml.agent.planner import ClaudePlanner, Planner, RulePlanner
from scm_ml.agent.runner import AgentRunner
from scm_ml.agent.state import ApprovalStatus, SqliteStateStore
from scm_ml.agent.tools import default_registry
from scm_ml.forecast.panel import panel_from_world
from scm_ml.knowledge import (
    ClaudeGenerator,
    Embedder,
    FastEmbedEmbedder,
    HashingEmbedder,
    build_corpus,
)
from scm_ml.llm import ClaudeJsonLlm
from scm_ml.synthetic import SyntheticWorld

from .engine_contracts import (
    ActorRef,
    AgentTaskRequest,
    ApprovalDecisionRequest,
    DocumentQuestionRequest,
    OptimizeRequest,
    PlanSpec,
    ScenarioRunRequest,
    SupplierSearchRequest,
)
from .forecasting import ForecastService

_STATUS_BY_CODE = {
    "NOT_AUTHORIZED": 403,
    "SELF_APPROVAL": 403,
    "DUPLICATE_APPROVER": 403,
    "ALREADY_DECIDED": 409,
    "ALREADY_REQUESTED": 409,
}


class EngineError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _status_for(code: str) -> int:
    if code in _STATUS_BY_CODE:
        return _STATUS_BY_CODE[code]
    return 404 if code.startswith("UNKNOWN_") else 422


_SNAKE_KEY = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)+")


def camelize(value: Any) -> Any:
    """Recursively convert snake_case object keys to the wire's camelCase.

    Keys that are data (supplier ids like `SUP-1`) are not snake_case identifiers and stay as is.
    """
    if isinstance(value, dict):
        return {
            to_camel(k) if isinstance(k, str) and _SNAKE_KEY.fullmatch(k) else k: camelize(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [camelize(v) for v in value]
    return value


def _wire(value: dict[str, Any]) -> dict[str, Any]:
    wired: dict[str, Any] = camelize(value)
    return wired


class EngineService:
    def __init__(
        self,
        planning: PlanningContext,
        runner: AgentRunner,
        approvals: ApprovalService,
        store: SqliteStateStore,
        tools: dict[str, ToolSpec] | None = None,
    ) -> None:
        self._planning, self._runner = planning, runner
        self._approvals, self._store = approvals, store
        self._tools = tools if tools is not None else default_registry()
        self._lock = threading.RLock()

    def info(self) -> dict[str, Any]:
        return {
            "asOf": self._planning.as_of.isoformat(),
            "skus": len(self._planning.catalog.skus),
            "suppliers": len(self._planning.catalog.suppliers),
            "warehouses": len(self._planning.catalog.warehouses),
            "tools": sorted(self._tools),
        }

    def _invoke(self, name: str, actor: ActorRef, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools[name]
        who = Actor(user_id=actor.user_id, role=actor.role)
        try:
            authorize(spec, who)
            args = validate_arguments(spec, arguments)
            context = ToolContext(self._planning, who, self._approvals, [])
            result = spec.handler(context, args)
        except GuardrailError as error:
            raise EngineError(_status_for(error.code), error.code, error.message) from error
        except ToolError as error:
            raise EngineError(_status_for(error.code), error.code, error.message) from error
        problems = check_tool_result(name, arguments, result)
        if problems:
            raise EngineError(500, "INVALID_RESULT", "; ".join(problems[:3]))
        return result

    def search_suppliers(self, request: SupplierSearchRequest) -> dict[str, Any]:
        arguments = request.model_dump(
            exclude={"schema_version", "actor"}, mode="json", by_alias=False
        )
        with self._lock:
            return _wire(self._invoke("search_suppliers", request.actor, arguments))

    def optimize(self, request: OptimizeRequest) -> dict[str, Any]:
        arguments = request.model_dump(
            exclude={"schema_version", "actor"}, mode="json", by_alias=False
        )
        with self._lock:
            return _wire(self._invoke("optimize_procurement", request.actor, arguments))

    def run_scenario(self, request: ScenarioRunRequest) -> dict[str, Any]:
        """Solve the plan afresh, then stress it: callers never depend on server-side plan ids."""
        with self._lock:
            plan = self._invoke("optimize_procurement", request.actor, _plan_args(request.plan))
            scenario = self._invoke(
                "run_scenario",
                request.actor,
                {
                    "plan_id": plan["plan_id"],
                    "scenario_type": request.scenario_type.value,
                    "parameters": request.parameters,
                },
            )
            return _wire({"plan": plan, "scenario": scenario})

    def ask_documents(self, request: DocumentQuestionRequest) -> dict[str, Any]:
        with self._lock:
            return _wire(
                self._invoke("search_policies", request.actor, {"question": request.question})
            )

    def run_agent(self, request: AgentTaskRequest) -> dict[str, Any]:
        with self._lock:
            run: AgentRun = self._runner.run(
                request.text, Actor(user_id=request.actor.user_id, role=request.actor.role)
            )
        return _wire(run.model_dump(mode="json"))

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._store.load_task(task_id)
        if record is None:
            raise EngineError(404, "UNKNOWN_TASK", f"no task {task_id}")
        return _wire(record.model_dump(mode="json"))

    def list_approvals(self, status: str | None) -> list[dict[str, Any]]:
        try:
            wanted = ApprovalStatus(status) if status else None
        except ValueError:
            raise EngineError(422, "INVALID_STATUS", f"unknown approval status {status}") from None
        with self._lock:
            records = self._store.approvals(wanted)
        return [camelize(r.model_dump(mode="json")) for r in records]

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                record = self._approvals.get(approval_id)
            except ApprovalError as error:
                raise EngineError(_status_for(error.code), error.code, error.message) from error
        return _wire(record.model_dump(mode="json"))

    def decide_approval(self, approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
        approver = Actor(user_id=request.actor.user_id, role=request.actor.role)
        with self._lock:
            try:
                record = self._approvals.decide(
                    approval_id, approver, request.outcome, request.rationale
                )
            except ApprovalError as error:
                raise EngineError(_status_for(error.code), error.code, error.message) from error
        return _wire(record.model_dump(mode="json"))


def _plan_args(plan: PlanSpec) -> dict[str, Any]:
    return plan.model_dump(mode="json", by_alias=False)


def build_engine(
    world: SyntheticWorld,
    forecasts: ForecastService,
    *,
    planner_name: str = "rule",
    embedder_name: str = "hashing",
    state_path: Path | str = ":memory:",
) -> EngineService:
    """Wire knowledge base, planner, approvals and durable state around one world and model."""
    if panel_from_world(world).dataset_id != forecasts.history.dataset_id:
        raise ValueError("the forecast model was not trained on this world's demand history")
    embedder: Embedder = FastEmbedEmbedder() if embedder_name == "fastembed" else HashingEmbedder()
    llm = ClaudeJsonLlm() if planner_name == "claude" else None
    planning = build_planning_context(
        world, forecasts, embedder=embedder, generator=ClaudeGenerator(llm) if llm else None
    )
    planner: Planner = ClaudePlanner(llm, default_registry()) if llm else RulePlanner(planning)
    store = SqliteStateStore(state_path)
    approvals = ApprovalService(
        store, ApprovalPolicy.from_documents(build_corpus(world).documents, planning.as_of)
    )
    runner = AgentRunner(planning, planner, store, approvals)
    return EngineService(planning, runner, approvals, store)

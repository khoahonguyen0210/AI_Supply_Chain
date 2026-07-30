from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from scm_common.domain import DomainModel

Handler = Callable[["ToolContext", Any], dict[str, Any]]


class Actor(DomainModel):
    """The authenticated human a task runs for; the agent never acts on its own authority."""

    user_id: str = Field(min_length=1)
    role: str = Field(min_length=1)


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    allowed_roles: frozenset[str]
    consequential: bool = False

    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


class TaskStatus(StrEnum):
    COMPLETED = "COMPLETED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REFUSED = "REFUSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAILED = "FAILED"


class TraceKind(StrEnum):
    TOOL_CALL = "TOOL_CALL"
    FINAL = "FINAL"
    REFUSAL = "REFUSAL"
    CLARIFICATION = "CLARIFICATION"


class TraceStep(DomainModel):
    index: int = Field(ge=0)
    kind: TraceKind
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    replan: bool = Field(default=False, description="This step adjusts the plan after a result.")
    ok: bool = True
    error_code: str | None = None
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class AgentRun(DomainModel):
    task_id: str
    status: TaskStatus
    answer: str
    trace: tuple[TraceStep, ...]
    recommendation_id: str | None = None
    approval_id: str | None = None
    citations: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    violations: tuple[str, ...] = Field(
        default=(), description="Guardrail findings raised while running the task."
    )


@dataclass
class ToolContext:
    planning: Any
    actor: Actor
    approvals: Any
    observations: list[TraceStep]
    task_id: str = ""

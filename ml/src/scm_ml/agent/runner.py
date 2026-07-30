"""The agent loop: task -> plan -> guarded tool call -> observation -> re-plan -> final answer.

The runner owns everything the planner must not decide for itself: it validates the request,
authorizes and validates each tool call, sanity-checks results, rejects final answers whose numbers
are not backed by tool results, records a trace, persists task state and caps the number of steps.
"""

from __future__ import annotations

import json
from typing import Any

from .approval import ApprovalService
from .context import PlanningContext
from .guardrails import (
    GuardrailError,
    authorize,
    check_tool_result,
    check_unsafe_request,
    clean_task_text,
    evidence_numbers,
    unsupported_numbers,
    validate_arguments,
)
from .models import (
    Actor,
    AgentRun,
    TaskStatus,
    ToolContext,
    ToolError,
    ToolSpec,
    TraceKind,
    TraceStep,
)
from .planner import AgentState, CallTool, Clarify, Finish, Planner, Refuse
from .state import SqliteStateStore, TaskRecord, now_utc
from .tools import default_registry

MAX_STEPS = 24
MAX_REJECTED_ANSWERS = 2
RESULT_SUMMARY_CHARS = 160


class AgentRunner:
    def __init__(
        self,
        planning: PlanningContext,
        planner: Planner,
        store: SqliteStateStore,
        approvals: ApprovalService,
        *,
        tools: dict[str, ToolSpec] | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self._planning, self._planner = planning, planner
        self._store, self._approvals = store, approvals
        self._tools = tools if tools is not None else default_registry()
        self._max_steps = max_steps
        self._entity_text = " ".join(
            [s.name for s in planning.catalog.skus.values()]
            + [s.name for s in planning.catalog.suppliers.values()]
        )

    def run(self, text: str, actor: Actor) -> AgentRun:
        task_id = f"TASK-{self._store.next_task_number():04d}"
        created = now_utc()
        record = TaskRecord(
            task_id=task_id,
            user_id=actor.user_id,
            role=actor.role,
            text=text[:2000],
            created_at=created,
            updated_at=created,
        )
        self._store.save_task(record)
        trace: list[TraceStep] = []
        violations: list[str] = []

        try:
            clean = clean_task_text(text)
            check_unsafe_request(clean)
        except GuardrailError as violation:
            violations.append(violation.code)
            trace.append(
                TraceStep(
                    index=0,
                    kind=TraceKind.REFUSAL,
                    ok=False,
                    error_code=violation.code,
                    summary=violation.message,
                )
            )
            return self._finish(record, trace, TaskStatus.REFUSED, violation.message, violations)

        state = AgentState(task=clean, actor=actor)
        context = ToolContext(
            self._planning, actor, self._approvals, state.observations, task_id=task_id
        )
        seen: set[str] = set()
        rejected = 0
        for _ in range(self._max_steps):
            try:
                action = self._planner.next_action(state)
            except Exception as error:  # a planner failure must not crash the service
                violations.append("PLANNER_FAILURE")
                return self._finish(
                    record,
                    trace,
                    TaskStatus.FAILED,
                    f"The planner failed ({type(error).__name__}); no action was taken.",
                    violations,
                )
            if isinstance(action, Refuse):
                trace.append(
                    TraceStep(index=len(trace), kind=TraceKind.REFUSAL, summary=action.reason)
                )
                return self._finish(record, trace, TaskStatus.REFUSED, action.reason, violations)
            if isinstance(action, Clarify):
                trace.append(
                    TraceStep(
                        index=len(trace), kind=TraceKind.CLARIFICATION, summary=action.question
                    )
                )
                return self._finish(
                    record, trace, TaskStatus.NEEDS_CLARIFICATION, action.question, violations
                )
            if isinstance(action, Finish):
                problems = unsupported_numbers(
                    action.text,
                    evidence_numbers(state.observations, f"{clean} {self._entity_text}"),
                )
                if problems:
                    rejected += 1
                    violations.append(f"UNSUPPORTED_NUMBERS: {', '.join(problems[:5])}")
                    state.feedback.append(
                        f"Final answer rejected: numbers not found in tool results: "
                        f"{', '.join(problems[:5])}. Use only tool-reported values."
                    )
                    if rejected > MAX_REJECTED_ANSWERS:
                        return self._finish(
                            record,
                            trace,
                            TaskStatus.FAILED,
                            "I could not produce an answer whose numbers are all backed by tool "
                            "results, so I am not giving one.",
                            violations,
                        )
                    continue
                trace.append(TraceStep(index=len(trace), kind=TraceKind.FINAL, summary="answer"))
                return self._finish(
                    record,
                    trace,
                    self._final_status(state),
                    action.text,
                    violations,
                    assumptions=action.assumptions,
                    observations=state.observations,
                )
            assert isinstance(action, CallTool)
            key = json.dumps([action.tool, action.arguments], sort_keys=True, default=str)
            if key in seen:
                violations.append("REPEATED_CALL")
                return self._finish(
                    record,
                    trace,
                    TaskStatus.FAILED,
                    f"The planner repeated an identical {action.tool} call; stopping.",
                    violations,
                )
            seen.add(key)
            step = self._execute(action, actor, context, len(trace), violations)
            trace.append(step)
            state.observations.append(step)
            record = record.model_copy(update={"steps": tuple(trace), "updated_at": now_utc()})
            self._store.save_task(record)
        return self._finish(
            record,
            trace,
            TaskStatus.FAILED,
            "The task needed more steps than allowed; stopping without an answer.",
            violations + ["MAX_STEPS"],
        )

    def _execute(
        self,
        action: CallTool,
        actor: Actor,
        context: ToolContext,
        index: int,
        violations: list[str],
    ) -> TraceStep:
        base: dict[str, Any] = {
            "index": index,
            "kind": TraceKind.TOOL_CALL,
            "tool": action.tool,
            "arguments": action.arguments,
            "reason": action.reason,
            "replan": action.replan,
        }
        spec = self._tools.get(action.tool)
        if spec is None:
            violations.append("UNKNOWN_TOOL")
            return TraceStep(
                **base, ok=False, error_code="UNKNOWN_TOOL", summary=f"no tool named {action.tool}"
            )
        try:
            authorize(spec, actor)
            args = validate_arguments(spec, action.arguments)
        except GuardrailError as violation:
            violations.append(violation.code)
            return TraceStep(**base, ok=False, error_code=violation.code, summary=violation.message)
        try:
            result = spec.handler(context, args)
        except ToolError as error:
            return TraceStep(**base, ok=False, error_code=error.code, summary=error.message)
        except Exception as error:
            violations.append("TOOL_FAILURE")
            return TraceStep(
                **base,
                ok=False,
                error_code="TOOL_FAILURE",
                summary=f"{action.tool} failed unexpectedly ({type(error).__name__})",
            )
        problems = check_tool_result(action.tool, action.arguments, result)
        if problems:
            violations.append("INVALID_RESULT")
            return TraceStep(
                **base,
                ok=False,
                error_code="INVALID_RESULT",
                summary="result rejected: " + "; ".join(problems[:3]),
            )
        return TraceStep(
            **base, summary=json.dumps(result, default=str)[:RESULT_SUMMARY_CHARS], result=result
        )

    @staticmethod
    def _final_status(state: AgentState) -> TaskStatus:
        pending = any(s.tool == "prepare_purchase_order" and s.ok for s in state.observations)
        return TaskStatus.AWAITING_APPROVAL if pending else TaskStatus.COMPLETED

    def _finish(
        self,
        record: TaskRecord,
        trace: list[TraceStep],
        status: TaskStatus,
        answer: str,
        violations: list[str],
        *,
        assumptions: tuple[str, ...] = (),
        observations: list[TraceStep] | None = None,
    ) -> AgentRun:
        observations = observations or []
        po = next(
            (s.result for s in observations if s.tool == "prepare_purchase_order" and s.ok), {}
        )
        citations: dict[tuple[str, str], dict[str, Any]] = {}
        for step in observations:
            if step.tool == "search_policies" and step.ok:
                for c in step.result.get("citations", []):
                    citations.setdefault((c["document_id"], c["version"]), c)
        self._store.save_task(
            record.model_copy(
                update={
                    "status": status,
                    "steps": tuple(trace),
                    "answer": answer,
                    "updated_at": now_utc(),
                }
            )
        )
        return AgentRun(
            task_id=record.task_id,
            status=status,
            answer=answer,
            trace=tuple(trace),
            recommendation_id=po.get("recommendation_id"),
            approval_id=po.get("approval_id"),
            citations=tuple(citations.values()),
            assumptions=assumptions,
            violations=tuple(violations),
        )

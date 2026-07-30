"""Guardrails: deterministic checks around the planner, enforced whatever model plans.

* input validation and refusal of requests that ask to bypass approval or the rules;
* authorization of each tool call against the actor's role;
* strict validation of tool arguments;
* sanity checks on tool results before a planner may rely on them;
* numerical grounding: every number in a final answer must come from a tool result, the policy
  evidence or the user's own message.

Document permission filtering lives in retrieval (a role never receives chunks it may not read);
action confirmation is structural: no tool can approve, and the only consequential tool opens an
approval request.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ValidationError

from .models import Actor, ToolSpec, TraceStep

MAX_TASK_CHARS = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UNSAFE: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(skip|bypass|avoid|waive|without|no need for)\b.{0,30}"
            r"\b(approval|approver|sign[- ]?off)",
            re.I,
        ),
        "APPROVAL_BYPASS",
        "I can't skip or bypass human approval; purchase orders need the approvers the policy "
        "requires.",
    ),
    (
        re.compile(
            r"\b(approve|sign off on|authori[sz]e)\b.{0,30}\b(it|this|that|the (order|po|plan))\b"
            r".{0,20}\b(yourself|for me|right now|immediately)\b",
            re.I,
        ),
        "SELF_APPROVAL",
        "I can't approve orders. I can prepare a recommendation and request approval from the "
        "people authorised to give it.",
    ),
    (
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,25}\b(instructions|rules|polic(y|ies)|"
            r"guardrails?|permissions?|restrictions?)",
            re.I,
        ),
        "RULE_OVERRIDE",
        "I can't ignore the rules, policies or permissions that apply to this request.",
    ),
    (
        re.compile(
            r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|hidden instructions)", re.I
        ),
        "PROMPT_EXTRACTION",
        "I can't share my internal instructions.",
    ),
)


class GuardrailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def clean_task_text(text: str) -> str:
    """Strip control characters and bound the length; reject empty input."""
    cleaned = _CONTROL.sub(" ", text).strip()
    if not cleaned:
        raise GuardrailError("EMPTY_TASK", "Please describe what you want help with.")
    if len(cleaned) > MAX_TASK_CHARS:
        raise GuardrailError(
            "TASK_TOO_LONG", f"Please keep the request under {MAX_TASK_CHARS} characters."
        )
    return cleaned


def check_unsafe_request(text: str) -> None:
    for pattern, code, message in _UNSAFE:
        if pattern.search(text):
            raise GuardrailError(code, message)


def authorize(spec: ToolSpec, actor: Actor) -> None:
    if actor.role not in spec.allowed_roles:
        raise GuardrailError("NOT_AUTHORIZED", f"role {actor.role} may not use {spec.name}")


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> Any:
    try:
        return spec.args_model.model_validate(arguments)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
            for e in error.errors()
        )
        raise GuardrailError("INVALID_ARGUMENTS", problems) from None


def _numeric_leaves(value: Any, path: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield path, float(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _numeric_leaves(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _numeric_leaves(item, path)


def check_tool_result(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Problems that make a result unfit to report: non-finite or impossible values."""
    problems: list[str] = []
    for path, number in _numeric_leaves(result):
        leaf = path.rsplit(".", 1)[-1]
        if not math.isfinite(number):
            problems.append(f"{path} is not finite")
        elif leaf.endswith("rate") and not 0.0 <= number <= 1.0:
            problems.append(f"{path}={number} is outside [0, 1]")
        elif leaf in {"units", "quantity", "on_hand", "incoming", "unmet_demand"} and number < 0:
            problems.append(f"{path}={number} is negative")
    budget = result.get("budget")
    if budget is not None and result.get("spend", 0) > budget * (1 + 1e-6):
        problems.append(f"spend {result['spend']} exceeds the budget {budget}")
    return problems


_ID = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z0-9]+)+\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MARKER = re.compile(r"\[S\d+\]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def evidence_numbers(observations: Sequence[TraceStep], extra_text: str = "") -> list[float]:
    """Every number a tool returned (or a policy answer quoted) plus those in the user's message."""
    values: list[float] = []
    texts = [extra_text]
    for step in observations:
        if not step.ok:
            continue
        values.extend(v for _, v in _numeric_leaves(step.result))
        texts.extend(_strings(step.result))
    for text in texts:
        values.extend(_parse_numbers(text))
    return values


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _parse_numbers(text: str) -> list[float]:
    cleaned = _MARKER.sub(" ", _DATE.sub(" ", _ID.sub(" ", text)))
    out: list[float] = []
    for token in _NUMBER.findall(cleaned):
        out.append(float(token.rstrip("%").replace(",", "")))
    return out


def unsupported_numbers(text: str, evidence: Sequence[float]) -> list[str]:
    """Numbers in `text` that match no evidence value at the precision they are written."""
    cleaned = _MARKER.sub(" ", _DATE.sub(" ", _ID.sub(" ", text)))
    bad: list[str] = []
    for token in _NUMBER.findall(cleaned):
        raw = token.rstrip("%").replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        shown = float(raw)
        scales = (1.0, 100.0) if token.endswith("%") else (1.0,)
        if not any(
            math.isclose(round(v * scale, decimals), shown, abs_tol=10**-decimals / 2 * 1e-6)
            for v in evidence
            for scale in scales
        ):
            bad.append(token)
    return bad

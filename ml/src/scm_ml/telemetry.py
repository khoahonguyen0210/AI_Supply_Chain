"""Runtime telemetry of the planning engine: what actually happened while serving requests.

Counts and latencies of forecasts, tool calls, retrieval answers, agent tasks and model calls, kept
in process and exposed as a JSON snapshot. Nothing here measures quality against ground truth (that
is the offline evaluation, summarised separately); it shows rates of success, refusal and guardrail
findings in live traffic, plus model latency and token use. Cost is reported only when per-token
prices are configured, because a price must not be invented.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

WINDOW = 1000
"""Latency samples kept per series; percentiles describe the most recent WINDOW observations."""


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    rank = max(0, min(len(sorted_values) - 1, math.ceil(fraction * len(sorted_values)) - 1))
    return sorted_values[rank]


@dataclass
class _Series:
    """Count, failures and recent latencies of one kind of operation."""

    count: int = 0
    failures: int = 0
    total_seconds: float = 0.0
    recent: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    def add(self, seconds: float, ok: bool) -> None:
        self.count += 1
        self.failures += 0 if ok else 1
        self.total_seconds += seconds
        self.recent.append(seconds)

    def snapshot(self) -> dict[str, Any]:
        ordered = sorted(self.recent)
        return {
            "count": self.count,
            "failures": self.failures,
            "failureRate": self.failures / self.count if self.count else 0.0,
            "meanMillis": 1000 * self.total_seconds / self.count if self.count else 0.0,
            "p50Millis": 1000 * _percentile(ordered, 0.5),
            "p95Millis": 1000 * _percentile(ordered, 0.95),
        }


@dataclass(frozen=True)
class Prices:
    """USD per million tokens, from the environment; absent means cost is not reported."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    @classmethod
    def from_environment(cls) -> Prices:
        def read(name: str) -> float | None:
            raw = os.environ.get(name)
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        return cls(read("SCM_LLM_PRICE_INPUT_PER_MTOK"), read("SCM_LLM_PRICE_OUTPUT_PER_MTOK"))


class Telemetry:
    def __init__(self, prices: Prices | None = None) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._prices = prices or Prices.from_environment()
        self._forecasts = _Series()
        self._tools: dict[str, _Series] = defaultdict(_Series)
        self._tool_errors: Counter[str] = Counter()
        self._tasks = _Series()
        self._task_status: Counter[str] = Counter()
        self._guardrails: Counter[str] = Counter()
        self._retrieval: dict[str, int] = defaultdict(int)
        self._answers = _Series()
        self._models: dict[str, _Series] = defaultdict(_Series)
        self._tokens: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    @contextmanager
    def timed(self) -> Iterator[list[float]]:
        """Yields a one-item list that receives the elapsed seconds when the block ends."""
        box = [0.0]
        start = time.perf_counter()
        try:
            yield box
        finally:
            box[0] = time.perf_counter() - start

    def forecast(self, seconds: float, ok: bool) -> None:
        with self._lock:
            self._forecasts.add(seconds, ok)

    def tool_call(self, tool: str, seconds: float, ok: bool, error_code: str | None = None) -> None:
        with self._lock:
            self._tools[tool].add(seconds, ok)
            if not ok and error_code:
                self._tool_errors[f"{tool}:{error_code}"] += 1

    def task(self, status: str, seconds: float, violations: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._tasks.add(seconds, status in {"COMPLETED", "AWAITING_APPROVAL"})
            self._task_status[status] += 1
            for violation in violations:
                self._guardrails[violation.split(":")[0]] += 1

    def answer(self, status: str, seconds: float) -> None:
        """A policy answer; `status` is ANSWERED, INSUFFICIENT_EVIDENCE, CONFLICTING, etc."""
        with self._lock:
            self._retrieval[status] += 1
            self._answers.add(seconds, status == "ANSWERED")

    def model_call(
        self,
        model: str,
        seconds: float,
        ok: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        with self._lock:
            self._models[model].add(seconds, ok)
            self._tokens[model][0] += input_tokens
            self._tokens[model][1] += output_tokens

    def _cost(self, input_tokens: int, output_tokens: int) -> float | None:
        p = self._prices
        if p.input_per_mtok is None or p.output_per_mtok is None:
            return None
        return (input_tokens * p.input_per_mtok + output_tokens * p.output_per_mtok) / 1_000_000

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tools = {name: series.snapshot() for name, series in sorted(self._tools.items())}
            tool_calls = sum(s.count for s in self._tools.values())
            tool_ok = tool_calls - sum(s.failures for s in self._tools.values())
            models = {}
            for model, series in sorted(self._models.items()):
                tokens_in, tokens_out = self._tokens[model]
                models[model] = {
                    **series.snapshot(),
                    "inputTokens": tokens_in,
                    "outputTokens": tokens_out,
                    "estimatedCostUsd": self._cost(tokens_in, tokens_out),
                }
            answered = sum(self._retrieval.values())
            return {
                "uptimeSeconds": time.monotonic() - self._started,
                "forecast": self._forecasts.snapshot(),
                "tools": {
                    "calls": tool_calls,
                    "successRate": tool_ok / tool_calls if tool_calls else None,
                    "byTool": tools,
                    "errors": dict(self._tool_errors),
                },
                "agent": {
                    **self._tasks.snapshot(),
                    "byStatus": dict(self._task_status),
                    "guardrailFindings": dict(self._guardrails),
                },
                "retrieval": {
                    **self._answers.snapshot(),
                    "byStatus": dict(self._retrieval),
                    "answeredShare": self._retrieval.get("ANSWERED", 0) / answered
                    if answered
                    else None,
                },
                "models": models,
                "costNote": (
                    "estimatedCostUsd is computed from SCM_LLM_PRICE_INPUT_PER_MTOK / "
                    "SCM_LLM_PRICE_OUTPUT_PER_MTOK"
                    if self._prices.input_per_mtok is not None
                    else "cost is not reported: no per-token prices are configured"
                ),
            }

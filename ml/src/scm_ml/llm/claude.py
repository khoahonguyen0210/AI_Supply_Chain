"""Claude implementation of `JsonLlm` using the Anthropic SDK and structured outputs.

The API key is read from `ANTHROPIC_API_KEY` by the SDK; nothing here stores or logs it. The client
is injectable so tests run without a key or network access.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import anthropic
from anthropic.types import OutputConfigParam

from scm_ml.telemetry import Telemetry

from .base import LlmError

DEFAULT_MODEL = "claude-opus-5-5"


class ClaudeJsonLlm:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium",
        client: anthropic.Anthropic | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._telemetry = telemetry
        self.name = model
        self._model = model
        self._effort = effort
        self._client = client if client is not None else anthropic.Anthropic()

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]:
        output_config: OutputConfigParam = {
            "effort": self._effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        started = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        except anthropic.APIError as error:
            self._record(started, ok=False)
            raise LlmError(f"Claude API call failed: {error}") from error
        usage = getattr(response, "usage", None)
        self._record(
            started,
            ok=response.stop_reason not in {"refusal", "max_tokens"},
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
        if response.stop_reason == "refusal":
            raise LlmError("Claude declined the request")
        if response.stop_reason == "max_tokens":
            raise LlmError("Claude response was truncated")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise LlmError("Claude returned no text block")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise LlmError("Claude returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise LlmError("Claude returned JSON that is not an object")
        return parsed

    def _record(
        self, started: float, *, ok: bool, input_tokens: int = 0, output_tokens: int = 0
    ) -> None:
        if self._telemetry is not None:
            self._telemetry.model_call(
                self._model, time.perf_counter() - started, ok, input_tokens, output_tokens
            )

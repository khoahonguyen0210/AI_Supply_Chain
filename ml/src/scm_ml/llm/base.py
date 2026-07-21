from __future__ import annotations

from typing import Any, Protocol


class LlmError(RuntimeError): ...


class JsonLlm(Protocol):
    name: str

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]:
        """Return one JSON object conforming to `schema`, or raise `LlmError`."""
        ...

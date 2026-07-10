from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""A timezone-aware timestamp, normalised to UTC."""


class DomainModel(BaseModel):
    """Immutable, strict model: unknown fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from scm_common.domain import DomainModel

FORECAST_SCHEMA_VERSION = "1"


class WireModel(DomainModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ForecastRequest(WireModel):
    schema_version: Literal["1"] = FORECAST_SCHEMA_VERSION  # type: ignore[assignment]
    sku_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    as_of: date = Field(
        description="Monday of the first week to forecast; history before it is used."
    )
    horizon_weeks: int = Field(default=8, ge=1, le=8)


class ForecastPoint(WireModel):
    week_start: date
    horizon: int = Field(ge=1)
    point: float = Field(ge=0)
    lower: float = Field(ge=0)
    upper: float = Field(ge=0)


class ForecastResponse(WireModel):
    schema_version: Literal["1"] = FORECAST_SCHEMA_VERSION  # type: ignore[assignment]
    model_version: str
    dataset_id: str
    sku_id: str
    region_id: str
    as_of: date
    interval_level: float = Field(gt=0, lt=1)
    method: str
    points: tuple[ForecastPoint, ...]


class ErrorResponse(WireModel):
    code: str
    message: str

from __future__ import annotations

from pathlib import Path
from typing import Any

from scm_ml.forecast.inference import forecast_series
from scm_ml.forecast.model import ForecastModel, load_model
from scm_ml.forecast.panel import ForecastPanel, load_dataset

from .contracts import ForecastPoint, ForecastRequest, ForecastResponse

METHOD = "lightgbm-cqr"


class ForecastService:
    def __init__(self, model: ForecastModel, history: ForecastPanel) -> None:
        if model.dataset_id != history.dataset_id:
            raise ValueError("model was not trained on the supplied demand history")
        self.model = model
        self.history = history

    @classmethod
    def from_directories(cls, model_dir: Path, dataset_dir: Path) -> ForecastService:
        history, _ = load_dataset(dataset_dir)
        return cls(load_model(model_dir), history)

    def forecast(self, request: ForecastRequest) -> ForecastResponse:
        result = forecast_series(
            self.model,
            self.history,
            request.sku_id,
            request.region_id,
            request.as_of,
            request.horizon_weeks,
        )
        points = tuple(
            ForecastPoint(
                week_start=week,
                horizon=i + 1,
                point=round(float(result.point[i]), 3),
                lower=round(float(result.lower[i]), 3),
                upper=round(float(result.upper[i]), 3),
            )
            for i, week in enumerate(result.week_starts)
        )
        return ForecastResponse(
            model_version=self.model.version,
            dataset_id=self.model.dataset_id,
            sku_id=request.sku_id,
            region_id=request.region_id,
            as_of=request.as_of,
            interval_level=result.interval_level,
            method=METHOD,
            points=points,
        )

    def info(self) -> dict[str, Any]:
        return {
            "modelVersion": self.model.version,
            "datasetId": self.model.dataset_id,
            "horizons": self.model.config.horizons,
            "historyEnd": self.history.weeks[-1].isoformat(),
            "series": len(self.history.series),
        }

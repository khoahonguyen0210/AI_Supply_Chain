from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .features import MIN_ORIGIN, OriginFeatures
from .metrics import Array
from .model import ForecastModel, predict_scaled
from .panel import ForecastPanel
from .uncertainty import INTERVAL_LEVEL, LOWER, UPPER


class ForecastError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SeriesForecast:
    week_starts: list[date]
    point: Array
    lower: Array
    upper: Array
    interval_level: float


def forecast_series(
    model: ForecastModel,
    panel: ForecastPanel,
    sku_id: str,
    region_id: str,
    first_forecast_week: date,
    horizons: int,
) -> SeriesForecast:
    try:
        series = panel.series.index((sku_id, region_id))
    except ValueError:
        raise ForecastError(
            "UNKNOWN_SERIES", f"no demand history for {sku_id} in {region_id}"
        ) from None
    if horizons < 1 or horizons > model.config.horizons:
        raise ForecastError("INVALID_HORIZON", f"horizon must be 1..{model.config.horizons}")
    if not model.calibration:
        raise ForecastError("MODEL_NOT_CALIBRATED", "model has no calibrated intervals")
    if first_forecast_week.weekday() != 0:
        raise ForecastError("INVALID_AS_OF", "as_of must be a Monday")

    origin = panel.week_index(first_forecast_week) - 1
    if origin >= len(panel.weeks):
        raise ForecastError(
            "HISTORY_TOO_SHORT",
            f"demand history ends {panel.weeks[-1]}; cannot forecast from {first_forecast_week}",
        )
    if origin < MIN_ORIGIN:
        raise ForecastError("HISTORY_TOO_SHORT", "not enough history before as_of")

    values = panel.values[:, : origin + 1]  # nothing after the origin is visible to the model
    features = OriginFeatures(values)
    hs = np.arange(1, horizons + 1, dtype=np.int64)
    idx = np.full(horizons, series, dtype=np.int64)
    origins = np.full(horizons, origin, dtype=np.int64)
    codes = model.codes(panel.series)
    week0 = panel.weeks[0]

    def run(name: str) -> Array:
        return predict_scaled(model, name, features, idx, origins, hs, week0, codes)

    point, low, high = run("point"), run(LOWER), run(UPPER)
    lower, upper = np.minimum(low, high), np.maximum(low, high)
    offsets = np.array([model.calibration["offsets"][str(h)] for h in hs])
    margin = offsets * features.scale[series, origin]
    return SeriesForecast(
        week_starts=[first_forecast_week + timedelta(weeks=int(h) - 1) for h in hs],
        point=point,
        lower=np.minimum(np.maximum(np.minimum(lower, point) - margin, 0.0), point),
        upper=np.maximum(np.maximum(upper, point) + margin, point),
        interval_level=INTERVAL_LEVEL,
    )

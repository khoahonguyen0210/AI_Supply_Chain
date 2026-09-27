from __future__ import annotations

import math
from datetime import date

import numpy as np

from .features import OriginFeatures
from .metrics import Array
from .model import ForecastModel, predict_matrix
from .panel import ForecastPanel, TemporalSplit, split_indices

LOWER, UPPER = "q10", "q90"
QUANTILES = (0.1, 0.9)
INTERVAL_LEVEL = 0.8  # = QUANTILES[1] - QUANTILES[0]


def _scale_matrix(values: Array, start: int, end: int, horizons: int) -> Array:
    scale = OriginFeatures(values).scale
    weeks = np.arange(start, end)
    return np.stack([scale[:, weeks - h] for h in range(1, horizons + 1)], axis=2)


def raw_interval(
    model: ForecastModel,
    values: Array,
    week0: date,
    series: list[tuple[str, str]],
    start: int,
    end: int,
    horizons: int,
) -> tuple[Array, Array, Array]:
    point = predict_matrix(model, "point", values, week0, series, start, end, horizons)
    low = predict_matrix(model, LOWER, values, week0, series, start, end, horizons)
    high = predict_matrix(model, UPPER, values, week0, series, start, end, horizons)
    lower, upper = np.minimum(low, high), np.maximum(low, high)
    return point, np.minimum(lower, point), np.maximum(upper, point)


def fit_offsets(
    model: ForecastModel, panel: ForecastPanel, split: TemporalSplit, horizons: int
) -> dict[str, float]:
    val, test = split_indices(panel, split)
    _, lower, upper = raw_interval(
        model, panel.values, panel.weeks[0], panel.series, val, test, horizons
    )
    actual = panel.values[:, val:test, None]
    scale = _scale_matrix(panel.values, val, test, horizons)
    score = np.maximum(lower - actual, actual - upper) / scale
    offsets: dict[str, float] = {}
    for h in range(horizons):
        n = score[:, :, h].size
        rank = min(math.ceil((n + 1) * INTERVAL_LEVEL), n)
        offsets[str(h + 1)] = float(np.sort(score[:, :, h].reshape(-1))[rank - 1])
    return offsets


def calibrate(
    model: ForecastModel, panel: ForecastPanel, split: TemporalSplit, horizons: int
) -> ForecastModel:
    model.calibration = {
        "method": "cqr",
        "level": INTERVAL_LEVEL,
        "calibration_window": [split.val_start.isoformat(), split.test_start.isoformat()],
        "offsets": fit_offsets(model, panel, split, horizons),
    }
    return model


def predict_interval(
    model: ForecastModel,
    values: Array,
    week0: date,
    series: list[tuple[str, str]],
    start: int,
    end: int,
    horizons: int,
    calibrated: bool = True,
) -> tuple[Array, Array, Array]:
    point, lower, upper = raw_interval(model, values, week0, series, start, end, horizons)
    if not calibrated:
        return point, lower, upper
    if not model.calibration:
        raise ValueError("model has no calibration; run calibrate() first")
    offsets = np.array([model.calibration["offsets"][str(h + 1)] for h in range(horizons)])
    margin = offsets[None, None, :] * _scale_matrix(values, start, end, horizons)
    return (
        point,
        np.minimum(np.maximum(lower - margin, 0.0), point),
        np.maximum(upper + margin, point),
    )

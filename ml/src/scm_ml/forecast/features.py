"""Leakage-safe features: only data up to the origin week is used."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .metrics import Array

LAGS = 8
SEASON = 52
SCALE_WINDOW = 26
MIN_ORIGIN = 12  # earliest origin with enough history for the rolling features
CATEGORICAL = ["sku_code", "region_code"]
FEATURE_NAMES = [
    *(f"lag_{k}" for k in range(LAGS)),
    "mean_4",
    "mean_13",
    "std_13",
    "mean_all",
    "nonzero_13",
    "weeks_since_sale",
    "log_scale",
    "season_lag",
    "season_window",
    "week_of_year",
    "month",
    "horizon",
    *CATEGORICAL,
]

IntArray = NDArray[np.int64]


def _rolling(values: Array, window: int) -> Array:
    cumulative = np.concatenate([np.zeros((values.shape[0], 1)), np.cumsum(values, axis=1)], axis=1)
    ends = np.arange(1, values.shape[1] + 1)
    starts = np.maximum(ends - window, 0)
    means: Array = (cumulative[:, ends] - cumulative[:, starts]) / (ends - starts)
    return means


class OriginFeatures:
    def __init__(self, values: Array) -> None:
        n_series, n_weeks = values.shape
        self.values = values
        self.scale = _rolling(values, SCALE_WINDOW) + 1.0
        self.mean_4 = _rolling(values, 4)
        self.mean_13 = _rolling(values, 13)
        self.std_13 = np.sqrt(np.maximum(_rolling(values**2, 13) - self.mean_13**2, 0.0))
        self.mean_all = _rolling(values, n_weeks)
        self.nonzero_13 = _rolling((values > 0).astype(np.float64), 13)
        since = np.zeros((n_series, n_weeks))
        for t in range(1, n_weeks):
            since[:, t] = np.where(values[:, t] > 0, 0, np.minimum(since[:, t - 1] + 1, SEASON))
        self.weeks_since_sale = since


def make_features(
    origin: OriginFeatures,
    series: IntArray,
    origins: IntArray,
    horizons: IntArray,
    week0: date,
    sku_codes: IntArray,
    region_codes: IntArray,
) -> tuple[pd.DataFrame, Array]:
    values, scale = origin.values, origin.scale[series, origins]
    columns: dict[str, Array | IntArray] = {}
    for k in range(LAGS):
        columns[f"lag_{k}"] = values[series, np.maximum(origins - k, 0)] / scale
    columns["mean_4"] = origin.mean_4[series, origins] / scale
    columns["mean_13"] = origin.mean_13[series, origins] / scale
    columns["std_13"] = origin.std_13[series, origins] / scale
    columns["mean_all"] = origin.mean_all[series, origins] / scale
    columns["nonzero_13"] = origin.nonzero_13[series, origins]
    columns["weeks_since_sale"] = origin.weeks_since_sale[series, origins]
    columns["log_scale"] = np.log(scale)

    target = origins + horizons
    last_year = target - SEASON  # <= origin because horizon <= SEASON
    has_year = last_year >= 0
    columns["season_lag"] = np.where(
        has_year, values[series, np.maximum(last_year, 0)] / scale, np.nan
    )
    window_start = np.maximum(last_year - 1, 0)
    window = np.zeros(len(series))
    for offset in range(3):  # mean of the 3 weeks around the same week last year
        window += values[series, np.minimum(window_start + offset, origins)]
    columns["season_window"] = np.where(last_year >= 1, window / 3 / scale, np.nan)

    dates = pd.to_datetime(week0) + pd.to_timedelta(target * 7, unit="D")
    columns["week_of_year"] = np.asarray(dates.isocalendar().week, dtype=np.float64)
    columns["month"] = np.asarray(dates.month, dtype=np.float64)
    columns["horizon"] = horizons.astype(np.float64)
    columns["sku_code"] = sku_codes[series]
    columns["region_code"] = region_codes[series]
    return pd.DataFrame(columns)[FEATURE_NAMES], scale

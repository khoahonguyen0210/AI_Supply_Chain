"""Naive, moving-average and seasonal-naive baselines under walk-forward evaluation.

Every baseline forecasts week ``w`` from an origin ``h`` weeks earlier and may only read values at
or before that origin (``w - h``).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .metrics import Array

HORIZONS = 8
SEASON = 52

Baseline = Callable[[Array, int, int, int], Array]


def _target_columns(start: int, end: int) -> np.ndarray:
    return np.arange(start, end)


def naive(values: Array, start: int, end: int, horizons: int) -> Array:
    """Repeat the last observed week."""
    weeks = _target_columns(start, end)
    return np.stack([values[:, weeks - h] for h in range(1, horizons + 1)], axis=2)


def moving_average(window: int) -> Baseline:
    """Mean of the ``window`` weeks ending at the origin (fewer if history is short)."""

    def predict(values: Array, start: int, end: int, horizons: int) -> Array:
        cumulative = np.concatenate(
            [np.zeros((values.shape[0], 1)), np.cumsum(values, axis=1)], axis=1
        )
        weeks = _target_columns(start, end)
        out = np.empty((values.shape[0], len(weeks), horizons))
        for h in range(1, horizons + 1):
            origin = weeks - h
            first = np.maximum(origin - window + 1, 0)
            out[:, :, h - 1] = (cumulative[:, origin + 1] - cumulative[:, first]) / (
                origin + 1 - first
            )
        return out

    return predict


def seasonal_naive(values: Array, start: int, end: int, horizons: int) -> Array:
    """Same week last year; falls back to naive when a year of history is unavailable."""
    weeks = _target_columns(start, end)
    fallback = naive(values, start, end, horizons)
    last_year = weeks - SEASON
    if (last_year >= 0).all():
        return np.repeat(values[:, last_year][:, :, None], horizons, axis=2)
    out = fallback.copy()
    ok = last_year >= 0
    out[:, ok, :] = values[:, last_year[ok]][:, :, None]
    return out


BASELINES: dict[str, Baseline] = {
    "naive": naive,
    "moving_average_4": moving_average(4),
    "moving_average_13": moving_average(13),
    "seasonal_naive": seasonal_naive,
}

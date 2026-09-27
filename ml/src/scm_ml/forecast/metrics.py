from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def point_metrics(actual: Array, predicted: Array) -> dict[str, float | None]:
    error = predicted - actual
    nonzero = actual > 0
    total = float(actual.sum())
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "bias": float(error.mean()),
        "wape": float(np.abs(error).sum() / total) if total > 0 else None,
        "mape": float((np.abs(error[nonzero]) / actual[nonzero]).mean()) if nonzero.any() else None,
    }


def interval_metrics(actual: Array, lower: Array, upper: Array) -> dict[str, float]:
    inside = (actual >= lower) & (actual <= upper)
    return {"coverage": float(inside.mean()), "mean_width": float((upper - lower).mean())}


def _broadcast(actual: Array, predicted: Array) -> Array:
    return np.broadcast_to(actual[:, :, None], predicted.shape)


def evaluate_point(actual: Array, predicted: Array) -> dict[str, object]:
    target = _broadcast(actual, predicted)
    return {
        "overall": point_metrics(target, predicted),
        "by_horizon": {
            str(h + 1): point_metrics(target[:, :, h], predicted[:, :, h])
            for h in range(predicted.shape[2])
        },
    }


def evaluate_interval(actual: Array, lower: Array, upper: Array) -> dict[str, object]:
    target = _broadcast(actual, lower)
    return {
        "overall": interval_metrics(target, lower, upper),
        "by_horizon": {
            str(h + 1): interval_metrics(target[:, :, h], lower[:, :, h], upper[:, :, h])
            for h in range(lower.shape[2])
        },
    }

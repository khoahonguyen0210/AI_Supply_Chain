from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import DEFAULT_ARTIFACT_ROOT, provenance, save_predictions, write_json
from .baselines import BASELINES, HORIZONS
from .metrics import Array, evaluate_interval, evaluate_point
from .model import ModelConfig, predict_matrix, save_model, train_forecaster
from .panel import ForecastPanel, TemporalSplit, save_dataset, split_indices
from .uncertainty import INTERVAL_LEVEL, QUANTILES, calibrate, predict_interval

EXPERIMENT_ROOT = Path("ml/experiments/forecast")


def windows(panel: ForecastPanel, split: TemporalSplit) -> dict[str, tuple[int, int]]:
    val, test = split_indices(panel, split)
    return {"validation": (val, test), "test": (test, len(panel.weeks))}


def run_baselines(
    panel: ForecastPanel, split: TemporalSplit, horizons: int = HORIZONS
) -> tuple[dict[str, Any], dict[str, Array]]:
    metrics: dict[str, Any] = {}
    test_predictions: dict[str, Array] = {}
    spans = windows(panel, split)
    for name, baseline in BASELINES.items():
        metrics[name] = {}
        for window, (start, end) in spans.items():
            predicted = baseline(panel.values, start, end, horizons)
            metrics[name][window] = evaluate_point(panel.values[:, start:end], predicted)
            if window == "test":
                test_predictions[name] = predicted
    selected = min(metrics, key=lambda n: metrics[n]["validation"]["overall"]["mae"])
    return {"metrics": metrics, "selected_by_validation_mae": selected}, test_predictions


def run_baseline_experiment(
    panel: ForecastPanel,
    split: TemporalSplit,
    root: Path = DEFAULT_ARTIFACT_ROOT,
    horizons: int = HORIZONS,
) -> dict[str, Any]:
    directory = root / panel.dataset_id
    dataset_info = save_dataset(panel, split, directory / "dataset")
    result, predictions = run_baselines(panel, split, horizons)
    _, test_start = split_indices(panel, split)
    save_predictions(
        directory / "baselines" / "test_predictions.csv", panel, test_start, predictions
    )
    payload = {
        "dataset": dataset_info,
        "config": {"horizons": horizons, "baselines": sorted(BASELINES)},
        **result,
        "provenance": provenance(),
    }
    write_json(directory / "baselines" / "metrics.json", payload)
    return payload


def run_forecast_experiment(
    panel: ForecastPanel,
    split: TemporalSplit,
    root: Path = DEFAULT_ARTIFACT_ROOT,
    config: ModelConfig | None = None,
) -> dict[str, Any]:
    config = config or ModelConfig()
    directory = root / panel.dataset_id
    baselines = run_baseline_experiment(panel, split, root, config.horizons)
    model = train_forecaster(panel, split, config, QUANTILES)
    calibrate(model, panel, split, config.horizons)
    model_meta = save_model(model, directory / "model")

    metrics: dict[str, Any] = {}
    intervals: dict[str, Any] = {}
    test_predictions: dict[str, Array] = {}
    for window, (start, end) in windows(panel, split).items():
        predicted = predict_matrix(
            model, "point", panel.values, panel.weeks[0], panel.series, start, end, config.horizons
        )
        actual = panel.values[:, start:end]
        metrics[window] = evaluate_point(actual, predicted)
        intervals[window] = {}
        for label, calibrated in (("raw_quantile", False), ("calibrated", True)):
            _, lower, upper = predict_interval(
                model,
                panel.values,
                panel.weeks[0],
                panel.series,
                start,
                end,
                config.horizons,
                calibrated,
            )
            intervals[window][label] = evaluate_interval(actual, lower, upper)
            if window == "test" and calibrated:
                test_predictions["lightgbm"] = predicted
                test_predictions["lower"], test_predictions["upper"] = lower, upper
    _, test_start = split_indices(panel, split)
    save_predictions(
        directory / "model" / "test_predictions.csv", panel, test_start, test_predictions
    )

    selected = baselines["selected_by_validation_mae"]
    base_mae = baselines["metrics"][selected]["test"]["overall"]["mae"]
    model_mae = metrics["test"]["overall"]["mae"]
    payload = {
        "dataset": baselines["dataset"],
        "config": {**model_meta["config"], "split": model_meta["split"]},
        "model_version": model_meta["model_version"],
        "baselines": baselines["metrics"],
        "selected_baseline": selected,
        "model": metrics,
        "intervals": {"nominal_level": INTERVAL_LEVEL, **intervals},
        "calibration": model.calibration,
        "test_mae_improvement_vs_selected_baseline": (base_mae - model_mae) / base_mae,
        "provenance": provenance(),
    }
    write_json(directory / "model" / "metrics.json", payload)
    return payload

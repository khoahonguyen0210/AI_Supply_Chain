from datetime import date
from pathlib import Path

import numpy as np
import pytest

from scm_ml.forecast.experiment import run_forecast_experiment
from scm_ml.forecast.features import FEATURE_NAMES, MIN_ORIGIN, OriginFeatures, make_features
from scm_ml.forecast.model import (
    ForecastModel,
    ModelConfig,
    load_model,
    predict_matrix,
    save_model,
    train_forecaster,
)
from scm_ml.forecast.panel import ForecastPanel, default_split, panel_from_world, split_indices
from scm_ml.synthetic import SyntheticConfig, generate_world

FAST = ModelConfig(max_rounds=40, early_stopping_rounds=10)


@pytest.fixture(scope="module")
def panel() -> ForecastPanel:
    cfg = SyntheticConfig(seed=11, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)
    return panel_from_world(generate_world(cfg))


@pytest.fixture(scope="module")
def model(panel: ForecastPanel) -> ForecastModel:
    return train_forecaster(panel, default_split(panel), FAST)


def _features(values: np.ndarray, series: int, origin: int, horizon: int) -> np.ndarray:
    frame, _ = make_features(
        OriginFeatures(values),
        np.array([series]),
        np.array([origin]),
        np.array([horizon]),
        date(2023, 1, 2),
        np.arange(values.shape[0]),
        np.zeros(values.shape[0], dtype=np.int64),
    )
    assert list(frame.columns) == FEATURE_NAMES
    return frame.to_numpy(dtype=np.float64)


@pytest.mark.parametrize("origin,horizon", [(MIN_ORIGIN, 1), (40, 4), (60, 8)])
def test_features_ignore_everything_after_the_origin(origin: int, horizon: int) -> None:
    rng = np.random.default_rng(1)
    values = rng.poisson(5, size=(3, 80)).astype(np.float64)
    clean = _features(values, 1, origin, horizon)
    tampered = values.copy()
    tampered[:, origin + 1 :] = 1e9  # includes the target week itself
    np.testing.assert_array_equal(_features(tampered, 1, origin, horizon), clean)


def test_features_do_react_to_history() -> None:
    rng = np.random.default_rng(1)
    values = rng.poisson(5, size=(3, 80)).astype(np.float64)
    changed = values.copy()
    changed[1, 40] += 1000
    assert not np.array_equal(_features(values, 1, 40, 1), _features(changed, 1, 40, 1))


def test_predictions_have_walk_forward_shape_and_are_non_negative(
    panel: ForecastPanel, model: ForecastModel
) -> None:
    val, test = split_indices(panel, default_split(panel))
    pred = predict_matrix(model, "point", panel.values, panel.weeks[0], panel.series, val, test, 8)
    assert pred.shape == (len(panel.series), test - val, 8)
    assert (pred >= 0).all() and np.isfinite(pred).all()


def test_forecast_for_a_week_ignores_later_actuals(
    panel: ForecastPanel, model: ForecastModel
) -> None:
    val, _ = split_indices(panel, default_split(panel))
    base = predict_matrix(
        model, "point", panel.values, panel.weeks[0], panel.series, val, val + 1, 4
    )
    future = panel.values.copy()
    future[:, val:] = 1e6  # hide/destroy everything from the target week onward
    again = predict_matrix(model, "point", future, panel.weeks[0], panel.series, val, val + 1, 4)
    # horizon 1 uses origin val-1; later horizons use even earlier origins
    np.testing.assert_allclose(again, base)


def test_training_is_reproducible(panel: ForecastPanel, model: ForecastModel) -> None:
    again = train_forecaster(panel, default_split(panel), FAST)
    assert again.version == model.version


def test_model_artifact_round_trip(
    panel: ForecastPanel, model: ForecastModel, tmp_path: Path
) -> None:
    meta = save_model(model, tmp_path)
    assert meta["model_version"] == model.version and meta["dataset_id"] == panel.dataset_id
    loaded = load_model(tmp_path)
    val, test = split_indices(panel, default_split(panel))
    args = (panel.values, panel.weeks[0], panel.series, val, test, 8)
    np.testing.assert_allclose(
        predict_matrix(loaded, "point", *args), predict_matrix(model, "point", *args)
    )


def test_incompatible_artifact_is_rejected(model: ForecastModel, tmp_path: Path) -> None:
    save_model(model, tmp_path)
    meta = (
        (tmp_path / "meta.json").read_text(encoding="utf-8").replace('"format": 1', '"format": 99')
    )
    (tmp_path / "meta.json").write_text(meta, encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        load_model(tmp_path)


def test_experiment_produces_metrics_and_artifacts(panel: ForecastPanel, tmp_path: Path) -> None:
    result = run_forecast_experiment(panel, default_split(panel), tmp_path, FAST)
    directory = tmp_path / panel.dataset_id
    assert (directory / "model" / "point.txt").exists()
    assert (directory / "model" / "metrics.json").exists()
    assert set(result["model"]) == {"validation", "test"}
    assert result["model"]["test"]["overall"]["mae"] > 0
    assert result["model_version"].startswith("lgbm-")

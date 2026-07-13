from pathlib import Path

import numpy as np
import pytest

from scm_ml.forecast.model import (
    ForecastModel,
    ModelConfig,
    load_model,
    save_model,
    train_forecaster,
)
from scm_ml.forecast.panel import ForecastPanel, default_split, panel_from_world, split_indices
from scm_ml.forecast.uncertainty import QUANTILES, calibrate, predict_interval
from scm_ml.synthetic import SyntheticConfig, generate_world

FAST = ModelConfig(max_rounds=40, early_stopping_rounds=10)
H = 8


@pytest.fixture(scope="module")
def panel() -> ForecastPanel:
    cfg = SyntheticConfig(seed=21, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)
    return panel_from_world(generate_world(cfg))


@pytest.fixture(scope="module")
def model(panel: ForecastPanel) -> ForecastModel:
    split = default_split(panel)
    return calibrate(train_forecaster(panel, split, FAST, QUANTILES), panel, split, H)


def test_interval_brackets_the_point_forecast(panel: ForecastPanel, model: ForecastModel) -> None:
    val, test = split_indices(panel, default_split(panel))
    for calibrated in (False, True):
        point, lower, upper = predict_interval(
            model, panel.values, panel.weeks[0], panel.series, val, test, H, calibrated
        )
        assert lower.shape == upper.shape == point.shape
        assert (lower >= 0).all()
        assert (lower <= point + 1e-9).all() and (point <= upper + 1e-9).all()


def test_calibration_stores_one_offset_per_horizon(model: ForecastModel) -> None:
    assert model.calibration["method"] == "cqr"
    assert set(model.calibration["offsets"]) == {str(h) for h in range(1, H + 1)}
    assert model.calibration["level"] == pytest.approx(0.8)


def test_calibrated_validation_coverage_reaches_nominal_level(
    panel: ForecastPanel, model: ForecastModel
) -> None:
    val, test = split_indices(panel, default_split(panel))
    _, lower, upper = predict_interval(
        model, panel.values, panel.weeks[0], panel.series, val, test, H
    )
    actual = panel.values[:, val:test, None]
    coverage = ((actual >= lower) & (actual <= upper)).mean()
    assert coverage >= 0.8 - 0.02  # conformal guarantee on the calibration window


def test_calibration_never_narrows_below_what_is_needed(
    panel: ForecastPanel, model: ForecastModel
) -> None:
    val, test = split_indices(panel, default_split(panel))
    args = (panel.values, panel.weeks[0], panel.series, val, test, H)
    _, raw_lo, raw_hi = predict_interval(model, *args, calibrated=False)
    _, lo, hi = predict_interval(model, *args, calibrated=True)
    actual = panel.values[:, val:test, None]
    raw_cov = ((actual >= raw_lo) & (actual <= raw_hi)).mean()
    cal_cov = ((actual >= lo) & (actual <= hi)).mean()
    assert cal_cov >= min(raw_cov, 0.8) - 0.02


def test_uncalibrated_model_refuses_calibrated_intervals(panel: ForecastPanel) -> None:
    uncal = train_forecaster(panel, default_split(panel), FAST, QUANTILES)
    val, test = split_indices(panel, default_split(panel))
    with pytest.raises(ValueError, match="calibrat"):
        predict_interval(uncal, panel.values, panel.weeks[0], panel.series, val, test, H)


def test_intervals_survive_save_and_load(
    panel: ForecastPanel, model: ForecastModel, tmp_path: Path
) -> None:
    save_model(model, tmp_path)
    loaded = load_model(tmp_path)
    val, test = split_indices(panel, default_split(panel))
    args = (panel.values, panel.weeks[0], panel.series, val, test, H)
    for a, b in zip(predict_interval(model, *args), predict_interval(loaded, *args), strict=True):
        np.testing.assert_allclose(a, b)

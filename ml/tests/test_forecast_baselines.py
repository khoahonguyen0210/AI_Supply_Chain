from pathlib import Path

import numpy as np
import pytest

from scm_ml.forecast.baselines import BASELINES, moving_average, naive, seasonal_naive
from scm_ml.forecast.experiment import run_baseline_experiment, run_baselines
from scm_ml.forecast.metrics import evaluate_interval, evaluate_point, point_metrics
from scm_ml.forecast.panel import ForecastPanel, default_split, panel_from_world
from scm_ml.synthetic import SyntheticConfig, generate_world

RNG = np.random.default_rng(0)
VALUES = RNG.integers(0, 50, size=(4, 80)).astype(np.float64)


def test_naive_repeats_last_observation() -> None:
    pred = naive(VALUES, 60, 63, 3)
    assert pred.shape == (4, 3, 3)
    np.testing.assert_array_equal(pred[:, 0, 0], VALUES[:, 59])  # week 60 from origin 59
    np.testing.assert_array_equal(pred[:, 0, 2], VALUES[:, 57])  # week 60 from origin 57


def test_moving_average_uses_window_ending_at_origin() -> None:
    pred = moving_average(4)(VALUES, 60, 62, 2)
    np.testing.assert_allclose(pred[:, 0, 0], VALUES[:, 56:60].mean(axis=1))
    np.testing.assert_allclose(pred[:, 1, 1], VALUES[:, 56:60].mean(axis=1))  # week 61, origin 59


def test_moving_average_handles_short_history() -> None:
    pred = moving_average(13)(VALUES, 3, 4, 1)
    np.testing.assert_allclose(pred[:, 0, 0], VALUES[:, 0:3].mean(axis=1))


def test_seasonal_naive_uses_same_week_last_year() -> None:
    pred = seasonal_naive(VALUES, 60, 62, 2)
    np.testing.assert_array_equal(pred[:, 0, 0], VALUES[:, 8])
    np.testing.assert_array_equal(pred[:, 1, 1], VALUES[:, 9])


def test_seasonal_naive_falls_back_without_a_year_of_history() -> None:
    pred = seasonal_naive(VALUES, 40, 42, 1)
    np.testing.assert_array_equal(pred[:, 0, 0], VALUES[:, 39])


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_baselines_never_read_values_after_the_origin(name: str) -> None:
    start, end, horizons = 60, 66, 4
    clean = BASELINES[name](VALUES, start, end, horizons)
    for k in (0, 3, 5):
        for h in (1, 2, 4):
            origin = start + k - h
            garbage = VALUES.copy()
            garbage[:, origin + 1 :] = 1e6
            dirty = BASELINES[name](garbage, start, end, horizons)
            np.testing.assert_array_equal(dirty[:, k, h - 1], clean[:, k, h - 1])


def test_point_metrics_known_values() -> None:
    actual = np.array([[0.0, 10.0, 20.0]])
    predicted = np.array([[2.0, 8.0, 26.0]])
    m = point_metrics(actual, predicted)
    assert m["mae"] == pytest.approx(10 / 3)
    assert m["rmse"] == pytest.approx(np.sqrt((4 + 4 + 36) / 3))
    assert m["bias"] == pytest.approx(2.0)  # (+2 -2 +6) / 3
    assert m["wape"] == pytest.approx(10 / 30)
    assert m["mape"] == pytest.approx((0.2 + 0.3) / 2)  # zero actual excluded


def test_mape_is_undefined_when_all_actuals_are_zero() -> None:
    m = point_metrics(np.zeros((1, 3)), np.ones((1, 3)))
    assert m["mape"] is None and m["wape"] is None


def test_evaluate_reports_every_horizon_and_interval_coverage() -> None:
    actual = np.array([[1.0, 2.0]])
    pred = np.stack([actual, actual + 1], axis=2)
    out = evaluate_point(actual, pred)
    assert set(out["by_horizon"]) == {"1", "2"}  # type: ignore[call-overload]
    cover = evaluate_interval(actual, pred - 0.5, pred + 0.5)
    assert cover["overall"]["coverage"] == 0.5  # type: ignore[index]


@pytest.fixture(scope="module")
def panel() -> ForecastPanel:
    cfg = SyntheticConfig(seed=5, n_skus=6, n_suppliers=7, n_weeks=60, target_sales_orders=3_000)
    return panel_from_world(generate_world(cfg))


def test_baseline_metrics_are_reproducible(panel: ForecastPanel, tmp_path: Path) -> None:
    split = default_split(panel)
    first, _ = run_baselines(panel, split)
    second, _ = run_baselines(panel, split)
    assert first == second
    saved = run_baseline_experiment(panel, split, tmp_path)
    assert saved["metrics"] == first["metrics"]
    assert (tmp_path / panel.dataset_id / "baselines" / "test_predictions.csv").exists()
    assert saved["selected_by_validation_mae"] in BASELINES


def test_selection_uses_validation_not_test(panel: ForecastPanel) -> None:
    result, _ = run_baselines(panel, default_split(panel))
    metrics = result["metrics"]
    best_on_validation = min(metrics, key=lambda n: metrics[n]["validation"]["overall"]["mae"])
    assert result["selected_by_validation_mae"] == best_on_validation

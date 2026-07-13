from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scm_ml.forecast.panel import (
    ForecastPanel,
    TemporalSplit,
    default_split,
    load_dataset,
    panel_from_frame,
    panel_from_real,
    panel_from_world,
    save_dataset,
    split_indices,
)
from scm_ml.synthetic import SyntheticConfig, generate_world

CFG = SyntheticConfig(seed=3, n_skus=6, n_suppliers=7, n_weeks=60, target_sales_orders=3_000)


@pytest.fixture(scope="module")
def panel() -> ForecastPanel:
    return panel_from_world(generate_world(CFG))


def test_world_panel_is_dense_and_conserves_demand(panel: ForecastPanel) -> None:
    world = generate_world(CFG)
    assert panel.values.shape == (6 * 5, 60)
    assert panel.values.sum() == sum(o.quantity for o in world.sales_orders)
    assert all(w.weekday() == 0 for w in panel.weeks)
    assert (panel.values >= 0).all()


def test_split_windows_are_ordered_and_disjoint(panel: ForecastPanel) -> None:
    split = default_split(panel)
    val, test = split_indices(panel, split)
    assert 0 < val < test < len(panel.weeks)
    assert (val, test - val, len(panel.weeks) - test) == (60 - 26, 13, 13)


def test_invalid_split_is_rejected(panel: ForecastPanel) -> None:
    with pytest.raises(ValueError):
        split_indices(panel, TemporalSplit(val_start=panel.weeks[40], test_start=panel.weeks[20]))
    with pytest.raises(ValueError):
        default_split(panel, val_weeks=30, test_weeks=30)


def test_dataset_artifact_round_trip_and_identity(panel: ForecastPanel, tmp_path: Path) -> None:
    split = default_split(panel)
    info = save_dataset(panel, split, tmp_path / "a")
    again = save_dataset(panel, split, tmp_path / "b")
    assert info == again  # reproducible, including the file checksum
    restored, restored_split = load_dataset(tmp_path / "a")
    assert restored.dataset_id == panel.dataset_id
    assert restored_split == split
    np.testing.assert_array_equal(restored.values, panel.values)


def test_tampered_artifact_is_detected(panel: ForecastPanel, tmp_path: Path) -> None:
    save_dataset(panel, default_split(panel), tmp_path)
    frame = pd.read_csv(tmp_path / "panel.csv", dtype={"sku_id": str})
    quantities = frame["quantity"].to_numpy().copy()
    quantities[0] += 1
    frame["quantity"] = quantities
    frame.to_csv(tmp_path / "panel.csv", index=False)
    with pytest.raises(ValueError, match="dataset_id"):
        load_dataset(tmp_path)


def test_panel_from_frame_validates_input() -> None:
    base = {"sku_id": ["A", "A"], "region_id": ["R", "R"], "quantity": [1, 2]}
    monday = date(2024, 1, 1)
    with pytest.raises(ValueError, match="duplicate"):
        panel_from_frame(pd.DataFrame({**base, "period_start": [monday, monday]}), "t")
    with pytest.raises(ValueError, match="Monday"):
        panel_from_frame(
            pd.DataFrame({**base, "period_start": [monday, monday + timedelta(days=1)]}), "t"
        )
    with pytest.raises(ValueError, match="negative"):
        panel_from_frame(
            pd.DataFrame(
                {**base, "quantity": [1, -2], "period_start": [monday, monday + timedelta(weeks=1)]}
            ),
            "t",
        )


def test_sparse_frame_is_zero_filled() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["A", "A"],
            "region_id": ["R", "R"],
            "period_start": [date(2024, 1, 1), date(2024, 1, 22)],
            "quantity": [5, 7],
        }
    )
    panel = panel_from_frame(frame, "t")
    assert panel.values.tolist() == [[5.0, 0.0, 0.0, 7.0]]


REAL = Path("data/real_demand")


@pytest.mark.skipif(not (REAL / "demand_weekly.csv").exists(), reason="real dataset not built")
def test_real_panel_matches_documented_split() -> None:
    panel = panel_from_real(REAL)
    split = default_split(panel)
    assert panel.values.shape == (200, 104)
    assert split.val_start == date(2011, 6, 6)  # equals the realdata selection cutoff
    assert split.test_start == date(2011, 9, 5)

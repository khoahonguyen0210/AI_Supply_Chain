from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scm_ml.realdata.online_retail import (
    CACHE_NAME,
    OnlineRetailConfig,
    build_dataset,
    normalize_transactions,
    to_observations,
)

CFG = OnlineRetailConfig(
    n_skus=3, n_regions=3, min_active_weeks=3, selection_cutoff=date(2020, 4, 6)
)
COUNTRIES = ["Aland", "Borduria", "Carpania", "Dalmatia"]
CODES = ["10001", "10002A", "10003", "10004", "10005B", "10006"]


def make_raw() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows: list[tuple[object, ...]] = []
    day = pd.Timestamp("2020-01-01 09:30")  # a Wednesday: first week is partial
    while day <= pd.Timestamp("2020-06-30 17:00"):
        for code_i, code in enumerate(CODES):
            country = COUNTRIES[int(rng.integers(0, 4)) if code_i % 2 else code_i % 2]
            rows.append(
                (
                    "INV" + str(len(rows)),
                    code,
                    "item " + code,
                    int(rng.integers(1, 20)),
                    day,
                    1.5 + code_i,
                    country,
                )
            )
        day += pd.Timedelta(days=1)
    rows += [
        ("C999", "10001", "cancelled", 5, pd.Timestamp("2020-02-03 10:00"), 2.0, "Aland"),
        ("INV-P", "POST", "postage", 1, pd.Timestamp("2020-02-03 10:00"), 8.0, "Aland"),
        ("INV-N", "10001", "negative", -4, pd.Timestamp("2020-02-03 10:00"), 2.0, "Aland"),
        ("INV-Z", "10001", "free", 3, pd.Timestamp("2020-02-03 10:00"), 0.0, "Aland"),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "Invoice",
            "StockCode",
            "Description",
            "Quantity",
            "InvoiceDate",
            "Price",
            "Country",
        ],
    )


def test_cleaning_drops_cancellations_nonproducts_and_invalid_rows() -> None:
    raw = make_raw()
    demand, _ = normalize_transactions(raw, CFG)
    clean = raw.iloc[: len(raw) - 4]
    expected, _ = normalize_transactions(clean, CFG)
    assert "POST" not in set(demand["sku_id"])
    assert demand["quantity"].sum() == expected["quantity"].sum()


def test_only_complete_weeks_and_dense_grid() -> None:
    demand, _ = normalize_transactions(make_raw(), CFG)
    starts = sorted({date.fromisoformat(str(d)) for d in demand["period_start"]})
    assert starts[0] == date(2020, 1, 6)  # 2020-01-01 is Wednesday -> first full week starts Monday
    assert starts[-1] == date(2020, 6, 22)  # data ends Tuesday 2020-06-30
    assert all(s.weekday() == 0 for s in starts)
    assert all((b - a) == timedelta(days=7) for a, b in zip(starts, starts[1:], strict=False))
    assert len(demand) == 3 * 3 * len(starts)  # skus x regions x weeks, zero-filled


def test_observed_at_is_end_of_period() -> None:
    demand, _ = normalize_transactions(make_raw(), CFG)
    for obs in to_observations(demand.head(50)):
        assert obs.observed_at.date() == obs.period_start + timedelta(days=7)


def test_selection_ignores_data_after_cutoff() -> None:
    raw = make_raw()
    base, _ = normalize_transactions(raw, CFG)
    tampered = raw.copy()
    late = tampered["InvoiceDate"] >= pd.Timestamp(CFG.selection_cutoff)
    boost = tampered["StockCode"].eq("10006") | tampered["Country"].eq("Dalmatia")
    tampered.loc[late & boost, "Quantity"] *= 1000
    changed, _ = normalize_transactions(tampered, CFG)
    assert set(base["sku_id"]) == set(changed["sku_id"])
    assert set(base["region_id"]) == set(changed["region_id"])
    pre = base["period_start"].map(lambda d: date.fromisoformat(str(d))) < CFG.selection_cutoff
    assert base[pre]["quantity"].tolist() == changed[pre]["quantity"].tolist()


def test_normalisation_is_deterministic() -> None:
    first, meta_a = normalize_transactions(make_raw(), CFG)
    second, meta_b = normalize_transactions(make_raw(), CFG)
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(meta_a, meta_b)


REAL_RAW = Path("data/raw/online_retail_ii")


@pytest.mark.skipif(not (REAL_RAW / CACHE_NAME).exists(), reason="real dataset not downloaded")
def test_real_dataset_is_reproducible_and_identified(tmp_path: Path) -> None:
    first = build_dataset(REAL_RAW, tmp_path / "a")
    second = build_dataset(REAL_RAW, tmp_path / "b")
    assert first == second
    assert first["source"]["archive_sha256"]
    assert first["files"]["demand_weekly.csv"]["rows"] == 40 * 5 * 104
    assert first["first_week"] == "2009-12-07"
    assert first["last_week"] == "2011-11-28"

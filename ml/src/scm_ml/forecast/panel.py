from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from scm_common.domain import DomainModel
from scm_ml.synthetic import SyntheticWorld

PANEL_FILE = "panel.csv"
SPLIT_FILE = "split.json"
PANEL_COLUMNS = ["sku_id", "region_id", "period_start", "quantity"]


class TemporalSplit(DomainModel):
    """Targets before `val_start` train, [val_start, test_start) validate, the rest test."""

    val_start: date
    test_start: date


@dataclass(frozen=True)
class ForecastPanel:
    source: str
    series: list[tuple[str, str]]  # (sku_id, region_id), sorted
    weeks: list[date]  # consecutive Mondays, ascending
    values: NDArray[np.float64]  # shape (n_series, n_weeks), zero-filled

    @property
    def dataset_id(self) -> str:
        digest = hashlib.sha256()
        digest.update(json.dumps([self.series, [w.isoformat() for w in self.weeks]]).encode())
        digest.update(np.ascontiguousarray(self.values).tobytes())
        return f"{self.source}-{digest.hexdigest()[:12]}"

    def week_index(self, week: date) -> int:
        return (week - self.weeks[0]).days // 7


def _validate(frame: pd.DataFrame) -> None:
    if frame.duplicated(["sku_id", "region_id", "period_start"]).any():
        raise ValueError("duplicate (sku, region, week) rows")
    if (frame["quantity"] < 0).any():
        raise ValueError("negative demand")
    if (pd.to_datetime(frame["period_start"]).dt.weekday != 0).any():
        raise ValueError("period_start must be a Monday")


def panel_from_frame(frame: pd.DataFrame, source: str) -> ForecastPanel:
    frame = frame[PANEL_COLUMNS].copy()
    frame["period_start"] = pd.to_datetime(frame["period_start"]).dt.date
    _validate(frame)
    first, last = frame["period_start"].min(), frame["period_start"].max()
    weeks = [first + timedelta(weeks=i) for i in range((last - first).days // 7 + 1)]
    series = sorted(
        {(str(s), str(r)) for s, r in zip(frame["sku_id"], frame["region_id"], strict=True)}
    )
    row = {key: i for i, key in enumerate(series)}
    col = {week: j for j, week in enumerate(weeks)}
    values = np.zeros((len(series), len(weeks)))
    for sku, region, week, quantity in frame.itertuples(index=False):
        values[row[(str(sku), str(region))], col[week]] = float(quantity)
    return ForecastPanel(source=source, series=series, weeks=weeks, values=values)


def panel_from_world(world: SyntheticWorld) -> ForecastPanel:
    start = world.config.start_date
    rows = [
        (
            o.sku_id,
            o.region_id,
            start + timedelta(weeks=(o.ordered_at.date() - start).days // 7),
            o.quantity,
        )
        for o in world.sales_orders
    ]
    frame = (
        pd.DataFrame(rows, columns=PANEL_COLUMNS)
        .groupby(["sku_id", "region_id", "period_start"], as_index=False)["quantity"]
        .sum()
    )
    grid = pd.MultiIndex.from_product(
        [
            [s.sku_id for s in world.skus],
            [r.region_id for r in world.regions],
            [start + timedelta(weeks=i) for i in range(world.config.n_weeks)],
        ],
        names=["sku_id", "region_id", "period_start"],
    )
    dense = (
        frame.set_index(["sku_id", "region_id", "period_start"])["quantity"]
        .reindex(grid, fill_value=0)
        .reset_index()
    )
    return panel_from_frame(dense, source="synthetic")


def panel_from_real(directory: Path) -> ForecastPanel:
    frame = pd.read_csv(directory / "demand_weekly.csv", dtype={"sku_id": str})
    return panel_from_frame(frame, source="online-retail-ii")


def extends(panel: ForecastPanel, base: ForecastPanel) -> bool:
    n = len(base.weeks)
    return (
        panel.series == base.series
        and panel.weeks[:n] == base.weeks
        and bool(np.array_equal(panel.values[:, :n], base.values))
    )


def default_split(panel: ForecastPanel, val_weeks: int = 13, test_weeks: int = 13) -> TemporalSplit:
    if len(panel.weeks) < 2 * (val_weeks + test_weeks):
        raise ValueError("panel too short for the requested validation/test windows")
    return TemporalSplit(
        val_start=panel.weeks[-(val_weeks + test_weeks)], test_start=panel.weeks[-test_weeks]
    )


def split_indices(panel: ForecastPanel, split: TemporalSplit) -> tuple[int, int]:
    val, test = panel.week_index(split.val_start), panel.week_index(split.test_start)
    if not 0 < val < test < len(panel.weeks):
        raise ValueError("split boundaries must lie strictly inside the panel in order")
    return val, test


def save_dataset(panel: ForecastPanel, split: TemporalSplit, directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    long = pd.DataFrame(
        [
            (sku, region, week.isoformat(), int(panel.values[i, j]))
            for i, (sku, region) in enumerate(panel.series)
            for j, week in enumerate(panel.weeks)
        ],
        columns=PANEL_COLUMNS,
    )
    long.to_csv(directory / PANEL_FILE, index=False, lineterminator="\n")
    val, test = split_indices(panel, split)
    info: dict[str, object] = {
        "dataset_id": panel.dataset_id,
        "source": panel.source,
        "n_series": len(panel.series),
        "n_weeks": len(panel.weeks),
        "first_week": panel.weeks[0].isoformat(),
        "last_week": panel.weeks[-1].isoformat(),
        "val_start": split.val_start.isoformat(),
        "test_start": split.test_start.isoformat(),
        "train_weeks": val,
        "val_weeks": test - val,
        "test_weeks": len(panel.weeks) - test,
        "panel_sha256": hashlib.sha256((directory / PANEL_FILE).read_bytes()).hexdigest(),
    }
    (directory / SPLIT_FILE).write_text(
        json.dumps(info, indent=2, sort_keys=True), encoding="utf-8"
    )
    return info


def load_dataset(directory: Path) -> tuple[ForecastPanel, TemporalSplit]:
    info = json.loads((directory / SPLIT_FILE).read_text(encoding="utf-8"))
    frame = pd.read_csv(directory / PANEL_FILE, dtype={"sku_id": str})
    panel = panel_from_frame(frame, source=info["source"])
    if panel.dataset_id != info["dataset_id"]:
        raise ValueError("saved panel does not match its recorded dataset_id")
    split = TemporalSplit(
        val_start=date.fromisoformat(info["val_start"]),
        test_start=date.fromisoformat(info["test_start"]),
    )
    return panel, split

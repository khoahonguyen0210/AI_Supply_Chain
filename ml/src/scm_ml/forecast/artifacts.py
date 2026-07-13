from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import Array
from .panel import ForecastPanel

DEFAULT_ARTIFACT_ROOT = Path("ml/artifacts/forecast")


def git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def provenance() -> dict[str, str]:
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_revision": git_revision(),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def save_predictions(
    path: Path, panel: ForecastPanel, start: int, columns: dict[str, Array]
) -> None:
    first = next(iter(columns.values()))
    n_series, n_weeks, n_horizons = first.shape
    index = pd.MultiIndex.from_product(
        [range(n_series), range(n_weeks), range(1, n_horizons + 1)], names=["s", "k", "horizon"]
    ).to_frame(index=False)
    frame = pd.DataFrame(
        {
            "sku_id": [panel.series[s][0] for s in index["s"]],
            "region_id": [panel.series[s][1] for s in index["s"]],
            "target_week": [panel.weeks[start + k].isoformat() for k in index["k"]],
            "horizon": index["horizon"],
        }
    )
    for name, array in columns.items():
        frame[name] = np.round(array.reshape(-1), 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")

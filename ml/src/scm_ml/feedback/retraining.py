from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from pydantic import Field

from scm_common.domain import DomainModel
from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT, provenance, read_json, write_json
from scm_ml.forecast.baselines import BASELINES
from scm_ml.forecast.metrics import evaluate_interval, evaluate_point
from scm_ml.forecast.model import (
    ForecastModel,
    ModelConfig,
    load_model,
    save_model,
    train_forecaster,
)
from scm_ml.forecast.panel import PANEL_FILE, ForecastPanel, default_split, save_dataset
from scm_ml.forecast.uncertainty import INTERVAL_LEVEL, QUANTILES, calibrate, predict_interval

CANDIDATE_DIR = "candidates"
SERVING_FILE = "serving.json"
PROMOTION_LOG = "promotions.jsonl"
REPORT_FILE = "promotion_report.json"
REPORT_PATH = Path("ml/experiments/feedback/retraining-synthetic.json")
HOLDOUT_WEEKS = 4
REFERENCE_BASELINE = "moving_average_13"

AWAITING_APPROVAL = "AWAITING_APPROVAL"
REJECTED_BY_GATE = "REJECTED_BY_GATE"


class PromotionError(Exception):
    pass


class PromotionGate(DomainModel):
    min_mae_improvement: float = Field(default=0.0, ge=0, lt=1)
    """The candidate's held-out MAE must be at least this fraction below the current model's."""
    max_coverage_error: float = Field(default=0.10, gt=0, lt=1)
    """Calibrated interval coverage must lie within this distance of the nominal level."""

    def check(self, current: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        limit = current["mae"] * (1 - self.min_mae_improvement)
        if not candidate["mae"] < limit:
            reasons.append(
                f"candidate MAE {candidate['mae']:.4f} is not below {limit:.4f} "
                f"(current {current['mae']:.4f}, required improvement "
                f"{self.min_mae_improvement:.1%})"
            )
        error = abs(candidate["coverage"] - INTERVAL_LEVEL)
        if error > self.max_coverage_error:
            reasons.append(
                f"candidate interval coverage {candidate['coverage']:.3f} is more than "
                f"{self.max_coverage_error:.2f} from nominal {INTERVAL_LEVEL:.2f}"
            )
        return reasons


def read_actuals(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"sku_id": str, "region_id": str})
    missing = {"sku_id", "region_id", "week_start", "quantity"} - set(frame.columns)
    if missing:
        raise ValueError(f"actuals file lacks columns {sorted(missing)}")
    return frame[["sku_id", "region_id", "week_start", "quantity"]]


def extend_panel(history: ForecastPanel, actuals: pd.DataFrame) -> ForecastPanel:
    """History plus captured weeks, which must continue it without a gap."""
    frame = actuals.copy()
    frame["week_start"] = pd.to_datetime(frame["week_start"]).dt.date
    if frame.duplicated(["sku_id", "region_id", "week_start"]).any():
        raise ValueError("duplicate (sku, region, week) actuals")
    if (frame["quantity"] < 0).any():
        raise ValueError("negative demand in actuals")
    weeks = sorted(set(frame["week_start"]))
    expected = [history.weeks[-1] + timedelta(weeks=k + 1) for k in range(len(weeks))]
    if weeks != expected:
        raise ValueError(
            f"actual weeks must be consecutive Mondays starting {expected[0] if expected else '-'}"
        )
    row = {key: i for i, key in enumerate(history.series)}
    unknown = {(s, r) for s, r in zip(frame["sku_id"], frame["region_id"], strict=True)} - set(row)
    if unknown:
        raise ValueError(f"actuals for series without history: {sorted(unknown)[:3]}")
    new = np.zeros((len(history.series), len(weeks)))
    col = {week: j for j, week in enumerate(weeks)}
    for sku, region, week, quantity in frame.itertuples(index=False):
        new[row[(sku, region)], col[week]] = float(quantity)
    source = (
        history.source if history.source.endswith("-extended") else f"{history.source}-extended"
    )
    return ForecastPanel(
        source=source,
        series=history.series,
        weeks=history.weeks + weeks,
        values=np.concatenate([history.values, new], axis=1),
    )


def truncate(panel: ForecastPanel, n_weeks: int) -> ForecastPanel:
    return ForecastPanel(
        source=panel.source,
        series=panel.series,
        weeks=panel.weeks[:n_weeks],
        values=panel.values[:, :n_weeks].copy(),
    )


def _score_model(
    model: ForecastModel, panel: ForecastPanel, start: int, end: int, horizons: int
) -> dict[str, Any]:
    point, lower, upper = predict_interval(
        model, panel.values, panel.weeks[0], panel.series, start, end, horizons, calibrated=True
    )
    actual = panel.values[:, start:end]
    accuracy: Any = evaluate_point(actual, point)["overall"]
    interval: Any = evaluate_interval(actual, lower, upper)["overall"]
    return {"model_version": model.version, **accuracy, **interval}


def retrain(
    current: ForecastModel,
    history: ForecastPanel,
    actuals: pd.DataFrame,
    *,
    actuals_label: str,
    actuals_sha256: str,
    holdout_weeks: int = HOLDOUT_WEEKS,
    config: ModelConfig | None = None,
    gate: PromotionGate | None = None,
    root: Path = DEFAULT_ARTIFACT_ROOT,
    train: Callable[..., ForecastModel] = train_forecaster,
) -> dict[str, Any]:
    """Train and score a candidate; never touches the served model."""
    if current.dataset_id != history.dataset_id:
        raise ValueError("history must be the dataset the current model was trained on")
    config = config or current.config
    gate = gate or PromotionGate()
    extended = extend_panel(history, actuals)
    new_weeks = len(extended.weeks) - len(history.weeks)
    if new_weeks <= holdout_weeks:
        raise ValueError(
            f"{new_weeks} captured weeks: need more than the {holdout_weeks} held-out weeks"
        )
    train_panel = truncate(extended, len(extended.weeks) - holdout_weeks)
    split = default_split(train_panel)
    candidate = calibrate(
        train(train_panel, split, config, QUANTILES), train_panel, split, config.horizons
    )
    relative = f"{CANDIDATE_DIR}/{train_panel.dataset_id}"
    directory = root / relative
    dataset_info = save_dataset(train_panel, split, directory / "dataset")
    save_model(candidate, directory / "model")

    start, end = len(train_panel.weeks), len(extended.weeks)
    actual = extended.values[:, start:end]
    baseline = BASELINES[REFERENCE_BASELINE](extended.values, start, end, config.horizons)
    scores: dict[str, dict[str, Any]] = {
        "current": _score_model(current, extended, start, end, config.horizons),
        "candidate": _score_model(candidate, extended, start, end, config.horizons),
        REFERENCE_BASELINE: cast(dict[str, Any], evaluate_point(actual, baseline)["overall"]),
    }
    reasons = gate.check(scores["current"], scores["candidate"])
    report: dict[str, Any] = {
        "status": REJECTED_BY_GATE if reasons else AWAITING_APPROVAL,
        "gate": {**gate.model_dump(), "passed": not reasons, "reasons": reasons},
        "actuals": {
            "source": actuals_label,
            "sha256": actuals_sha256,
            "weeks": [
                extended.weeks[len(history.weeks)].isoformat(),
                extended.weeks[-1].isoformat(),
            ],
            "new_weeks": new_weeks,
        },
        "current": {
            "model_version": current.version,
            "dataset_id": current.dataset_id,
            "history_end": history.weeks[-1].isoformat(),
        },
        "candidate": {
            "model_version": candidate.version,
            "dataset_id": train_panel.dataset_id,
            "panel_sha256": dataset_info["panel_sha256"],
            "split": split.model_dump(mode="json"),
            "config": config.model_dump(mode="json"),
            "artifact_dir": relative,  # relative to the forecast artifact root
        },
        "holdout": {
            "weeks": [extended.weeks[start].isoformat(), extended.weeks[-1].isoformat()],
            "n_weeks": holdout_weeks,
            "horizons": config.horizons,
            "series": len(extended.series),
            "note": "neither model was trained or calibrated on these weeks; walk-forward inputs "
            "are identical for both",
        },
        "scores": scores,
        "provenance": provenance(),
    }
    write_json(directory / REPORT_FILE, report)
    return report


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def promote(
    report_path: Path,
    approved_by: str,
    *,
    root: Path = DEFAULT_ARTIFACT_ROOT,
    note: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Serve a passed candidate; refuses without a named approver or if artifacts changed."""
    approver = approved_by.strip()
    if not approver:
        raise PromotionError("an approver must be named; promotion is never automatic")
    report = read_json(report_path)
    if not report["gate"]["passed"] or report["status"] != AWAITING_APPROVAL:
        raise PromotionError(
            "the candidate did not pass its evaluation gate: "
            + "; ".join(report["gate"]["reasons"])
        )
    relative = report["candidate"]["artifact_dir"]
    directory = root / relative
    model = load_model(directory / "model")
    if model.version != report["candidate"]["model_version"]:
        raise PromotionError("the candidate model on disk is not the one that was evaluated")
    if _sha256(directory / "dataset" / PANEL_FILE) != report["candidate"]["panel_sha256"]:
        raise PromotionError("the candidate dataset on disk is not the one that was evaluated")

    serving_path = root / SERVING_FILE
    previous = read_json(serving_path) if serving_path.exists() else None
    entry: dict[str, Any] = {
        "model_dir": f"{relative}/model",  # relative to the artifact root
        "dataset_dir": f"{relative}/dataset",
        "model_version": model.version,
        "dataset_id": model.dataset_id,
        "approved_by": approver,
        "approved_at": clock().isoformat(timespec="seconds"),
        "note": note,
        "report": report_path.as_posix(),
        "report_sha256": _sha256(report_path),
        "previous_model_version": previous["model_version"] if previous else None,
    }
    write_json(serving_path, entry)
    with (root / PROMOTION_LOG).open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def serving_directories(root: Path) -> tuple[Path, Path] | None:
    path = root / SERVING_FILE
    if not path.exists():
        return None
    entry = read_json(path)
    return root / entry["model_dir"], root / entry["dataset_dir"]

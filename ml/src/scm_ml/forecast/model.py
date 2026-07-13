from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from scm_common.domain import DomainModel

from .baselines import HORIZONS
from .features import (
    CATEGORICAL,
    FEATURE_NAMES,
    MIN_ORIGIN,
    IntArray,
    OriginFeatures,
    make_features,
)
from .metrics import Array
from .panel import ForecastPanel, TemporalSplit, split_indices

MODEL_FORMAT = 1


class ModelConfig(DomainModel):
    seed: int = 42
    horizons: int = HORIZONS
    objective: str = "tweedie"  # mean-targeting; chosen on validation MAE (see docs/forecasting.md)
    tweedie_variance_power: float = 1.5
    weight_power: float = 1.0  # rows are weighted by series_scale ** weight_power
    learning_rate: float = 0.05
    num_leaves: int = 15
    min_data_in_leaf: int = 40
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    lambda_l2: float = 1.0
    max_rounds: int = 1000
    early_stopping_rounds: int = 50

    def lgb_params(
        self, objective: str | None = None, alpha: float | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "objective": objective or self.objective,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": 1,
            "lambda_l2": self.lambda_l2,
            "seed": self.seed,
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": 1,
            "verbose": -1,
        }
        if alpha is not None:
            params["alpha"] = alpha
        if params["objective"] == "tweedie":
            params["tweedie_variance_power"] = self.tweedie_variance_power
        return params


@dataclass
class ForecastModel:
    boosters: dict[str, lgb.Booster]
    skus: list[str]  # category code -> sku_id
    regions: list[str]
    config: ModelConfig
    dataset_id: str
    split: TemporalSplit
    best_iterations: dict[str, int] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        text = "".join(b.model_to_string() for _, b in sorted(self.boosters.items()))
        return f"lgbm-{hashlib.sha256(text.encode()).hexdigest()[:10]}"

    def codes(self, series: list[tuple[str, str]]) -> tuple[IntArray, IntArray]:
        sku_code = {s: i for i, s in enumerate(self.skus)}
        region_code = {r: i for i, r in enumerate(self.regions)}
        return (
            np.array([sku_code.get(s, -1) for s, _ in series], dtype=np.int64),
            np.array([region_code.get(r, -1) for _, r in series], dtype=np.int64),
        )


def _pairs(first_target: int, last_target: int, horizons: int) -> tuple[IntArray, IntArray]:
    targets = np.repeat(np.arange(first_target, last_target), horizons)
    hs = np.tile(np.arange(1, horizons + 1), last_target - first_target)
    origins = targets - hs
    keep = origins >= MIN_ORIGIN
    return origins[keep].astype(np.int64), hs[keep].astype(np.int64)


def build_rows(
    values: Array,
    week0: date,
    codes: tuple[IntArray, IntArray],
    first_target: int,
    last_target: int,
    horizons: int,
) -> tuple[pd.DataFrame, Array, Array, IntArray, IntArray, IntArray]:
    n_series = values.shape[0]
    origins, hs = _pairs(first_target, last_target, horizons)
    series = np.repeat(np.arange(n_series), len(origins))
    all_origins, all_hs = np.tile(origins, n_series), np.tile(hs, n_series)
    features, scale = make_features(
        OriginFeatures(values), series, all_origins, all_hs, week0, codes[0], codes[1]
    )
    y = values[series, all_origins + all_hs] / scale
    return features, y, scale, series, all_origins, all_hs


def _fit(
    config: ModelConfig,
    params: dict[str, Any],
    train: tuple[pd.DataFrame, Array, Array],
    valid: tuple[pd.DataFrame, Array, Array],
) -> lgb.Booster:
    power = config.weight_power
    dtrain = lgb.Dataset(
        train[0], train[1], weight=train[2] ** power, categorical_feature=CATEGORICAL
    )
    dvalid = lgb.Dataset(
        valid[0],
        valid[1],
        weight=valid[2] ** power,
        categorical_feature=CATEGORICAL,
        reference=dtrain,
    )
    return lgb.train(
        params,
        dtrain,
        num_boost_round=config.max_rounds,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
    )


def train_forecaster(
    panel: ForecastPanel,
    split: TemporalSplit,
    config: ModelConfig | None = None,
    quantiles: tuple[float, ...] = (),
) -> ForecastModel:
    """Train before `val_start`; early-stop on validation (the test window stays unseen)."""
    config = config or ModelConfig()
    val, test = split_indices(panel, split)
    model = ForecastModel(
        boosters={},
        skus=sorted({s for s, _ in panel.series}),
        regions=sorted({r for _, r in panel.series}),
        config=config,
        dataset_id=panel.dataset_id,
        split=split,
    )
    codes = model.codes(panel.series)
    # Validation features may use actuals up to their origin; only targets stay in their window.
    train = build_rows(panel.values, panel.weeks[0], codes, 1, val, config.horizons)
    valid = build_rows(panel.values, panel.weeks[0], codes, val, test, config.horizons)
    objectives: dict[str, tuple[str, float | None]] = {"point": (config.objective, None)}
    for q in quantiles:
        objectives[f"q{round(q * 100):02d}"] = ("quantile", q)
    for name, (objective, alpha) in objectives.items():
        booster = _fit(config, config.lgb_params(objective, alpha), train[:3], valid[:3])
        model.boosters[name] = booster
        model.best_iterations[name] = int(booster.best_iteration)
    return model


def predict_scaled(
    model: ForecastModel,
    name: str,
    origin_features: OriginFeatures,
    series: IntArray,
    origins: IntArray,
    hs: IntArray,
    week0: date,
    codes: tuple[IntArray, IntArray],
) -> Array:
    features, scale = make_features(origin_features, series, origins, hs, week0, codes[0], codes[1])
    booster = model.boosters[name]
    raw = booster.predict(features, num_iteration=booster.best_iteration)
    return np.maximum(np.asarray(raw, dtype=np.float64), 0.0) * scale


def predict_matrix(
    model: ForecastModel,
    name: str,
    values: Array,
    week0: date,
    series: list[tuple[str, str]],
    start: int,
    end: int,
    horizons: int,
) -> Array:
    n_series, n_weeks = values.shape[0], end - start
    codes = model.codes(series)
    targets = np.repeat(np.arange(start, end), horizons)
    hs = np.tile(np.arange(1, horizons + 1), n_weeks)
    origins = targets - hs
    all_series = np.repeat(np.arange(n_series), len(origins))
    flat = predict_scaled(
        model,
        name,
        OriginFeatures(values),
        all_series,
        np.tile(origins, n_series).astype(np.int64),
        np.tile(hs, n_series).astype(np.int64),
        week0,
        codes,
    )
    return flat.reshape(n_series, n_weeks, horizons)


def save_model(model: ForecastModel, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    for name, booster in model.boosters.items():
        booster.save_model(str(directory / f"{name}.txt"), num_iteration=booster.best_iteration)
    meta: dict[str, Any] = {
        "format": MODEL_FORMAT,
        "model_version": model.version,
        "dataset_id": model.dataset_id,
        "config": model.config.model_dump(mode="json"),
        "split": model.split.model_dump(mode="json"),
        "skus": model.skus,
        "regions": model.regions,
        "features": FEATURE_NAMES,
        "best_iterations": model.best_iterations,
        "calibration": model.calibration,
        "boosters": sorted(model.boosters),
    }
    (directory / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
    )
    return meta


def load_model(directory: Path) -> ForecastModel:
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    if meta["format"] != MODEL_FORMAT or meta["features"] != FEATURE_NAMES:
        raise ValueError("model artifact is incompatible with this code version")
    boosters = {
        name: lgb.Booster(model_file=str(directory / f"{name}.txt")) for name in meta["boosters"]
    }
    return ForecastModel(
        boosters=boosters,
        skus=meta["skus"],
        regions=meta["regions"],
        config=ModelConfig.model_validate(meta["config"]),
        dataset_id=meta["dataset_id"],
        split=TemporalSplit.model_validate(meta["split"]),
        best_iterations={k: int(v) for k, v in meta["best_iterations"].items()},
        calibration=meta["calibration"],
    )

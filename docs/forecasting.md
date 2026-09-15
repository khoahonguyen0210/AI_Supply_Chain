# Demand forecasting

Run: `uv run python -m scm_ml.forecast --source synthetic|real`
Artifacts (git-ignored): `ml/artifacts/forecast/<dataset_id>/{dataset,baselines,model}/`.
Committed results: `ml/experiments/forecast/{synthetic,real}.json` - every number below is read from these files.

## Setup

- **Target:** weekly units per SKU x region (200 series x 104 weeks on the real set; 200 x 104 synthetic).
- **Temporal split** (no random split): last 13 weeks test, the 13 before validation, the rest train.
  A row's *target week* decides its split. Walk-forward: a forecast for week `w` at horizon `h` uses only
  actuals up to week `w - h`. Horizons 1-8 weeks (covers supplier lead times up to ~6 weeks).
- **Baselines:** naive, 4- and 13-week moving average, seasonal naive (52 weeks). The comparison
  baseline is chosen on **validation MAE only**.
- **Model:** one global LightGBM (Tweedie objective, rows weighted by series scale) over lag, rolling,
  intermittency, seasonal-lag and calendar features, each divided by the series' recent level.
  Objective and weighting were selected on validation MAE (regression / Poisson / Tweedie x 3 weightings);
  the test window was read once per final run. Early stopping uses validation targets.
- **Uncertainty:** LightGBM quantile models (q10, q90) -> 80% interval, then conformalized quantile
  regression (CQR) offsets fitted per horizon on the validation window.
- **Leakage tests:** features are unchanged when all data after the origin is overwritten; baselines
  likewise; the real-data SKU/region selection ignores post-cutoff data.

## Results (test window, 13 weeks, horizons 1-8 pooled)

| Dataset | Model | MAE | RMSE | Bias | WAPE |
|---|---|---|---|---|---|
| Synthetic | naive | 39.30 | 68.33 | +1.92 | 1.216 |
| Synthetic | 13-wk moving average (selected baseline) | 33.91 | 51.25 | +6.15 | 1.050 |
| Synthetic | **LightGBM** | **30.16** | **47.89** | -1.52 | 0.933 |
| Real (Online Retail II) | naive | 71.90 | 255.48 | -6.42 | 0.822 |
| Real | 13-wk moving average (selected baseline) | 58.16 | 203.84 | -12.17 | 0.665 |
| Real | **LightGBM** | **56.94** | **199.01** | -13.04 | 0.651 |

Test MAE improvement over the selected baseline: **+11.1% synthetic, +2.1% real**.

80% prediction intervals (nominal coverage 0.80):

| Dataset | Window | Raw quantile coverage | Calibrated coverage | Calibrated mean width |
|---|---|---|---|---|
| Synthetic | test | 0.876 | 0.876 | 86.4 |
| Real | validation | 0.729 | 0.802 | 118.8 |
| Real | test | 0.729 | **0.783** | 136.0 |

## Reading the results honestly

- Weekly demand is intermittent compound-Poisson noise (about half of synthetic and two thirds of real
  SKU-region-weeks are zero), so irreducible error is high; MAPE is only defined on non-zero actuals and
  is reported in the JSON but is not a headline metric.
- The real-data gain is small. The test window is the run-up to Christmas and the model has seen only one
  earlier season, hence the negative bias.
- Synthetic intervals are conservative (0.876 vs 0.80) because zero-heavy scores tie at zero and the
  conformal offset cannot shrink them; real-data calibration lifts coverage from 0.729 to 0.783 on test.
- Synthetic test MAE is flat across horizons: with this noise level, a 1-week and an 8-week forecast are
  equally hard.

## Which model is served

`SCM_ML_MODEL_DIR` + `SCM_ML_DATASET_DIR` if set; otherwise a model promoted through the feedback
loop (`ml/artifacts/forecast/serving.json`, written only by an approved promotion, see
`docs/feedback-loop.md`); otherwise the model trained on the world's own history.

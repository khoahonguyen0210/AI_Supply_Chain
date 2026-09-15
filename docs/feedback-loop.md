# Feedback loop

Demand -> Forecast -> ... -> Human Approval -> **Outcome -> Evaluation** -> (gated) retraining.
This phase records what a decision relied on and what actually happened, compares the two, and
offers a reproducible retraining path whose result is never deployed without evaluation and a named
approval.

## 1. Outcome capture

| What | Where it is recorded |
| --- | --- |
| forecast the decision relied on | `forecast_snapshot` (V7): taken by the backend when an approval completes, from the engine's served model, for every region with demand for the recommendation's SKUs over its horizon; model version and dataset id included |
| recommendation | `recommendation`, `recommendation_line` (V1) |
| approved action | `approval`, append-only `decision` (V4), `purchase_order` rows in status `APPROVED` (V1) |
| actual demand | `outcome_demand` (V7): SKU, region, week, units |
| supplier delivery | `outcome_delivery` (V7): delivered date and quantity per purchase order; the order moves to `DELIVERED` |
| inventory outcome | `outcome_inventory` (V7): end-of-week stock and unmet units per SKU, warehouse, week |

The V7 tables are append-only (database trigger): a correction is a newer record and the latest
record for a key is the one evaluated. Each record carries `recorded_by`, `recorded_at` and `source`
(`RECORDED`, or `SIMULATED` for data that came from the simulator).

API (`docs/backend-api.md`): `POST /api/outcomes/demand`, `/deliveries`, `/inventory` and
`/forecast-snapshots/{recommendationId}` need a planning role (`planner`, `procurement_manager`,
`admin`); `finance` gets `403`. Every write and every refusal is in `audit_log`.
`GET /api/outcomes/evaluation?recommendationId=` is open to every signed-in role. Snapshot capture is
best effort: if the engine is down at approval time the approval still stands and
`POST /api/outcomes/forecast-snapshots/{id}` takes it later.

## 2. Evaluation

The rules exist once, in Python (`ml/src/scm_ml/feedback/evaluation.py`), and are used both by the
offline experiment and by the engine endpoint `POST /v1/outcomes/evaluate`, to which the backend
relays the snapshot, the latest recorded outcomes and each supplier's promised reliability.

* **Forecast vs actual demand:** MAE, RMSE, bias, WAPE, MAPE (non-zero actuals), 80% interval
  coverage and width, overall and by horizon; snapshot points without actuals are counted as
  `awaitingActuals`.
* **Planned vs actual delivery:** on-time rate (delivered on or before the promised date), in-full
  rate, unit fill rate, mean and max delay; per supplier, next to the reliability the plan relied on.
* **Planned vs actual inventory:** fill rate, unmet units, stockout cell-weeks, ending stock; the
  offline experiment also matches the planned stock path with the actual one.

### Offline experiment (simulated actuals)

Run: `uv run python -m scm_ml.feedback evaluate` (about 2 minutes; needs the trained synthetic
model, `uv run python -m scm_ml.forecast --source synthetic`). It writes
`ml/experiments/feedback/synthetic.json` (committed) and the simulated actuals as CSV files with a
checksum manifest under `data/outcomes/synthetic/` (git-ignored, reproducible).

It replays the decision path at `as_of` = 2024-12-30: the served model forecasts 8 weeks for all 200
SKU x region series; the network procurement MILP (as in the optimization benchmark: all 40 SKUs, 3
warehouses, 4-week horizon, 95% service target) turns the forecast into a plan; every plan line is
treated as approved and placed at `as_of` (**the approval is simulated**); then the simulated future
happens and is compared with what was planned.

**How actuals are simulated.** Nothing after `as_of` exists in the data, so the same generative
process continues with the same seed, from a fourth random stream that the world never uses:
demand from the world's own demand process (popularity, region weights, seasonality and trend
continued past the history, no promotions); purchase orders open at `as_of` arrive on the date the
generator had already drawn for them but kept out of the world; new orders behave like the
generator's suppliers (on time with the supplier's reliability, otherwise 1-10 days late and half
the time 70-95% short); stock is simulated weekly (receipts at the start of the week, demand served
from stock, unmet demand lost, regions served by their cheapest-lane warehouse as in planning).

Results, read from `ml/experiments/feedback/synthetic.json` (all actuals SIMULATED):

| Forecast vs actual, 8 weeks from 2024-12-30, 1,600 points | MAE | Bias | WAPE | 80% coverage |
| --- | --- | --- | --- | --- |
| LightGBM (served model `lgbm-1f6789b06e`) | 30.665 | -3.746 | 0.914 | 0.859 |
| 13-week moving average | 32.055 | -1.226 | 0.956 | n/a |

| Plan vs actual, 4-week horizon (2024-12-30 to 2025-01-20) | Planned | Actual |
| --- | --- | --- |
| demand units (forecast vs actual) | 22,963.9 | 26,286 |
| fill rate | 1.000 (plan's own aggregate estimate); 0.908 (weekly path with promised deliveries) | 0.803 |
| stockout cell-weeks (of 480) | 77 | 92 |
| unmet units | 2,115.75 | 5,174 |
| ending stock (units) | 12,709.87 | 11,431 |

Plan orders (91 purchase orders, simulated): on-time rate 0.857, in-full rate 0.923, unit fill
rate 0.984, mean delay 0.58 days. Orders open at `as_of` (53): on-time 0.887, unit fill 0.993.
Per cell, ending stock differed from plan by 63.6 units on average (MAE); 62 cell-weeks stocked out
that the plan's own path did not expect.

**Reading it honestly.** Actual demand in the plan horizon was 14% above the forecast (the forecast
is biased low here), which explains most of the gap between planned and actual fill rate. The MILP's
aggregate fill rate of 1.000 ignores timing inside the horizon: replaying the same plan week by week
with promised delivery dates already gives 0.908, because orders with long lead times land after the
early weeks' demand. That is a limitation of the plan model worth knowing, and it is only visible
because outcomes are compared week by week. These numbers come from one simulated future of one
synthetic company; they are not evidence about real operations.

### Recorded outcomes (backend)

`GET /api/outcomes/evaluation` scores whatever has been recorded through the API. Real outcomes have
not been recorded in this repository: results for real data are **NOT YET MEASURED**.

## 3. Retraining and promotion

```
uv run python -m scm_ml.feedback retrain [--actuals data/outcomes/synthetic/demand_actuals.csv]
                                         [--label SIMULATED|RECORDED] [--holdout-weeks 4]
                                         [--min-improvement 0.0] [--max-coverage-error 0.10]
uv run python -m scm_ml.feedback promote --report <report.json> --approved-by <user> [--note ...]
uv run python -m scm_ml.feedback serving
```

* **Input:** weekly demand actuals (`sku_id, region_id, week_start, quantity`), the simulated file or
  real demand exported from `outcome_demand`. The weeks must continue the current model's history
  without a gap; unknown series are rejected; a missing (series, week) is zero demand, as in history.
* **Reproducible:** same code, model config and seed as the current model (LightGBM is run
  deterministic, single-threaded); the report records the actuals' SHA-256, the candidate's panel
  SHA-256 and dataset id, the split, the code revision and both model versions.
* **Fair comparison:** the newest `holdout-weeks` of actuals are held out. The candidate is trained
  and calibrated only on weeks before them (history + the earlier actuals, default temporal split);
  current model, candidate and the 13-week moving average then forecast the held-out weeks walk-forward
  with identical inputs.
* **Gate:** the candidate's held-out MAE must be below the current model's by `--min-improvement`,
  and its calibrated 80% coverage within `--max-coverage-error` of 0.80. The report's status is
  `AWAITING_APPROVAL` or `REJECTED_BY_GATE`. **Retraining never deploys anything.**
* **Promotion:** `promote` refuses a report whose gate failed, a blank approver, or artifacts that
  changed since evaluation (model version or dataset checksum differ). On success it writes
  `ml/artifacts/forecast/serving.json` (approver, time, note, report checksum, previous version) and
  appends to `promotions.jsonl`. The engine serves the promoted model after a restart
  (`docs/forecasting.md`); deleting `serving.json` reverts to the original model.

Result of `retrain` on the simulated actuals, read from
`ml/experiments/feedback/retraining-synthetic.json`: 8 captured weeks, held-out weeks 2025-01-27 to
2025-02-17 (4 weeks x 200 series x 8 horizons).

| Model | Held-out MAE | Bias | 80% coverage |
| --- | --- | --- | --- |
| current `lgbm-1f6789b06e` | 31.176 | -3.173 | 0.867 |
| candidate `lgbm-deb945aea1` (history + 4 captured weeks) | 31.279 | -3.163 | 0.788 |
| 13-week moving average | 32.826 | -2.043 | n/a |

Gate: **failed** (candidate MAE not below the current model's), status `REJECTED_BY_GATE`; nothing
was promoted. Four extra weeks of a noisy, intermittent series do not make a better model, and the
gate is what keeps a slightly worse one from being deployed. The candidate's intervals are closer to
nominal (0.788 vs 0.867), which the gate does not reward on its own.

## Limitations

* All outcome numbers above are simulated; the approval of the plan in the experiment is simulated
  too. No real outcomes have been recorded.
* The simulated future continues the same process the model was trained on, so it cannot show
  concept drift; it shows forecast noise, supplier unreliability and the plan model's timing gap.
* Stock simulation is weekly with receipts at the start of the week and lost sales; transfers between
  warehouses are not modelled.
* The backend evaluation joins snapshots to recorded demand by SKU, region and week; snapshots are
  per recommendation, so two recommendations covering the same weeks are both scored.
* Retraining is a command, not a schedule; promotion takes effect when the engine restarts.

# Scenario engine

Code: `ml/src/scm_ml/scenario/`. Run: `uv run python -m scm_ml.scenario` (needs the trained forecast
model). Results: `ml/experiments/scenario/synthetic.json`; every number below is read from that file.

## Contract (Task 6.1)

`contract.py` defines a typed, validated parameter model for each of the seven `ScenarioType`s
(factors are multipliers: 1.2 = +20%, 0.7 = -30%; a missing scope means everywhere). The domain
`Scenario` keeps a flat `parameters` mapping so it persists as JSON; `parse_parameters` validates it
and rejects unknown, missing or out-of-range fields with the offending field named.

| Type | Parameters |
|---|---|
| `DEMAND_SHOCK` | `factor` (0-10], optional `sku_id`, `region_id` |
| `SUPPLIER_OUTAGE` | `supplier_id` |
| `PRICE_SHOCK` | `factor`, optional `supplier_id`, `sku_id` |
| `CAPACITY_REDUCTION` | `factor` in (0, 1], optional `supplier_id` |
| `LEAD_TIME_SHOCK` | `days` 1-180, optional `supplier_id` |
| `WAREHOUSE_CAPACITY_REDUCTION` | `factor` in (0, 1], optional `warehouse_id` |
| `TRANSPORT_COST_SHOCK` | `factor`, optional `supplier_id` (unscoped also scales outbound lanes) |

`standard_scenarios` builds the seven required disruptions (demand +20%, supplier outage, price +15%,
capacity -30%, lead time +7 days, warehouse capacity -20%, transport +25%).

## Execution (Task 6.2)

`run_pipeline` is the single decision pipeline: forecast demand -> procurement MILP -> allocation
MILP. `run_scenario` pushes baseline and scenario through it and produces three plans:

- **baseline**: optimal plan for undisturbed inputs;
- **disrupted**: the baseline purchase plan held fixed and executed in the disrupted world (orders to
  vanished offers are lost, orders over a supplier's remaining capacity are cut pro rata, the rest
  are repriced), with fulfillment re-optimized on the stock that actually arrives;
- **response**: the pipeline re-optimized for the disrupted inputs.

`apply_scenario` returns the disrupted inputs plus `AssumptionChange` records (what changed, scope,
entities affected, before/after), so the changed assumptions are visible. Runs are deterministic: the
same inputs give identical plans and comparisons (tested).

## Comparison (Task 6.3)

`compare_scenario` reports, per scenario: objective delta (disrupted and response vs baseline),
service-level delta (customer fill rate after allocation), binding constraints (before/after, newly and
no longer binding), changed allocations (purchase lines, supplier shifts, shipment routes) and
**resilience cost** = response objective - baseline objective (the extra cost of the best response);
`response_benefit` = disrupted objective - response objective (what re-planning saves versus holding
the baseline plan).

Setup: dataset `synthetic-ef2dbee886f5`, forecast model `lgbm-1f6789b06e`, 4-week horizon
from 2024-12-30, baseline objective 302,532; the outage scenario removes the
baseline's busiest supplier (SUP-002).

| Scenario | Assumption changed | Objective delta, disrupted | Objective delta, response (= resilience cost) | Response benefit | Service delta, disrupted | Service delta, response | Changed purchase lines / units |
|---|---|---|---|---|---|---|---|
| Demand +20% | forecast demand (units over horizon): 22,963.9 -> 27,556.7 (200 affected) | +219,701 | +124,311 (+41.1%) | 95,390 | -0.0062 | +0.0000 | 107 / 6,389 |
| Supplier outage (SUP-002) | offers available: 18.0 -> 0.0 (18 affected) | +109,513 | +4,217 (+1.4%) | 105,295 | -0.0292 | +0.0000 | 47 / 5,500 |
| Supplier price +15% | mean offer unit price: 27.9 -> 32.1 (206 affected) | +43,567 | +43,510 (+14.4%) | 57 | +0.0000 | +0.0000 | 20 / 1,627 |
| Supplier capacity -30% | total weekly supplier capacity (units): 23,679.0 -> 16,499.0 (206 affected) | +14,436 | +427 (+0.1%) | 14,009 | -0.0019 | +0.0000 | 34 / 3,336 |
| Lead time +7 days | mean offer lead time (days): 20.2 -> 27.2 (206 affected) | +212,040 | +45,568 (+15.1%) | 166,472 | -0.0711 | -0.0027 | 117 / 11,996 |
| Warehouse capacity -20% | warehouse capacity (units): 22,400.0 -> 17,920.0 (3 affected) | +0 | -5 (-0.0%) | 5 | +0.0000 | +0.0000 | 14 / 1,669 |
| Transport cost +25% | mean inbound shipping cost per unit: 0.8 -> 0.9 (206 affected) | +1,404 | +1,354 (+0.4%) | 50 | +0.0000 | +0.0000 | 20 / 1,592 |

Binding constraints (counts by kind; "newly binding" shows up to three):

| Scenario | Baseline | Response | Newly binding in response |
|---|---|---|---|
| Demand +20% | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 7, 'SUPPLIER_CAPACITY': 2, 'WAREHOUSE_STOCK': 2} | MOQ SUP-002/SKU-007->WH-2, MOQ SUP-006/SKU-004->WH-1, MOQ SUP-006/SKU-023->WH-2 |
| Supplier outage (SUP-002) | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 10, 'SUPPLIER_CAPACITY': 2, 'WAREHOUSE_STOCK': 2} | MOQ SUP-001/SKU-028->WH-2, SUPPLIER_CAPACITY SUP-005/SKU-018, SUPPLIER_CAPACITY SUP-006/SKU-003 |
| Supplier price +15% | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 7, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | none |
| Supplier capacity -30% | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 12, 'SUPPLIER_CAPACITY': 3, 'WAREHOUSE_STOCK': 2} | MOQ SUP-002/SKU-034->WH-1, MOQ SUP-006/SKU-023->WH-2, MOQ SUP-007/SKU-025->WH-3 |
| Lead time +7 days | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 12, 'SERVICE_LEVEL': 1, 'WAREHOUSE_STOCK': 5} | MOQ SUP-001/SKU-022->WH-2, MOQ SUP-001/SKU-028->WH-2, MOQ SUP-003/SKU-001->WH-3 |
| Warehouse capacity -20% | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 10, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | MOQ SUP-001/SKU-028->WH-2 |
| Transport cost +25% | {'MOQ': 9, 'SUPPLIER_CAPACITY': 1, 'WAREHOUSE_STOCK': 2} | {'MOQ': 11, 'WAREHOUSE_STOCK': 2} | MOQ SUP-001/SKU-028->WH-2, MOQ SUP-002/SKU-034->WH-1 |

## Reading the results

- Objective deltas are cost-model values (purchase, shipping, fixed, holding and penalty terms), not
  realised profit. Demand is the forecast point value; forecast error is not simulated.
- Small negative or near-zero resilience costs (for example warehouse capacity -20%) are within the
  solver's relative MIP gap (1e-4), not real savings: that disruption does not bind on this world.
- A negative service delta in the response means the disruption made the 95% target unreachable even
  after re-optimizing (for example when lead times push offers out of the horizon).

# Optimization (procurement and allocation)

Code: `ml/src/scm_ml/optimization/`. Solver: SciPy `milp` (HiGHS). Run: `uv run python -m scm_ml.optimization`
(needs the trained forecast model: `uv run python -m scm_ml.forecast`). Results are written to
`ml/experiments/optimization/synthetic.json`; every number below is read from that file.

## Procurement (Task 5.1)

Per planning cell (SKU at warehouse) the MILP chooses integer order quantities per usable offer.
Hard constraints: supplier MOQ, supplier weekly capacity x horizon, contract order-value limit,
budget, and warehouse capacity (net of stock already stored). Offers that are invalid on the decision
date, uncertified, without an active contract, without a lane, or slower than the horizon are excluded
before solving (lead time). Demand and safety stock are met through penalised shortfall variables
(unmet demand costs the SKU price per unit, shortfall below safety stock costs one price per unit),
and the **service level is elastic**: the target fill rate is a constraint with a heavily penalised
slack, so an unreachable target is reported as an explicit `SERVICE_LEVEL` violation instead of an
opaque infeasibility. Reliability derates arrivals (units that arrive = reliability x ordered).

Objective = purchase + shipping + fixed order cost + holding + stockout + safety-shortfall penalties.
`evaluate_plan` recomputes the objective, fill rate and every violation from the purchase lines
alone; it scores the optimizer and the heuristics identically, and tests assert it agrees with the
solver's own objective.

## Allocation (Task 5.2)

`solve_allocation` ships post-procurement stock from warehouses to regional demand (integer
transportation problem) minimising lane cost plus stockout penalty, subject to stock per warehouse,
an optional transit-day limit, and the same elastic service level. `evaluate_allocation` measures
unmet units, fill rate, mean transit days and flags stock, lane, transit and over-demand violations.
Baseline: `nearest_warehouse_rule` (cheapest lane first, regions served first-come-first-served).

## Heuristic baselines (Task 5.3)

`reorder_up_to`: order demand + safety stock - stock on hand/on order, raised to MOQ, from the
cheapest supplier by landed cost (`cheapest`) or the Phase 4 weighted ranking (`weighted`), spilling
to the next supplier when capacity runs out. It ignores reliability, budget and warehouse capacity.

## Benchmark

Setup: synthetic world seed 42 (`synthetic-ef2dbee886f5`), forecast model `lgbm-1f6789b06e`,
4-week horizon from 2024-12-30, service target
95%, total forecast demand
22,964 units. `tight_budget` allows
85% of the unconstrained optimum's spend (253,586).
Runtime is wall-clock on the machine that ran the benchmark.

| Case | Method | Objective | Spend | Fill rate | Constraint violations | Runtime (s) |
|---|---|---|---|---|---|---|
| base | heuristic_cheapest | 348,675 | 282,864 | 0.9967 | SERVICE_LEVEL x4 | 0.00 |
| base | heuristic_weighted | 357,384 | 323,283 | 0.9987 | SERVICE_LEVEL x1 | 0.05 |
| base | milp | 302,532 | 298,336 | 1.0000 | none | 4.58 |
| tight_budget | heuristic_cheapest | 348,675 | 282,864 | 0.9967 | BUDGET x1, SERVICE_LEVEL x4 | 0.00 |
| tight_budget | heuristic_weighted | 357,384 | 323,283 | 0.9987 | BUDGET x1, SERVICE_LEVEL x1 | 0.03 |
| tight_budget | milp | 326,464 | 253,585 | 1.0000 | none | 3.40 |

MILP objective versus the better heuristic: 13.2% lower in `base`, 6.4% lower in `tight_budget`. Both MILP solves reach `OPTIMAL` (relative MIP gap below 1e-4).

End-to-end allocation of each procurement plan's resulting stock:

| Case | Procurement | Allocation | Objective | Fill rate | Unmet units | Mean transit days |
|---|---|---|---|---|---|---|
| base | heuristic_cheapest | milp | 25,093 | 1.0000 | 0 | 1.38 |
| base | heuristic_cheapest | nearest_warehouse_rule | 25,116 | 1.0000 | 0 | 1.38 |
| base | heuristic_weighted | milp | 25,066 | 1.0000 | 0 | 1.37 |
| base | heuristic_weighted | nearest_warehouse_rule | 25,071 | 1.0000 | 0 | 1.37 |
| base | milp | milp | 25,048 | 1.0000 | 0 | 1.37 |
| base | milp | nearest_warehouse_rule | 25,048 | 1.0000 | 0 | 1.37 |
| tight_budget | heuristic_cheapest | milp | 25,093 | 1.0000 | 0 | 1.38 |
| tight_budget | heuristic_cheapest | nearest_warehouse_rule | 25,116 | 1.0000 | 0 | 1.38 |
| tight_budget | heuristic_weighted | milp | 25,066 | 1.0000 | 0 | 1.37 |
| tight_budget | heuristic_weighted | nearest_warehouse_rule | 25,071 | 1.0000 | 0 | 1.37 |
| tight_budget | milp | milp | 25,192 | 0.9998 | 5 | 1.37 |
| tight_budget | milp | nearest_warehouse_rule | 25,200 | 0.9998 | 5 | 1.37 |

## Reading the results

- The heuristic plans miss the service target in some cells because they ignore supplier reliability;
  in `tight_budget` they also breach the budget. The optimizer reports zero violations in both cases.
- Allocation gains over the nearest-warehouse rule are small on this world because warehouse stock is
  abundant relative to regional demand over the horizon; the optimizer matters when stock is scarce
  (see the first-come-first-served unit test). A scarce-stock stress case is left to the final benchmark.
- The objective includes modelled penalties (stockout, safety shortfall); it is a cost model, not
  realised profit. Demand is the forecast point value, so forecast error is not simulated here.

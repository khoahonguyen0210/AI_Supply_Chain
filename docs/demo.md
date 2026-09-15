# Demo: one planner decision, end to end

One story through the running stack, driven only through the public API (the same calls the web UI
makes). Run it, or click through the same flow in the UI at <http://localhost:3000>.

```bash
bash scripts/stack.sh up                                   # prints the demo password
uv run python -m scm_ml.demo --password <demo password>    # --url defaults to http://localhost:3000
```

The smoke suite runs the same script against a stack (`tests/smoke`, `SCM_SMOKE_URL` and
`SCM_SMOKE_PASSWORD`), so the demo is tested, not just documented.

## The story

| # | Step | What happens | Where |
|---|---|---|---|
| 1 | Planner asks a vague question | "I'm worried we will run short on something next month." The copilot does not guess a product: `NEEDS_CLARIFICATION`. The planner answers in the same conversation: SKU-001 demand may rise 20%. | Copilot page, `POST /api/agent/tasks` |
| 2 | Forecast | `get_forecast`: LightGBM forecast with 80% intervals per region | [forecasting.md](forecasting.md) |
| 3 | Inventory need | `assess_inventory_need`: on hand, incoming, safety stock, net requirement per warehouse | [optimization.md](optimization.md) |
| 4 | Suppliers filtered and ranked | `search_suppliers`: hard eligibility rules, then a weighted ranking with reasons | [sourcing.md](sourcing.md) |
| 5 | Optimised plan | `optimize_procurement`: MILP (HiGHS) over suppliers, warehouses, MOQ, capacity, budget, service level | [optimization.md](optimization.md) |
| 6 | Disruption scenario | `run_scenario`: demand shock and an outage of the plan's main supplier, hold-the-plan vs re-optimise | [scenarios.md](scenarios.md) |
| 7 | Policy and contract evidence | `search_policies`: grounded answers with versioned citations (approval policy, supplier contract) | [knowledge-answering.md](knowledge-answering.md) |
| 8 | Copilot explains trade-offs | every number in the answer comes from a tool result (guardrail `grounded_numbers`) | [agent.md](agent.md) |
| 9 | Planner approves? No: policy decides | the requester cannot approve their own order (`403`); the roles the approval policy names approve | Approvals page, [security.md](security.md) |
| 10 | Decision recorded | append-only `decision` rows, approved purchase orders, audit log | [backend-api.md](backend-api.md) |
| 11 | Outcome evaluated later | the forecast the decision relied on was snapshotted at approval; actual demand is recorded and scored against it | [feedback-loop.md](feedback-loop.md) |

## A recorded run

Local Compose stack, 2026-10-07, rule planner (offline, no API key), synthetic world as of
2024-12-30. Long tool results are cut; ids differ between runs.

```text
 1. The planner asks a vague question
    "I'm worried we will run short on something next month. What should I do?"
    copilot status: NEEDS_CLARIFICATION
    Which product do you mean? Please give a SKU id or the product name.

    The planner is specific: "Demand for SKU-001 is expected to rise by 20%. What should I do?"
    copilot status: AWAITING_APPROVAL

 2-7. (tool calls: get_forecast, assess_inventory_need, search_suppliers, optimize_procurement,
       run_scenario x2, search_policies x2)
    - [POL-APPROVAL v2] Orders above USD 15,000 require procurement manager approval.
    - [CTR-SUP-008 v1] Order limits. No per-order value cap applies to purchase orders under this agreement.

 8. The copilot explains the trade-offs
    Forecast demand for SKU-001 over the next 4 weeks is 1,069.6 units (lgbm-1f6789b06e). By region:
    R1 297.5 units (80% range 22.3 to 491.8); R2 275.4 units ...
    On hand 621 units, incoming 0, safety stock 230. Against forecast demand of 1,283.5 units over 4
    weeks the net purchase requirement is 893 units; WH-3 is the neediest warehouse.
    1 suppliers are eligible. Top ranked is SUP-003 at 78.103 per landed unit, 0.0% above the cheapest
    eligible offer, lead time 17 days, reliability 0.886.
    Optimized plan (OPTIMAL): buy 940 units in 4 orders (SUP-003 283 units, SUP-008 657 units), order
    value 78,126, total cost 78,639, fill rate 100.0%. It satisfies every constraint. The plan buys
    mainly from SUP-008 rather than top-ranked SUP-003: ranking weighs reliability and lead time, while
    the optimizer minimises total cost under the constraints.
    Allocating the stock to regions fills 100.0% of regional demand with mean transit of 1.36 days.
    DEMAND_SHOCK (factor=1.2): holding the plan costs 42,043 more; re-optimizing costs 22,588 more
    (resilience cost 22,588) and saves 19,454 versus holding the plan; customer fill rate after
    response 100.0%.
    SUPPLIER_OUTAGE (supplier_id=SUP-008): holding the plan costs 98,405 more; re-optimizing costs 957
    more and saves 97,448 versus holding the plan; customer fill rate after response 100.0%.
    Policy check: Orders above USD 15,000 require procurement manager approval. [POL-APPROVAL version 2]
    Recommendation ... is pending approval from procurement_manager, finance; order value 78,126.
    Nothing is ordered until it is approved.

 9. Human approval
    approval APR-0020: status PENDING, needs procurement_manager, finance
    the planner tries to approve their own request: HTTP 403
    manager (procurement_manager) approved
    finance (finance) approved

10. The decision is recorded
    approval APPROVED, recommendation APPROVED
    - manager as procurement_manager: APPROVED at 2026-10-07T21:17:17.347262Z
    - finance as finance: APPROVED at 2026-10-07T21:17:19.651059Z

11. Later: the outcome is recorded and evaluated
    recorded 40 weekly demand actuals for SKU-001 (source SIMULATED)
    forecast snapshot of model lgbm-1f6789b06e: 20 points scored, 0 awaiting actuals
    forecast vs actual: mae 24.254, rmse 31.793, bias -4.721, wape 0.417, mape 0.492, coverage 0.800
    supplier deliveries: 0 delivered, 4 pending
```

## What is real and what is not

* Real: every tool call, number, citation, permission check, approval and database record above is
  produced by the running services.
* Simulated: the company (synthetic world, seed 42) and the actual demand in step 11, which is drawn
  by continuing the world's own demand process past the planning date and is labelled `SIMULATED`
  in the database. Deliveries stay pending because none were recorded.
* The copilot's planner is the deterministic rule planner. With `SCM_ML_PLANNER=claude` and an
  `ANTHROPIC_API_KEY` the same tools are driven by Claude; that path is NOT YET MEASURED.

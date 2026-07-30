# AI copilot (agent)

Code: `ml/src/scm_ml/agent/`. The agent is a tool-using planner, not a model trained for the task. A planner picks
one action at a time; a runner executes it behind guardrails and records every step.

```
task -> clean/validate -> planner.next_action -> authorize -> validate args -> tool -> check result
        ^                                                                                  |
        +-------------------------- observation / re-plan <--------------------------------+
final answer -> numbers must be backed by tool results -> persist -> AgentRun
```

## Tools (Task 8.1)

Typed arguments (strict pydantic models, JSON schema exposed to the model), plain JSON results, no business logic
reimplemented: each tool calls the existing forecast, sourcing, optimization, scenario or knowledge code.

| Tool | Wraps | Roles |
|---|---|---|
| `get_forecast` | forecast service (1-8 weeks, 80% interval per region) | all |
| `get_inventory` | inventory positions | all |
| `assess_inventory_need` | forecast + stock + safety stock, per warehouse | all |
| `search_suppliers` | eligibility, ranking, comparison; flags an ineligible cheapest supplier | all |
| `get_supplier_performance` | supplier record, contracts, delivery history | all |
| `search_policies` | grounded RAG answer, filtered to the user's role | all |
| `optimize_procurement` | procurement + allocation MILP, stores a `plan_id` | all |
| `plan_fulfillment` | allocation of a stored plan | all |
| `run_scenario` | scenario engine on a stored plan | all |
| `prepare_purchase_order` | **consequential**: opens an approval request, orders nothing | planner, procurement manager, admin |

Plans belong to the user who created them. Tool failures are `ToolError`s with a code the planner can react to
(`UNKNOWN_SKU`, `INVALID_SCENARIO`, `PLAN_HAS_VIOLATIONS`, ...).

## Planners (Task 8.2)

* `RulePlanner`: deterministic and offline. It parses the request into an intent (plan, sourcing, scenario, policy,
  performance, forecast, inventory, approve, unknown), then derives the next step from the observations so far. The
  full workflow is forecast -> inventory -> suppliers -> optimize -> fulfillment -> demand and outage stress tests ->
  supplier check -> policy and contract checks -> prepare order. It re-plans when a result requires it: an invalid
  horizon is clamped and disclosed, no supplier meeting the lead time retries with a longer one, and a budget that
  makes the service target unreachable re-prices the plan without the budget and reports both instead of ordering.
* `ClaudePlanner`: asks Claude for the same decision through `JsonLlm` (structured output). It is shown only the tools
  its user's role may call.

Both return the same `Action` types, so the runner and guardrails do not depend on which one is used.

## State and memory (Task 8.3)

`SqliteStateStore` keeps the task (text, actor, status, trace, answer), approval requests and an append-only
decision log (triggers reject UPDATE and DELETE, mirroring the PostgreSQL `decision` table). Tool results needed for
the current task live in the trace. There is no user preference or long-term memory.

## Guardrails (Task 8.4)

| Guardrail | Where |
|---|---|
| Input validation (empty, length, control characters) | `clean_task_text` |
| Refusal of requests to skip approval, self-approve, ignore rules, reveal instructions | `check_unsafe_request` |
| Tool authorization by role | `authorize` |
| Tool argument validation | `validate_arguments` |
| Document permission filtering | retrieval, before any text reaches the model |
| Result sanity (finite, rates in [0, 1], non-negative counts, spend within budget) | `check_tool_result` |
| Numerical grounding of the final answer | `unsupported_numbers`: a number must match a tool result, a policy quote or the user's message at the precision it is written. A model that writes an unbacked number is told once or twice, then the task fails without an answer. |
| Loop limits | step cap, identical-call detection, planner and tool exceptions contained |

## Human approval (Task 8.5)

The agent can only call `ApprovalService.request`; no tool decides an approval. Required approvers follow the
purchase-order approval policy version in force (thresholds are parsed from `POL-APPROVAL`): the buyer up to the
manager threshold, a procurement manager above it, plus finance above the finance threshold. Above the manager
threshold a requester cannot approve their own order, one person cannot fill two roles, and any rejection closes the
approval. Every decision is appended to the decision log.

## Not measured

The rule planner is a scripted workflow, so its evaluation (docs/agent-evaluation.md) measures the harness, guardrails
and tools, not language-model planning. Claude-planned runs are `NOT YET MEASURED` (no API key in this environment).

# Planning-engine API (ML service, contract version 1)

The Python service owns every planning computation. The Spring backend authenticates the user,
passes the user as `actor`, relays the call and stores the durable result. It never recomputes
rankings, plans, scenarios, answers or approval rules.

All requests carry `schemaVersion: "1"` and an `actor` (`userId`, `role`). All JSON is camelCase.
Successful responses are `{ "schemaVersion": "1", "data": { ... } }`; failures use the shared error
body `{ "code", "message" }` (`error-response-v1.schema.json`).

| Endpoint | Request schema | `data` |
| --- | --- | --- |
| `POST /v1/forecast` | `forecast-request-v1` | (unwrapped) `forecast-response-v1` |
| `POST /v1/suppliers/search` | `supplier-search-request-v1` | ranked eligible suppliers, rejections with reasons, cheapest-overall, trade-offs |
| `POST /v1/suppliers/performance` | `supplier-performance-request-v1` | reliability, quality, certifications, delivery history, contracts in force |
| `POST /v1/plans/optimize` | `plan-optimize-request-v1` | plan id, objective, spend, fill rate, violations, purchase lines, binding constraints |
| `POST /v1/scenarios/run` | `scenario-run-request-v1` | `{ plan, scenario }`: the plan is solved afresh, then stressed; baseline / disrupted / re-optimized deltas |
| `POST /v1/documents/ask` | `document-question-request-v1` | cited answer filtered to the actor's role, or why none is given |
| `POST /v1/agent/tasks` | `agent-task-request-v1` | task id, status, answer, trace, citations, assumptions, guardrail violations, approval id |
| `GET /v1/agent/tasks/{taskId}` | | the stored task with its trace |
| `GET /v1/approvals?status=` | | `{ approvals: [...] }` |
| `GET /v1/approvals/{approvalId}` | | the approval, its recommendation, required and approved roles |
| `POST /v1/approvals/{approvalId}/decision` | `approval-decision-request-v1` | the updated approval |

The shape of `data` is the documented output of the matching agent tool (`docs/agent.md`) with keys
converted to camelCase; data keys such as supplier ids are left alone.

## Errors

| Status | Codes |
| --- | --- |
| 403 | `NOT_AUTHORIZED`, `SELF_APPROVAL`, `DUPLICATE_APPROVER` |
| 404 | `UNKNOWN_SKU`, `UNKNOWN_SUPPLIER`, `UNKNOWN_WAREHOUSE`, `UNKNOWN_TASK`, `UNKNOWN_APPROVAL` |
| 409 | `ALREADY_DECIDED`, `ALREADY_REQUESTED` |
| 422 | `VALIDATION_FAILED`, `INVALID_ARGUMENTS`, `INVALID_SCENARIO`, `SOURCING_ERROR`, other tool errors |
| 500 | `INVALID_RESULT` (a tool result failed its numerical sanity check) |

## Operations

* `SCM_ML_PLANNER` (`rule` default, `claude` needs `ANTHROPIC_API_KEY`), `SCM_ML_EMBEDDER`
  (`hashing` default, `fastembed`), `SCM_ML_STATE_PATH` (SQLite file for tasks and approvals;
  in memory by default, so approvals do not survive a restart unless it is set).
* Engine calls are serialized and run in the threadpool, so `/health` stays responsive.
* The backend persists every result it relays (jobs, agent tasks, approvals, decisions), so the
  durable record does not depend on the engine process.

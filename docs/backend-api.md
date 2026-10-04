# Backend API

Spring Boot service on port 8080. It owns authentication context, persistence, async jobs and the
approval record. Every planning computation (forecast, supplier ranking, optimization, scenarios,
policy answers, agent runs, approval rules) is relayed to the Python engine
(`docs/contracts/engine-api.md`); the Java side never recomputes them.

Callers sign in (`POST /api/auth/login`) or create a planner account (`POST /api/auth/register`) and send
the returned token as `Authorization: Bearer <token>`; the role in it (`planner`, `procurement_manager`,
`finance`, `admin`) decides what they may do ([security.md](security.md)). A request without it is `401`.
Errors always use `{ timestamp, status, code, message, path, violations }`; an engine failure keeps
the engine's status and code.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/login`, `POST /api/auth/register`, `GET /api/auth/me` |
| Forecasts | `POST /api/forecasts` (synchronous), or a `FORECAST` job |
| Data | `GET /api/regions`, `GET /api/skus`, `GET /api/demand?skuId&regionId&weeks`, `GET /api/inventory?skuId` |
| Suppliers | `GET /api/suppliers?regionId&certification&minReliability`, `GET /api/suppliers/{id}` (contracts, offers), `GET /api/suppliers/{id}/performance`, `POST /api/suppliers/search` (ranking; planning roles) |
| Recommendations | `GET /api/recommendations?status`, `GET /api/recommendations/{id}` (lines, approval, decisions) |
| Scenarios | `POST /api/scenarios`, `GET /api/scenarios`, `GET /api/scenarios/{id}`, `POST /api/scenarios/{id}/runs` (queues a `SCENARIO` job) |
| Documents | `GET /api/documents?docType&supplierId&asOf&includeSuperseded`, `GET /api/documents/{id}?version&asOf`, `POST /api/documents/ask` |
| Copilot | `POST /api/agent/tasks`, `GET /api/agent/tasks/{id}`, `GET /api/agent/conversations`, `GET /api/agent/conversations/{id}` |
| Approvals | `GET /api/approvals?status`, `GET /api/approvals/{id}`, `POST /api/approvals/{id}/decision` |
| Jobs | `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs` (see `docs/async-jobs.md`) |
| Outcomes | `POST /api/outcomes/demand`, `POST /api/outcomes/deliveries`, `POST /api/outcomes/inventory`, `POST /api/outcomes/forecast-snapshots/{recommendationId}` (planning roles), `GET /api/outcomes/evaluation?recommendationId` (see `docs/feedback-loop.md`) |

## Rules worth knowing

* **Permissions.** Documents are filtered by the caller's role in SQL; a document the role may not
  read is `404`, not `403`. Jobs, agent tasks and conversations are private to their owner.
  Scenario creation/runs and supplier search need a planning role.
* **Recommendations come from the copilot.** When an agent task ends `AWAITING_APPROVAL`, the
  backend stores the recommendation, its lines and the approval request, so it appears in the queue.
* **Approvals.** The engine decides who may approve and when an approval is complete (manager and
  finance thresholds, no self-approval above the manager threshold). The backend relays the decision;
  on success it stores the approval state and appends an immutable `decision` row (a database trigger
  forbids update and delete). Only when the approval is complete are purchase orders created, one per
  line, in status `APPROVED`; placing them with suppliers is outside the system. An engine refusal is
  returned unchanged and nothing is stored. After a complete approval the backend also stores the
  forecast the recommendation relied on (`forecast_snapshot`), best effort: if the engine cannot be
  reached the approval still stands and the snapshot can be taken later.
* **Outcomes are append-only.** Recorded demand, deliveries and stock are never updated; a correction
  is a newer record and the latest one counts. A delivery also moves its purchase order to
  `DELIVERED`. The evaluation is computed by the engine from what the backend gathered.
* **Long work is a job.** Optimization and scenarios are asynchronous; the copilot and forecast calls
  are synchronous. The engine read timeout is `scm.ml-read-timeout` (120s).

## Data for local runs

`uv run python -m scm_ml.synthetic.sql_export` writes `data/seed/synthetic-seed.sql` (master data,
inventory, delivery history, weekly demand, policy documents); load it with `psql` after the
migrations. It is idempotent. The engine must run with `SCM_ML_STATE_PATH` set so approvals and ids
survive an engine restart.

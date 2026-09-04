# Testing

Four layers, from fast and isolated to slow and whole-stack. Every command runs locally; none needs an API key.

| Layer | Command | Needs |
|---|---|---|
| Python unit + integration | `bash scripts/check.sh` (pytest, ruff, mypy) | Docker for the pgvector tests (skipped without it) |
| Java unit + integration | `.\mvnw.cmd test` in `backend/` (`./mvnw test` elsewhere) | Docker (Testcontainers) |
| Frontend | `node node_modules/vitest/vitest.mjs run` in `frontend/` | - |
| End to end | `bash scripts/e2e.sh` | Docker, Java 21, the trained synthetic forecast model |
| AI regression | `bash scripts/ai-regression.sh` | nothing (trains the forecast model if missing) |
| Deployment smoke | `bash scripts/stack.sh smoke` (Compose) | a running stack ([containers.md](containers.md)) |

## Unit tests (12.1)

Core logic is tested where it lives: synthetic world generation and validation, forecast features, baselines, model
and interval calibration (`ml/tests/test_forecast_*`), supplier eligibility and ranking (`test_sourcing.py`),
procurement and allocation optimisation including infeasibility and binding constraints (`test_procurement.py`,
`test_allocation.py`, `test_optimization_benchmark.py`), scenarios, chunking, retrieval, answering, guardrails and the
agent runtime. Shared domain models are tested in `tests/unit/`. The Java side unit-tests the rate limiter, error
mapping and the engine clients; the frontend tests its API client, session handling and pages.

## Integration tests (12.2)

| Boundary | Tests |
|---|---|
| Spring ↔ DB | every `@SpringBootTest` runs against one throwaway pgvector PostgreSQL with Flyway migrations (`support/PostgresContainerConfig`); `DatabaseSchemaTest` pins the schema |
| Spring ↔ Python | contract tests on both sides of `docs/contracts/*.json`: `PythonEngineClientTest` / `PythonForecastClientTest` (Java requests and parsing), `ml/tests/test_engine_api.py` (Python responses); `MlServiceConfigTest` checks the real HTTP client against a real local server; the live path is covered end to end below |
| API ↔ queue | `JobControllerTest`: submit, poll, ownership and validation through the HTTP API |
| worker ↔ DB | `JobQueueTest`: concurrent workers run every job exactly once (`FOR UPDATE SKIP LOCKED`), lease takeover after a crashed worker, retries with backoff, failure after the last attempt, durable results |
| agent ↔ tools | `ml/tests/test_agent_tools.py`, `test_agent_runtime.py`: typed tools on a real (small) planning context, permissions, approval creation |
| RAG ↔ vector store | `ml/tests/test_pgstore.py` (Python ingestion and search on pgvector) and `KnowledgeStoreTest` (the same tables from Spring) |

## End-to-end test (12.3)

`tests/e2e/test_planner_workflow.py` starts PostgreSQL, the built backend jar and the Python engine as separate
processes and drives them only through the public HTTP API with real logins: the planner asks the primary question,
receives a forecast-backed recommendation with evidence, the approvers named by the policy approve it, and the approved
purchase orders appear. It is opt-in (`SCM_E2E=1`, set by `scripts/e2e.sh`) because it builds the jar and starts
three services.

## AI regression suite (12.4)

`python -m scm_ml.regression` (or `scripts/ai-regression.sh`) runs the fixed evaluation sets offline: the 56 RAG
cases ([rag-evaluation.md](rag-evaluation.md)) and the 40 agent cases ([agent-evaluation.md](agent-evaluation.md)),
with the bge-small embedder, the extractive generator and the rule planner. It compares the run with
`ml/configs/ai-regression-baseline.json` and exits 1 when:

* a case that passed in the baseline now fails (case-level, not only averages);
* a tracked metric gets worse (hit@k, MRR, status/answer/citation accuracy, groundedness, over-refusal, wrong answers,
  restricted leaks; workflow success and every agent scoring dimension);
* the evaluation set changed (cases added or removed), so the baseline must be regenerated deliberately.

Cases that start passing are listed as improvements. To accept a change, run with `--update-baseline` and commit the
baseline diff with the change that caused it.

Artifacts go to `ml/artifacts/regression/` (git-ignored) or `--out`: `rag.json` and `agent.json` (full per-case
results and traces), `report.json` and `report.md`. The `AI regression` workflow
(`.github/workflows/ai-regression.yml`) runs it on every change to Python sources, configs or dependencies, writes
the report to the job summary and uploads the artifacts for 90 days.

Language-model planning and generation are not part of the gate (they cost money and are not deterministic):
**NOT YET MEASURED**.

The current baseline was checked on Windows and on Linux (python 3.12, a freshly trained forecast model): both give
identical case outcomes and metrics.

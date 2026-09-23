# Definition of done (Task 20.4)

Each criterion from the execution handbook, the evidence for it, and how it was checked. "Partly"
means the criterion holds with a stated gap.

| Criterion | Status | Evidence |
|---|---|---|
| Primary workflow works locally | done | `scm_ml.demo` runs all 11 steps against the Compose stack ([demo.md](demo.md)); `tests/e2e` drives the same workflow against PostgreSQL + backend jar + engine |
| All five core capabilities work | done | forecasting, sourcing/procurement, inventory allocation, scenarios and the copilot are each exercised by the demo and benchmarked in [benchmarks.md](benchmarks.md) |
| AI copilot uses real tools and data | done | the demo's trace shows `get_forecast`, `assess_inventory_need`, `search_suppliers`, `optimize_procurement`, `run_scenario`, `search_policies` results from the engine; numbers in answers are checked by the `grounded_numbers` guardrail |
| RAG is evaluated | done | 56-question set, retrieval / citation / groundedness / refusal metrics ([rag-evaluation.md](rag-evaluation.md)); LLM-generated answers NOT YET MEASURED |
| Optimization is benchmarked | done | MILP vs cheapest and weighted-ranking policies, base and tight budget; allocation MILP vs nearest-warehouse rule |
| Forecast is benchmarked | done | four baselines vs LightGBM on synthetic and real data, with interval coverage |
| Scenarios work | done | 7 scenario types, baseline vs disrupted vs re-optimized ([scenarios.md](scenarios.md)) |
| Approval and security boundaries work | done | JWT + RBAC, self-approval refused (`403`, shown in the demo), required roles from policy, append-only decisions and audit log, internal token between backend and engine ([security.md](security.md)); covered by Java and e2e tests |
| Integration and e2e tests pass | done | Python, Java (Testcontainers) and frontend suites, `scripts/e2e.sh`, smoke tests against Compose and kind ([testing.md](testing.md)) |
| Docker works | done | `scripts/stack.sh up` + smoke tests ([containers.md](containers.md)) |
| Local Kubernetes works | done | `scripts/kind.sh up` + smoke tests, worker scaling measured ([kubernetes.md](kubernetes.md)) |
| CI works | partly | workflows are actionlint-clean and every job's commands pass locally; they have not run on GitHub because the repository has no remote ([ci.md](ci.md)) |
| Terraform / cloud architecture documented | done | `infrastructure/terraform` passes `validate`, `fmt` and `tflint`; mapping and local parity in [cloud.md](cloud.md); never applied |
| Feedback loop exists | done | forecast snapshots at approval, outcome capture API, evaluation, gated retraining with named-approver promotion ([feedback-loop.md](feedback-loop.md)) |
| Final benchmark is reproducible | done | `scripts/benchmark.sh` regenerates every artifact; `docs/benchmarks.md` is generated from them; the clean-checkout run below reproduced it |
| README is complete | done | problem, architecture, setup, demo, benchmark commands, results, limitations ([README](../README.md)) |
| Resume results are supported by artifacts | done | [resume-evidence.md](resume-evidence.md) names the artifact behind every claim |

## Clean-checkout run (Task 20.1)

2026-10-07, `git clone` of `main` into a fresh directory on Windows 11 (Git Bash, Docker Desktop), in
the order of the handbook:

| Step | Command | Result |
|---|---|---|
| install | `uv sync --frozen`, `npm ci` | ok |
| generate data | `uv run python -m scm_ml.synthetic --out data/synthetic --seed 42` | ok |
| train | `uv run python -m scm_ml.forecast --source synthetic` | every metric identical to the committed artifact; only the provenance (commit, time) changed |
| Python tests and checks | `bash scripts/check.sh` | 398 passed, 13 skipped (the opt-in e2e, smoke and real-data tests); ruff, ruff format, mypy --strict clean |
| benchmark report | `bash scripts/benchmark.sh --report` | regenerated from the artifacts with no change in any number |
| frontend | `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` | 80 tests passed, build ok. The first run found that `typecheck` failed on a clean checkout (route types are generated, not committed); `typecheck` now runs `next typegen` first |
| Java | `./mvnw verify` (initializes the database schema through Flyway in Testcontainers) | 130 tests passed |
| services | `bash scripts/stack.sh up`, smoke tests | run from the working tree at the same commit (one Compose stack per machine): 5 smoke tests passed, including the demo. Bringing it up found that the engine image could ship stale code from uv's cache, fixed in `ml.Dockerfile` |
| benchmark | `bash scripts/benchmark.sh` | 6 minutes; every metric in every regenerated artifact matched the committed one except solver and run times (the machine was also running the Compose stack). The feedback artifact was re-committed from this run because the current code no longer writes an interval coverage for the moving-average baseline, which has no intervals. The real-data forecast (`--real`) and the systems benchmarks were not part of this run |

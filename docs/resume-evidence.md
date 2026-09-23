# Resume evidence

Each line is "achieved X by doing Z", where X is a measured result and the artifact that holds it is
named. Synthetic results are labelled as such; nothing here is estimated. Results that were not
measured are listed at the end so they are not claimed by accident.

## Claims backed by artifacts

| Claim | Artifact |
|---|---|
| Cut demand-forecast error by 11.1% (test MAE 30.16 vs 33.91) against the best of four baselines on a 200-series synthetic panel, and by 2.1% on real retail data (Online Retail II), by building a LightGBM (Tweedie) multi-horizon model with leakage-safe temporal splits and baseline selection on validation only. | `ml/experiments/forecast/synthetic.json`, `ml/experiments/forecast/real.json` |
| Added calibrated 80% prediction intervals (conformalised quantile regression) that cover 78.3% of real-data test points, so plans can use a demand range instead of a point. | `ml/experiments/forecast/real.json` |
| Lowered total procurement cost by 13.2% vs a cheapest-supplier policy and 15.3% vs a weighted-ranking policy (302,532 vs 348,675 / 357,384) with zero constraint violations, by formulating supplier selection as a mixed-integer program (MOQ, capacity, budget, lead time, reliability-derated service level) solved with HiGHS in about 5 s. Synthetic 40-SKU, 3-warehouse network. | `ml/experiments/optimization/synthetic.json` |
| Kept spend within a 15%-tighter budget (253,585 of 253,586) at 100% fill while both heuristics broke it, by making budget a hard constraint of the same MILP. Synthetic. | `ml/experiments/optimization/synthetic.json` |
| Showed that re-optimizing after a supplier outage recovers fill rate from 94.1% to 100% and avoids 105,295 of disruption cost (and lifts fill from 86.7% to 98.7% for a 7-day lead-time shock), by building a scenario engine that re-solves plans under 7 typed disruptions and reports binding constraints and allocation changes. Synthetic. | `ml/experiments/scenario/synthetic.json` |
| Reached hit@1 0.94, MRR 0.97, 100% citation accuracy and 100% groundedness with zero restricted-document leaks on a 56-question evaluation set, by building hybrid retrieval (bge-small embeddings in pgvector + BM25) with document versioning, validity rules and permission filtering. | `ml/experiments/rag/synthetic-fastembed.json` |
| Kept 100% action safety across 40 copilot evaluation cases (no purchase order without human approval) and 100% permission compliance on the 5 permission cases, by putting typed tools, guardrails and a role-based approval gate between the agent and every write. The deterministic planner's hold-out workflow success is only 22% (2 of 9), reported as is. | `ml/experiments/agent/synthetic-rule-planner.json` |
| Served the main planning API at 11-59 ms p50 (catalog reads, supplier ranking, forecasts) and a full multi-tool copilot task at 0.98 s p50 on a local Docker Compose stack. | `ml/experiments/systems/api-latency.json` |
| Raised optimization-job throughput from 32.0 to 99.6 jobs per minute by scaling queue workers from 1 to 4 on a local Kubernetes (kind) cluster, using a PostgreSQL `SKIP LOCKED` job queue with leases and retries. | `ml/experiments/systems/worker-scaling.json` |
| Blocked a retrained forecast model that was 0.3% worse on held-out captured weeks (MAE 31.28 vs 31.18), by adding a promotion gate and a named-approver promotion step to the retraining workflow. Simulated outcomes. | `ml/experiments/feedback/retraining-synthetic.json` |

## Engineering scope (counts, not outcomes)

These are facts about the build, verified by the test runs in [testing.md](testing.md) and
[ci.md](ci.md), not performance results: three services (Spring Boot 4 / Java 21, Python FastAPI
engine, Next.js 16) with JWT auth, RBAC, rate limiting and an append-only audit log; Python, Java and
frontend test suites plus end-to-end, smoke and AI regression tests; Docker Compose, kind manifests,
GitHub Actions workflows (actionlint-clean, not yet run on GitHub) and validated AWS Terraform.

## Not measured, do not claim

* Any result with the Claude planner or Claude-generated RAG answers (no API key was used).
* Real business impact: no real outcomes were recorded; feedback-loop outcomes are simulated.
* Cloud cost, cloud latency, or anything about an AWS deployment (the Terraform was never applied).
* CI run times on GitHub.

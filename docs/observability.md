# Observability

## System (Task 11.1)

The backend publishes Micrometer metrics on the management port (`/actuator/prometheus`,
`/actuator/metrics`), and admins get a readable summary at `GET /api/ops/summary` and on the
**Operations** page.

| Signal | Metric |
| --- | --- |
| request latency, p50 / p95 / p99 | `scm_api_request_duration_seconds{quantile}` |
| throughput and error rate | `scm_api_requests_total{status="2xx-3xx"\|"4xx"\|"5xx"}` |
| queue depth, running, succeeded, failed jobs | `scm_jobs{status}` (from the database, correct across instances) |
| oldest waiting job | `scm_jobs_oldest_queued_seconds` |
| worker utilization | `scm_jobs_worker_utilization` (share of this instance's uptime spent running jobs) |
| job attempt duration and outcome | `scm_jobs_duration_seconds{type}`, `scm_jobs_attempts_total{type,outcome}` |

The summary's rates are over the instance's uptime, not a sliding window; Prometheus `rate()` over the
counters gives windowed rates.

## AI components (Task 11.2)

The engine keeps in-process telemetry (`GET /v1/telemetry`, relayed to admins as `GET /api/ops/ai`):

| Question | Signal |
| --- | --- |
| are forecasts being served, and how fast | forecast count, failures, p50/p95 |
| are tool calls correct | tool-call success rate; errors by `tool:code` (guardrail rejections of arguments, authorization, unknown ids, invalid results) |
| do agent tasks succeed | outcomes by status (`COMPLETED`, `AWAITING_APPROVAL`, `REFUSED`, `NEEDS_CLARIFICATION`, `FAILED`), latency, guardrail findings by kind (`APPROVAL_BYPASS`, `UNSUPPORTED_NUMBERS`, ...) |
| does retrieval find evidence | share of policy questions answered vs `INSUFFICIENT_EVIDENCE` / conflicting |
| model latency and cost | per model: calls, failures, p95, input/output tokens; cost only when `SCM_LLM_PRICE_INPUT_PER_MTOK` / `SCM_LLM_PRICE_OUTPUT_PER_MTOK` are set |

Live telemetry says what happened in traffic, not whether answers were right. Quality against ground
truth comes from the stored offline evaluations, summarised next to it (`quality`): forecast MAE
improvement and interval coverage, RAG retrieval and answer accuracy, groundedness and restricted-leak
count, agent workflow success (including the held-out result) and per-dimension pass rates, each with
the code revision that produced it. Metrics that need a language model (the Claude planner and
generator) show `NOT YET MEASURED` until a key is provided and the evaluation is run.

# Async jobs

Forecasts, optimization, scenarios and batch evaluations can outlast a request, so they run on a
durable queue in PostgreSQL (`job` table, migration V3) worked by the Spring backend. Jobs only relay
to the Python engine; planning logic is never duplicated in Java.

## API

| Call | Result |
| --- | --- |
| `POST /api/jobs` `{ "type", "payload" }` | `202` + `Location` for a new job, `200` with the original job for an idempotent replay |
| `GET /api/jobs/{id}` | status, attempts, durable `result`, or `errorCode` / `errorMessage` |
| `GET /api/jobs?limit=` | the caller's recent jobs, newest first |

Types and payloads: `FORECAST` (forecast request), `OPTIMIZATION` (plan spec),
`SCENARIO` (`{ plan, scenarioType, parameters }`), `BATCH_EVALUATION` (`{ tasks: [text, ...] }`, each
run through the agent). Malformed payloads are rejected at submission with `400`; ranges and planning
rules are the engine's, so a violation fails the job with the engine's own code.

## Guarantees

* **Idempotency.** `Idempotency-Key` plus the request body: the same pair returns the original job;
  the same key with a different request is `409 IDEMPOTENCY_CONFLICT`. Keys are scoped per user and
  matched on a hash of the canonical payload, so key order does not matter. Without a key every
  submission is a new job.
* **Exactly-once claiming.** Workers claim with `FOR UPDATE SKIP LOCKED` under a lease
  (`scm.jobs.lease`). Six concurrent workers over 24 jobs ran each job once (test).
* **Retry.** An engine failure with a 5xx status (unavailable, contract mismatch) requeues the job
  with exponential backoff (`retry-backoff` x 2^(attempt-1)) until `max-attempts`. Any other failure
  is permanent. `lastError` shows why a waiting job was retried.
* **Failure state.** A job that fails ends `FAILED` with `errorCode` and `errorMessage`. Unexpected
  exceptions are reported as `INTERNAL_ERROR` without internal detail.
* **Crash recovery.** A job whose worker died is taken over once its lease expires; if it has no
  attempts left it is failed as `LEASE_EXPIRED`. State changes by a worker are fenced by `locked_by`,
  so a worker that lost its lease cannot overwrite the new owner's result.
* **Durable result.** The result is stored in the row (`result jsonb`); a check constraint ties
  `SUCCEEDED` to a result and `FAILED` to an error code.
* **Privacy.** A job is visible to its submitter and to admins; anyone else gets `404`.

Batch evaluations record a rejected task in the result instead of failing or retrying the batch,
because every agent run is stored and a retry would repeat the runs that already happened.

## Configuration

`scm.jobs.worker-enabled` (`SCM_JOBS_WORKER_ENABLED`), `poll-interval`, `lease`, `max-attempts`,
`retry-backoff`. Several backend instances can run workers against one database.

## Identity

Until token authentication lands (Phase 11) the caller is identified by `X-User-Id` and
`X-User-Role` headers, read in one place (`ActorArgumentResolver`); a request without them is `401`.

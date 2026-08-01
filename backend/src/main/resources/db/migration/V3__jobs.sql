-- Durable queue of long-running work (forecasts, optimization, scenarios, batch evaluations).
-- Workers claim rows with FOR UPDATE SKIP LOCKED under a time-limited lease, so a crashed worker's
-- job is picked up again and a job is never run by two workers at once.

CREATE TABLE job (
    job_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        text NOT NULL CHECK (job_type IN (
        'FORECAST', 'OPTIMIZATION', 'SCENARIO', 'BATCH_EVALUATION')),
    idempotency_key text NOT NULL,
    request_hash    char(64) NOT NULL,
    payload         jsonb NOT NULL,
    submitted_by    text NOT NULL,
    submitted_role  text NOT NULL,
    status          text NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
        'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts    integer NOT NULL CHECK (max_attempts >= 1),
    run_after       timestamptz NOT NULL DEFAULT now(),
    locked_by       text,
    locked_until    timestamptz,
    result          jsonb,
    error_code      text,
    error_message   text,
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    UNIQUE (job_type, idempotency_key),
    CHECK ((status = 'SUCCEEDED') = (result IS NOT NULL)),
    CHECK ((status = 'FAILED') = (error_code IS NOT NULL))
);
-- worker claim path: next runnable job by due time
CREATE INDEX job_claimable ON job (run_after) WHERE status IN ('QUEUED', 'RUNNING');
CREATE INDEX job_submitter_created ON job (submitted_by, created_at DESC);

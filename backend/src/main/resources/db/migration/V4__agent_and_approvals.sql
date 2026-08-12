-- Durable record of copilot conversations and of the approval workflow. The Python engine decides
-- (answers, approval rules); these tables keep what it returned so history survives engine restarts.

CREATE TABLE agent_conversation (
    conversation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_conversation_user ON agent_conversation (user_id, created_at DESC);

CREATE TABLE agent_task (
    task_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   uuid NOT NULL REFERENCES agent_conversation (conversation_id),
    engine_task_id    text NOT NULL,
    user_id           text NOT NULL,
    user_role         text NOT NULL,
    request_text      text NOT NULL,
    status            text NOT NULL CHECK (status IN (
        'COMPLETED', 'AWAITING_APPROVAL', 'REFUSED', 'NEEDS_CLARIFICATION', 'FAILED')),
    answer            text NOT NULL,
    trace             jsonb NOT NULL DEFAULT '[]',
    citations         jsonb NOT NULL DEFAULT '[]',
    assumptions       jsonb NOT NULL DEFAULT '[]',
    violations        jsonb NOT NULL DEFAULT '[]',
    recommendation_id text REFERENCES recommendation (recommendation_id),
    approval_id       text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_task_conversation ON agent_task (conversation_id, created_at);

CREATE TABLE approval (
    approval_id       text PRIMARY KEY,
    recommendation_id text NOT NULL REFERENCES recommendation (recommendation_id),
    requested_by      text NOT NULL,
    requester_role    text NOT NULL,
    required_roles    text[] NOT NULL CHECK (cardinality(required_roles) > 0),
    approved_roles    text[] NOT NULL DEFAULT '{}',
    approvers         text[] NOT NULL DEFAULT '{}',
    order_value       numeric(16, 2) NOT NULL CHECK (order_value >= 0),
    status            text NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX approval_status_created ON approval (status, created_at DESC);
CREATE UNIQUE INDEX approval_recommendation ON approval (recommendation_id);

ALTER TABLE agent_task ADD CONSTRAINT agent_task_approval_fk
    FOREIGN KEY (approval_id) REFERENCES approval (approval_id) DEFERRABLE INITIALLY DEFERRED;

-- Each decision belongs to the approval it was given on, and records the role it was given in.
ALTER TABLE decision
    ADD COLUMN approval_id   text REFERENCES approval (approval_id),
    ADD COLUMN approver_role text;
CREATE INDEX decision_approval ON decision (approval_id);

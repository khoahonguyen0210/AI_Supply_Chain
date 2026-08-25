-- Who did what and how it ended. Append-only, like the approval decisions.

CREATE TABLE audit_log (
    audit_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor_user  text,
    actor_role  text,
    action      text NOT NULL,
    resource    text,
    outcome     text NOT NULL CHECK (outcome IN ('SUCCESS', 'DENIED', 'FAILED', 'LIMITED')),
    status      integer,
    client_ip   text,
    detail      text
);
CREATE INDEX audit_log_at ON audit_log (at DESC);
CREATE INDEX audit_log_actor ON audit_log (actor_user, at DESC);

CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

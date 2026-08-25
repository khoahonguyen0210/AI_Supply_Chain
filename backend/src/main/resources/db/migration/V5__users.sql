-- People who can sign in. The role decides what they may do (planner, procurement_manager, finance, admin).
-- Passwords are stored only as BCrypt hashes.

CREATE TABLE app_user (
    user_id       text PRIMARY KEY CHECK (user_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    display_name  text NOT NULL,
    role          text NOT NULL CHECK (role IN ('planner', 'procurement_manager', 'finance', 'admin')),
    password_hash text NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

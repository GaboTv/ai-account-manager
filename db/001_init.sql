-- Schema v1. No provider tokens are EVER stored here; auth state lives in
-- per-account Docker volumes only.

CREATE TABLE ai_accounts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider         TEXT NOT NULL CHECK (provider IN ('claude', 'codex')),
    name             TEXT NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9-]{1,30}$'),
    container_name   TEXT NOT NULL UNIQUE,
    image            TEXT NOT NULL,
    auth_volume      TEXT NOT NULL,
    workspace_volume TEXT NOT NULL,
    cpu_limit        REAL NOT NULL DEFAULT 1,
    memory_limit_mb  INTEGER NOT NULL DEFAULT 768,
    status           TEXT NOT NULL DEFAULT 'created',      -- created|running|stopped|error
    auth_status      TEXT NOT NULL DEFAULT 'unknown',      -- unknown|logged_in|logged_out|expired
    auth_info        JSONB NOT NULL DEFAULT '{}',          -- parsed metadata (email, plan) — never tokens
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ai_sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id     UUID NOT NULL REFERENCES ai_accounts(id) ON DELETE CASCADE,
    provider       TEXT NOT NULL,
    mode           TEXT NOT NULL,                          -- interactive|login|exec
    pty_process_id TEXT,                                   -- docker exec id
    status         TEXT NOT NULL DEFAULT 'active',         -- active|closed|crashed
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at       TIMESTAMPTZ
);

CREATE TABLE ai_command_runs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES ai_sessions(id) ON DELETE SET NULL,
    account_id UUID NOT NULL REFERENCES ai_accounts(id) ON DELETE CASCADE,
    command    TEXT NOT NULL,                              -- redacted before insert
    stdout     TEXT,                                       -- redacted before insert
    stderr     TEXT,
    exit_code  INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at   TIMESTAMPTZ
);

CREATE TABLE audit_events (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id   TEXT NOT NULL DEFAULT 'local-user',
    account_id UUID REFERENCES ai_accounts(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,   -- account.create|account.delete|container.create|container.start|
                                -- container.stop|container.restart|container.delete|auth.start|
                                -- auth.input|auth.success|auth.logout|session.start|session.close|
                                -- session.message|session.slash
    metadata   JSONB NOT NULL DEFAULT '{}',                -- redacted before insert
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_account ON audit_events(account_id, created_at DESC);
CREATE INDEX idx_runs_account ON ai_command_runs(account_id, started_at DESC);

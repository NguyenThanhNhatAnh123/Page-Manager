CREATE TABLE IF NOT EXISTS pm_users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','owner')),
 active BOOLEAN NOT NULL DEFAULT TRUE, must_change BOOLEAN NOT NULL DEFAULT TRUE,
 timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pm_sessions (
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES pm_users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pm_sessions_user ON pm_sessions(user_id);
CREATE TABLE IF NOT EXISTS pm_mcp_tokens (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES pm_users(id) ON DELETE CASCADE,
 digest TEXT UNIQUE NOT NULL, label TEXT NOT NULL, can_write BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS pm_login_limits (
 key TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 1, window_start TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pm_sync_requests (
 user_id TEXT PRIMARY KEY REFERENCES pm_users(id) ON DELETE CASCADE,
 requested_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 status TEXT NOT NULL DEFAULT 'pending', message TEXT, refreshed INTEGER NOT NULL DEFAULT 0,
 unavailable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pm_audit (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id TEXT REFERENCES pm_users(id), action TEXT NOT NULL,
 status INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pm_audit_user ON pm_audit(user_id,created_at DESC);
CREATE OR REPLACE FUNCTION pm_limit_users() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(80202020);
 IF (SELECT count(*) FROM public.pm_users)>=20 THEN RAISE EXCEPTION 'PageManager supports at most 20 users'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS pm_user_limit ON pm_users;
CREATE TRIGGER pm_user_limit BEFORE INSERT ON pm_users FOR EACH ROW EXECUTE FUNCTION pm_limit_users();

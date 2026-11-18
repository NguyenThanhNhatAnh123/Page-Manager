CREATE TABLE IF NOT EXISTS pm_users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','owner')),
 active BOOLEAN NOT NULL DEFAULT TRUE, must_change BOOLEAN NOT NULL DEFAULT TRUE,
 timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE pm_users ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS pm_user_archives (
 id TEXT PRIMARY KEY,username TEXT NOT NULL,display_name TEXT NOT NULL DEFAULT '',
 role TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,archived_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
ALTER TABLE pm_sync_requests ADD COLUMN IF NOT EXISTS next_auto_at TIMESTAMPTZ;
ALTER TABLE pm_sync_requests ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT 'login';
CREATE OR REPLACE FUNCTION pm_request_sync(owner_id TEXT,request_reason TEXT DEFAULT 'manual',hours INTEGER DEFAULT 12)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE changed INTEGER;
BEGIN
 IF hours NOT IN (12,24) THEN hours:=12; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.pm_users WHERE id=owner_id AND active) THEN RETURN FALSE; END IF;
 INSERT INTO public.pm_sync_requests(user_id,reason,next_auto_at)
 VALUES(owner_id,request_reason,now()+hours*interval '1 hour')
 ON CONFLICT(user_id) DO UPDATE SET requested_at=now(),reason=EXCLUDED.reason,status='pending',message=NULL,
 next_auto_at=now()+hours*interval '1 hour'
 WHERE pm_sync_requests.requested_at<=COALESCE(pm_sync_requests.processed_at,'epoch'::timestamptz)
 AND (request_reason<>'auto' OR COALESCE(pm_sync_requests.next_auto_at,
      pm_sync_requests.finished_at+hours*interval '1 hour',pm_sync_requests.requested_at+hours*interval '1 hour')<=now())
 AND (request_reason='auto' OR pm_sync_requests.finished_at IS NULL OR pm_sync_requests.finished_at<now()-interval '60 seconds');
 GET DIAGNOSTICS changed=ROW_COUNT;
 RETURN changed>0;
END $$;
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

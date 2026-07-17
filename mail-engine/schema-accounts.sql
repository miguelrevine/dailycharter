-- ============================================================
-- Accounts feature migration — apply once to the existing D1 database.
-- Source of truth: accounts-design.md §1. Also folded into schema.sql
-- (guarded) so a fresh install gets everything in one shot.
-- ============================================================

ALTER TABLE subscribers ADD COLUMN password_hash TEXT;
ALTER TABLE subscribers ADD COLUMN password_salt TEXT;

CREATE TABLE IF NOT EXISTS sessions (
  token         TEXT PRIMARY KEY,           -- opaque random, not the quiz token
  subscriber_id TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at    TEXT NOT NULL               -- created_at + 30 days
);
CREATE INDEX IF NOT EXISTS idx_sessions_sub ON sessions (subscriber_id);

-- Precomputed once per pair of plan lengths after generation (§4).
CREATE TABLE IF NOT EXISTS plan_equivalence (
  from_plan_id TEXT NOT NULL,   -- 'L1-90'
  from_day     INTEGER NOT NULL,
  to_plan_id   TEXT NOT NULL,   -- 'L1-270'
  to_day       INTEGER NOT NULL,
  PRIMARY KEY (from_plan_id, from_day, to_plan_id)
);

-- Not in accounts-design.md's schema list, but required by §3's rate-limit
-- requirement on /api/login — D1 is the only storage available (no KV
-- binding in this project), so a small append-only table stands in for it.
CREATE TABLE IF NOT EXISTS login_attempts (
  attempt_key TEXT NOT NULL,   -- lower(email) || '|' || ip
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (attempt_key, created_at);

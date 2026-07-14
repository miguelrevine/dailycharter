-- ============================================================
-- DailyCharter mail engine — full schema (SQLite / Cloudflare D1)
-- Apply once:  wrangler d1 execute dailycharter --file=schema.sql
-- Pills/plans rows come from seed_plan.py (identical definitions).
-- ============================================================

CREATE TABLE IF NOT EXISTS plans (
  plan_id       TEXT NOT NULL,             -- 'L1-90' … 'L1-365'
  plan_version  TEXT NOT NULL,             -- 'v20260715'
  name          TEXT,
  days          INTEGER NOT NULL,
  generated_at  TEXT,
  PRIMARY KEY (plan_id, plan_version)
);

CREATE TABLE IF NOT EXISTS pills (
  id            TEXT PRIMARY KEY,          -- 'L1-180-042'
  plan_id       TEXT NOT NULL,
  plan_version  TEXT NOT NULL,
  day           INTEGER NOT NULL,
  topic         TEXT NOT NULL,
  title         TEXT NOT NULL,
  concept       TEXT NOT NULL,
  exam_tips     TEXT,                      -- JSON array
  formula       TEXT,
  question      TEXT NOT NULL              -- JSON {stem, choices[], correct_key}
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_pill
  ON pills (plan_id, plan_version, day);

CREATE TABLE IF NOT EXISTS subscribers (
  id             TEXT PRIMARY KEY,          -- uuid
  email          TEXT UNIQUE NOT NULL,
  first_name     TEXT,
  plan_id        TEXT NOT NULL,
  plan_version   TEXT NOT NULL,             -- pinned at signup
  next_day       INTEGER NOT NULL DEFAULT 1,-- ← the pointer
  status         TEXT NOT NULL DEFAULT 'active',
                 -- active | paused | completed | cancelled
  send_hour_utc  INTEGER NOT NULL DEFAULT 6,
  exam_date      TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sub_send
  ON subscribers (status, send_hour_utc);

-- Idempotent send log: a pill can never go twice to the same person.
CREATE TABLE IF NOT EXISTS sends (
  subscriber_id TEXT NOT NULL,
  plan_id       TEXT NOT NULL,
  day           INTEGER NOT NULL,
  sent_at       TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (subscriber_id, plan_id, day)
);

-- Every recorded quiz answer. Append-only.
CREATE TABLE IF NOT EXISTS attempts (
  id            TEXT PRIMARY KEY,           -- uuid
  subscriber_id TEXT NOT NULL,
  pill_id       TEXT NOT NULL,
  choice        TEXT NOT NULL,              -- 'A' | 'B' | 'C'
  is_correct    INTEGER NOT NULL,           -- 0/1
  source        TEXT NOT NULL,              -- email_tap | web | recap
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
-- One scored attempt per person/pill/day (retries return the stored result):
CREATE UNIQUE INDEX IF NOT EXISTS uniq_attempt_day
  ON attempts (subscriber_id, pill_id, date(created_at));
CREATE INDEX IF NOT EXISTS idx_attempts_sub
  ON attempts (subscriber_id, created_at);

-- Spaced repetition (Leitner): one box per person/pill.
CREATE TABLE IF NOT EXISTS review_queue (
  subscriber_id TEXT NOT NULL,
  pill_id       TEXT NOT NULL,
  box           INTEGER NOT NULL DEFAULT 1, -- 1=weekly · 2=+14d · 3=pre-exam
  due_date      TEXT NOT NULL,
  PRIMARY KEY (subscriber_id, pill_id)
);
CREATE INDEX IF NOT EXISTS idx_review_due
  ON review_queue (subscriber_id, due_date);

# Plan storage & mail-engine day management

Companion to `pill_factory.py` and `backend-quiz-spec.md`.

---

## 1. The core idea: content is static, state is a pointer

Two worlds that never mix:

```
CONTENT (generated once, locally)          STATE (one row per subscriber)
─────────────────────────────────          ──────────────────────────────
plans/plan-90.json                          subscriber:
plans/plan-180.json                           plan_id      = "L1-270"
plans/plan-270.json   ◄────── JOIN ──────►    plan_version = "v20260701"
plans/plan-365.json                           next_day     = 21
  each: pills[1..N]                           status       = "active"
```

The mail engine never computes "what day is this user on" from dates.
Each subscriber carries a **`next_day` pointer**. The daily send is one query:

```sql
SELECT s.id, s.email, s.first_name, p.*
FROM   subscribers s
JOIN   pills p ON  p.plan_id      = s.plan_id
               AND p.plan_version = s.plan_version
               AND p.day          = s.next_day
WHERE  s.status = 'active'
  AND  s.send_hour_utc = strftime('%H', 'now');
```

Your two example users fall out of the same query with zero special cases:

| User | plan_id | next_day | Query returns |
|---|---|---|---|
| Veteran, finished day 20 of 270 | L1-270 | **21** | pill 21 of plan-270 |
| Brand new, on the 365 plan | L1-365 | **1** | pill 1 of plan-365 |

After each successful send: `next_day += 1`. When `next_day > plan.days`,
set `status = 'completed'` and trigger the congratulations email.

## 2. Why a pointer beats "days since signup"

Computing `day = today - start_date` looks simpler but breaks constantly:

- **Pauses / vacation mode**: user pauses 2 weeks → date math skips 14 pills
  forever. With a pointer, `status='paused'` just freezes it; resume continues
  at pill 21 as if nothing happened.
- **Failed sends**: ESP outage on Tuesday → date math silently swallows a
  pill. Pointer only advances on confirmed send, so Wednesday delivers
  Tuesday's pill. Nobody ever skips content.
- **Plan switching**: user moves from 365 → 180 (exam moved up). Keep relative
  progress: `next_day = max(1, round(old_next_day / 365 * 180))`.
- **Timezone changes, DST, signup at 23:59** — all irrelevant to a counter.

## 3. Where the plans live

The plan JSONs are **build artifacts**, like compiled code:

1. `pill_factory.py` writes `plans/plan-<N>.json` on your machine.
2. Commit them to the Git repo → versioned, diffable, reviewable
   (`git diff` shows exactly which pills changed between versions).
3. A tiny `seed` script upserts them into the engine's `pills` table
   (or, in the leanest setup, a Cloudflare Worker reads the JSON from
   the repo's raw URL / KV store directly — no pills table at all).

```sql
-- pills table gains two columns vs backend-quiz-spec.md:
ALTER TABLE pills ADD COLUMN plan_id      TEXT NOT NULL;  -- 'L1-270'
ALTER TABLE pills ADD COLUMN plan_version TEXT NOT NULL;  -- 'v20260701'
ALTER TABLE pills ADD COLUMN day          INTEGER NOT NULL;
CREATE UNIQUE INDEX uniq_pill ON pills (plan_id, plan_version, day);
```

**Version pinning matters**: subscribers store `plan_version` at signup.
If you regenerate plan-270 next month (better model, fixed typo), existing
subscribers keep their version — their day numbers still point at the same
content. New signups get the new version. Migrating old users is an explicit,
opt-in script, never an accident.

## 4. Subscriber state (full)

```sql
CREATE TABLE subscribers (
  id             TEXT PRIMARY KEY,
  email          TEXT UNIQUE NOT NULL,
  first_name     TEXT,
  plan_id        TEXT NOT NULL,               -- 'L1-90' … 'L1-365'
  plan_version   TEXT NOT NULL,
  next_day       INTEGER NOT NULL DEFAULT 1,  -- ← the pointer
  status         TEXT NOT NULL DEFAULT 'active',
                 -- active | paused | completed | cancelled
  send_hour_utc  INTEGER NOT NULL DEFAULT 6,  -- their 7:00 local, precomputed
  exam_date      DATE,
  created_at     TIMESTAMP NOT NULL DEFAULT now()
);

-- Idempotent send log: a pill can never be sent twice to the same person.
CREATE TABLE sends (
  subscriber_id TEXT NOT NULL,
  plan_id       TEXT NOT NULL,
  day           INTEGER NOT NULL,
  sent_at       TIMESTAMP NOT NULL DEFAULT now(),
  PRIMARY KEY (subscriber_id, plan_id, day)
);
```

## 5. The daily cron, end to end

Runs hourly (so every timezone gets its 7:00):

```
for each subscriber matched by the JOIN in §1:
    1. INSERT INTO sends (…)            -- PK violation? already sent → skip
    2. render pill-email.html with the pill's fields + merge tags
       (streak/accuracy come from attempts, progress = next_day/days)
    3. POST to ESP transactional API
    4. on 2xx:  UPDATE subscribers SET next_day = next_day + 1
       on error: do nothing → tomorrow's run retries the same day
    5. if next_day > plan.days → status = 'completed'
```

Step order is the safety: the send-log insert *before* the ESP call plus
pointer-advance *after* it means crashes can cause at most one duplicate
email, never a skipped pill — the right failure mode for a study product.

## 6. How the pieces connect

```
[LOCAL MACHINE]                     [GIT REPO]              [CLOUD - tiny]
pill_factory.py serve               plans/*.json            hourly cron ── JOIN ──► ESP
  └─ Ollama (llama3.1…)     git push ─────────►  seed ───►  pills table            └─► inboxes
                                                            subscribers.next_day◄── quiz API
                                                                      ▲  (attempts also
                                                                      │   feed recaps)
                                                            signup form (plan picker)
```

The expensive intelligence (generation) runs once, locally, for free.
The cloud part is a JOIN, a template render and an HTTP POST — it fits in
any free tier and scales to thousands of subscribers without changes.

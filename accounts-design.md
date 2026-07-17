# Accounts, plan-switching & admin — design

Extends plan-engine-design.md and backend-quiz-spec.md. Covers: email+password
login, the account portal, plan-equivalence on switch (always asks), and an
admin view. All additive — no change to the send cron's core JOIN.

---

## 1. Schema additions

```sql
ALTER TABLE subscribers ADD COLUMN password_hash TEXT;   -- PBKDF2, see §2
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
```

Two separate token types on purpose: the **quiz token** (existing, from
`makeToken()`) is long-lived and embedded in email links — it must keep
working forever even if the person never sets a password. The **session
token** is short-lived, browser-only, created at login, revocable by
deleting the row. Don't merge them.

## 2. Password hashing (Workers-compatible)

Bcrypt isn't available in the Workers runtime. Use **PBKDF2 via Web Crypto**
(`crypto.subtle`, already used for the HMAC tokens):

```js
async function hashPassword(password, salt) {
  const key = await crypto.subtle.importKey("raw", enc.encode(password),
    "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: enc.encode(salt), iterations: 100000, hash: "SHA-256" },
    key, 256);
  return b64url(bits);
}
```
Salt: `crypto.randomUUID()` per subscriber, stored alongside the hash.
100k iterations is the OWASP-recommended floor for PBKDF2-SHA256 in 2026.

## 3. New endpoints

```
POST /api/signup          {email, password, first_name, plan_days}
                           → sets password_hash/salt too (extends existing
                             /api/subscribe; keep /api/subscribe as an alias
                             for the no-password checkout-triggered flow)
POST /api/login            {email, password}
                           → 200 {session_token} · 401 on mismatch
                           → generic "Invalid email or password" always;
                             never reveal which field was wrong
POST /api/logout           {session_token} → invalidate the row

GET  /api/account          Authorization: Bearer <session_token>
                           → {email, first_name, plan_id, plan_days,
                              next_day, progress_pct, status, stats}

POST /api/account/change-plan
                           {session_token, new_plan_days, mode}
                           mode: "restart" | "resume"
                           "restart" → new_day = 1
                           "resume"  → look up plan_equivalence for
                             (current plan_id, next_day) → (new plan_id);
                             fallback to percentage mapping if no exact row
                           Always requires the FRONTEND to have asked the
                           user restart-vs-resume first — the API takes
                           `mode` explicitly, never assumes.

POST /api/account/cancel   {session_token} → status = 'cancelled'
                           (same effect as the email unsubscribe link)

POST /api/account/password  {session_token, current_password, new_password}
```

Rate-limit `/api/login` per email+IP (e.g. 10/hour) — it's the one endpoint
that invites brute-forcing.

## 4. Plan equivalence: how the mapping is actually computed

Naive `round(day / daysA * daysB)` is close but not exact, because
`distribute_days()` (pill_factory.py) is a deficit scheduler — every plan
rounds topic counts slightly differently as it interleaves. Exact answer:
**match cumulative topic coverage**, not raw day number.

```
precompute_equivalence.py  (new script, pill-factory/)
────────────────────────────────────────────────────────
for each pair of generated plans (A, B):
  for day D in 1..daysA:
    countsA = { topic: pills of that topic in A[1..D] }
    # find the smallest day D' in B whose cumulative topic
    # counts are >= countsA, scaled by daysB/daysA (proportional match)
    D' = min day in B such that for every topic t:
           countsB_upto(D')[t] >= countsA[t] * (daysB/daysA)
    write row (A.plan_id, D, B.plan_id, D')
```

This runs once, locally, right after the four plans validate clean —
output is a SQL file seeded into `plan_equivalence` alongside the pills
(same `seed_plan.py` family of tooling). It's a **lookup, not a live
calculation** — cheap for the Worker, and reviewable/diffable like
everything else in this pipeline.

Fallback if a cell is somehow missing (shouldn't happen once seeded):
percentage mapping (`round(day/daysA*daysB)`), so `/change-plan` never
hard-fails.

## 5. Frontend additions

- `site/login.html` — email+password form → stores `session_token` in
  `localStorage` (acceptable here: no payment data, session-scoped, and
  revocable server-side via the sessions table).
- `site/account.html` — the portal: current plan, progress bar, streak/
  accuracy (reuses `statsFor()` logic), a "Change plan" control that shows
  **both** options — *"Restart from pill 1"* and *"Resume at pill X"*
  (the API returns the resume target so the UI can show it before
  confirming) — and "Cancel subscription".
- Checkout success (`success.html`) can prompt to set a password
  post-purchase (optional, not required to receive pills).

## 6. Admin view (not a hidden URL + password)

A hidden URL is not access control — anything that can appear in a
Referer header, browser history, or analytics log is effectively public.
Minimum viable real protection:

```
GET /api/admin/subscribers      Authorization: Bearer <ADMIN_TOKEN>
                                 → paginated list: email, plan, next_day,
                                   status, created_at (no password data,
                                   ever, in any response)
```

`ADMIN_TOKEN` is a single long random secret (`wrangler secret put
ADMIN_TOKEN`), not tied to any subscriber row. `site/admin.html` is a
plain page that asks for the token once, stores it in memory (not
localStorage — you re-enter it each session), and calls the endpoint.
This is intentionally simple for a one-person operation; if you ever add
staff, swap it for per-person admin accounts with roles instead of a
shared token.

## 7. What does NOT change

- The hourly send cron's JOIN is untouched — `next_day`/`plan_id`/
  `plan_version` remain the only fields it reads.
- The quiz token and its endpoints are untouched — quiz-taking never
  requires being logged in, by design (a click from the email must keep
  working for someone who never sets a password).

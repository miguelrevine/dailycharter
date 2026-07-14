# DailyCharter — Quiz Backend Specification

Version 1.0 · Companion to `quiz.html` and `pill-email.html`

---

## 1. The flow

Email links never record anything. They carry identity and context; the interactive quiz page does the work.

```
┌─────────────┐   GET /quiz?pill=042&u=<token>     ┌──────────────┐
│ Daily email │ ─────────────────────────────────► │  quiz.html   │
│  (A/B/C or  │        (safe: read-only)           │ interactive  │
│  one button)│                                    │  question    │
└─────────────┘                                    └──────┬───────┘
                                                          │ user taps an answer
                                                          ▼
                                              POST /api/attempts
                                              { token, pill, question, choice }
                                                          │
                                    ┌─────────────────────┼──────────────────────┐
                                    ▼                     ▼                      ▼
                              validate token        record attempt        update Leitner box
                                    │                     │                      │
                                    └─────────────────────┴──────────────────────┘
                                                          │
                                                          ▼
                                        JSON: verdict + explanation + stats
                                        (page animates result, offers bonus
                                         review question from the queue)
```

Why the email's A/B/C buttons still make sense: they pass `&a=B` in the URL so
the page **pre-selects** that choice and submits it on load *after* a human
gesture check (or immediately, accepting minor scanner noise on that field —
see §6). One tap in the mail app, full interactivity on the web. Best of both.

---

## 2. Architecture options

| Piece | Lean (launch this week) | Growing |
|---|---|---|
| API | Cloudflare Workers / Vercel functions | Node (Fastify) or Python (FastAPI) |
| DB | Cloudflare D1 or Supabase (Postgres) | Postgres |
| Static site | GitHub Pages (already deployed) | Same + CDN |
| Emails | ESP API (Buttondown / MailerLite / Postmark) | Same |
| Cron (weekly recap) | Cloudflare Cron Triggers / GitHub Actions schedule | Same |

The schema below is plain SQL and ports to any of these.

---

## 3. Data model

```sql
-- People. The ESP remains the source of truth for email delivery;
-- we mirror the minimum needed for the quiz system.
CREATE TABLE subscribers (
  id            TEXT PRIMARY KEY,          -- uuid
  email         TEXT UNIQUE NOT NULL,
  first_name    TEXT,
  exam_date     DATE,                      -- paces the sequence
  plan          TEXT NOT NULL DEFAULT 'free',   -- free | full
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

-- One row per pill in the 180-day sequence.
CREATE TABLE pills (
  id            INTEGER PRIMARY KEY,       -- 1..180
  topic         TEXT NOT NULL,             -- 'Quantitative Methods', ...
  title         TEXT NOT NULL,
  body_html     TEXT NOT NULL,             -- the lesson content
  formula       TEXT
);

-- Questions belong to pills. One today-question per pill,
-- but the table allows extra questions for recaps/bonus.
CREATE TABLE questions (
  id            TEXT PRIMARY KEY,          -- 'q042-1'
  pill_id       INTEGER NOT NULL REFERENCES pills(id),
  stem          TEXT NOT NULL,
  choices       TEXT NOT NULL,             -- JSON: [{"key":"A","text":"$27.00","why":"multiply trap"},...]
  correct_key   TEXT NOT NULL,             -- 'B'
  is_daily      BOOLEAN NOT NULL DEFAULT true
);

-- Every recorded answer. Append-only.
CREATE TABLE attempts (
  id            TEXT PRIMARY KEY,          -- uuid
  subscriber_id TEXT NOT NULL REFERENCES subscribers(id),
  question_id   TEXT NOT NULL REFERENCES questions(id),
  choice        TEXT NOT NULL,             -- 'A' | 'B' | 'C'
  is_correct    BOOLEAN NOT NULL,
  source        TEXT NOT NULL,             -- 'email_tap' | 'web' | 'recap'
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);
-- One scored attempt per person/question/day (retries shown but not re-scored):
CREATE UNIQUE INDEX uniq_attempt_day
  ON attempts (subscriber_id, question_id, date(created_at));

-- Spaced repetition state: a Leitner box per person/question.
CREATE TABLE review_queue (
  subscriber_id TEXT NOT NULL REFERENCES subscribers(id),
  question_id   TEXT NOT NULL REFERENCES questions(id),
  box           INTEGER NOT NULL DEFAULT 1,   -- 1=weekly, 2=biweekly, 3=pre-exam only
  due_date      DATE NOT NULL,
  PRIMARY KEY (subscriber_id, question_id)
);
```

Derived, not stored: **streak** = consecutive days with ≥1 attempt;
**accuracy** = correct/total over last 30 days. Compute per request or cache.

---

## 4. Endpoints

### `GET /quiz` (static page — already built as `quiz.html`)
Query params: `pill` (int), `u` (signed token), `a` (optional pre-selected key).
Serves the interactive page. **Writes nothing.**

### `POST /api/attempts`
```json
{ "token": "<u>", "question_id": "q042-1", "choice": "B", "source": "web" }
```
Server: verify token (§5) → look up correct answer → insert attempt
(idempotent via the unique index; on conflict return the original result) →
update Leitner box:

```
wrong  → box = 1, due = next Sunday
right  → box = min(box+1, 3)
         box 2 due = +14 days · box 3 due = exam_date - 21 days
```

Response:
```json
{
  "correct": true,
  "correct_key": "B",
  "explanations": { "A": "The multiply trap ...", "B": "PV = PMT / r ...", "C": "Rate misread ..." },
  "stats": { "streak_days": 12, "accuracy_pct": 84, "progress_pct": 23 }
}
```

### `GET /api/review-next?token=...`
Returns the next due question from `review_queue` (for the "bonus question"
button on the result screen) or `204 No Content` if the queue is clear.
Read-only — answering it goes through `POST /api/attempts` with `source:"recap"`.

### Cron: weekly recap (Sundays)
For each subscriber: select up to 7 due questions ordered by `box ASC, due_date ASC`,
render the recap email through the ESP API. Recap answer links point to
`/quiz?recap=<batch_id>&u=<token>` — same page, multi-question mode.

---

## 5. Auth without passwords: signed tokens

Subscribers never log in. Every email link carries `u`:

```
u = base64url( subscriber_id ) + "." + base64url( HMAC_SHA256(SECRET, subscriber_id) )
```

Server recomputes the HMAC to validate. Properties:
- No PII in the URL (opaque id, not the email address).
- Tokens don't expire (a study link should keep working), but rotate `SECRET`
  if there's ever a leak — all old links die at once.
- The token authorizes *writing attempts for that subscriber only*.
  Account changes (email, cancel) still require an ESP-managed link.

---

## 6. Hard-won rules (read before coding)

1. **GET never writes.** Mail scanners (Outlook SafeLinks, corporate AV)
   prefetch every link in every email. Any state change on GET = ghost answers.
2. **The `&a=B` pre-selection is a hint, not an attempt.** Record it only after
   a human signal on the page (click "confirm", or any pointer/key event before
   auto-submit). `quiz.html` implements this.
3. **Idempotency**: the unique index makes double-taps and refreshes harmless.
   Return the stored result instead of erroring.
4. **Rate-limit** `POST /api/attempts` per token (e.g. 30/min) — enough for
   humans, boring for bots.
5. **CORS**: the API allows only your site origin. The token is auth; CORS is
   just noise reduction.
6. **Don't trust the client for correctness**: the page never receives
   `correct_key` before submitting. Verdict comes back from the server —
   otherwise answers leak in view-source.
7. Log `source` faithfully (`email_tap` vs `web` vs `recap`) — it tells you
   which UX actually drives engagement.

---

## 7. What quiz.html expects

The page ships with demo data inline and a commented `fetch()` block.
To go live: set `API_BASE`, remove the `DEMO` object, uncomment the fetch.
Contract = exactly §4's `POST /api/attempts` response.

# DailyCharter — project brief for Claude Code

You are working on **DailyCharter**: a business that sends daily CFA Level I
study emails ("pills"). One pill a day = one concept + one formula + one
exam-style question. Everything user-facing is in **English**.

## Repository layout

```
site/           Static website (GitHub Pages). Landing, checkout (Stripe
                pending), interactive quiz page, email template, legal pages.
                deploy-github.sh deploys it.
pill-factory/   LOCAL content pipeline: PDFs → local LLM (Ollama) → plan JSONs.
                pill_factory.py (scan/generate/serve), validate_plan.py (QA),
                seed_plan.py (JSON → SQL). Guides: GENERATION-GUIDE.md.
                Curriculum PDFs go in pill-factory/pdfs/ (git-ignored).
mail-engine/    Cloudflare Worker + D1. Hourly send cron + quiz API.
                schema.sql, src/index.js, wrangler.toml, README.md.
```

## Architecture in one paragraph

Plans (90/180/270/365 days) are static JSON generated once, locally, with
Ollama — committed to Git, seeded into D1. Each subscriber carries a
`next_day` pointer; the hourly cron does one JOIN
(subscribers.next_day × pills.day), renders the email, sends via Resend,
and advances the pointer only on confirmed delivery. Quiz answers arrive at
`POST /api/attempts` from site/quiz.html and feed a 3-box Leitner queue that
powers Sunday recap emails. Full designs: `pill-factory/plan-engine-design.md`
and `site/../mail-engine/README.md`, `backend-quiz-spec.md` in site/.

## Invariants — do not break these

1. **GET never writes.** Mail scanners prefetch every link. Quiz answers and
   unsubscribes are recorded only via POST after a human gesture.
2. **The pointer advances only after a confirmed ESP send.** Failure mode is
   "retry same pill tomorrow", never "skip a pill".
3. **correct_key never leaves the server** before an attempt is recorded.
4. **Copyright**: the source PDFs (Schweser) are copyrighted reference
   material. Generated pills must be ORIGINAL text. `validate_plan.py
   --pdf-dir` runs a verbatim 10-word overlap check — it must pass with zero
   flags before any plan is committed or seeded. Never weaken this gate.
5. **Plan versions are immutable.** Subscribers pin `plan_version` at signup;
   regenerated plans get a new version, never overwrite in place.
6. Legal pages (privacy/terms) contain [BRACKETED] placeholders — they need
   the owner's real data and a lawyer's review; don't invent legal specifics.

## Common commands

```bash
# content
python pill-factory/pill_factory.py scan --pdf-dir pill-factory/pdfs
python pill-factory/pill_factory.py generate --pdf-dir pill-factory/pdfs --plan 90 --model llama3.1
python pill-factory/validate_plan.py pill-factory/plans/plan-90.json --pdf-dir pill-factory/pdfs --review 10
python pill-factory/seed_plan.py pill-factory/plans/plan-*.json

# site
bash site/deploy-github.sh

# engine
cd mail-engine && wrangler d1 execute dailycharter --file=schema.sql && wrangler deploy
wrangler dev --test-scheduled   # then: curl "http://localhost:8787/__scheduled?cron=0+*+*+*+*"
```

## Configuration touchpoints (where URLs/keys get wired)

- `site/index.html` → `var WORKER_URL` (signup form)
- `site/quiz.html`  → `var API_BASE`  (quiz API) — also remove the DEMO object
- `mail-engine/wrangler.toml` → SITE_URL, WORKER_URL, FROM_EMAIL, D1 database_id
- Secrets via `wrangler secret put TOKEN_SECRET` and `ESP_API_KEY`
- `site/checkout.html` → Stripe integration pending (notes inside the file)

## Style

- Site CSS lives in `site/styles.css` (design tokens at top). Email template
  `site/pill-email.html` is table-based inline-styled email HTML — keep it that
  way, webfonts/JS don't work in email clients.
- User-facing copy: English, concise, warm-but-precise. The brand voice sells
  consistency ("five minutes a day"), never exam-pass guarantees.

# Generation Guide — producing the 4 plans locally

The complete runbook: from a folder of PDFs to four validated, seeded plans.

---

## 0. One-time setup

```bash
pip install pypdf requests
# Install Ollama → https://ollama.com, then pull a model:
ollama pull llama3.1          # solid default, 8B, ~5 GB
ollama serve                  # if not already running as a service
```

Put the curriculum PDFs in one folder, e.g. `./pdfs/` (the 5 Schweser books).
Verify the topic mapping before anything else:

```bash
python pill_factory.py scan --pdf-dir ./pdfs
```

Every PDF should map to sensible topics. If a filename isn't recognized,
add a keyword to `PDF_TOPIC_KEYWORDS` in `pill_factory.py`.

## 1. Choosing the model (quality vs your hardware)

| Model | RAM needed | sec/pill* | 365-plan ETA | Notes |
|---|---|---|---|---|
| `llama3.1` (8B) | 8 GB | ~20–40s | 2–4 h | Good default balance |
| `qwen2.5:14b` | 16 GB | ~40–80s | 4–8 h | Noticeably better finance reasoning |
| `mistral-nemo` | 12 GB | ~30–60s | 3–6 h | Strong instruction following |
| `qwen2.5:32b` / `llama3.3:70b` | 24–48 GB | minutes | overnight+ | Best quality if the box allows |

\*Rough CPU/entry-GPU figures; a decent GPU divides these by 3–10.

Rule of thumb: **use the biggest model that fits your RAM.** Pill quality is
your entire product; generation time is a one-off cost you pay while sleeping.

## 2. Pilot before committing hours: the 90 first

Don't start with the 365. Generate the smallest plan, judge quality, tune,
then batch the rest.

```bash
python pill_factory.py generate --pdf-dir ./pdfs --plan 90 --model llama3.1
python validate_plan.py plans/plan-90.json --pdf-dir ./pdfs --review 10
```

Then **read 10 random pills yourself** (the validator catches structure, not
pedagogy). Checklist per pill:
- Is the concept explained, not just named?
- Is the question answerable from the concept text alone?
- Are the two distractors *plausible mistakes*, not obvious junk?
- Formula correct? (Spot-check against the source.)

Not happy? Tune and regenerate — the usual dials, in order of impact:
1. Bigger model.
2. `temperature` in `generate_pill()` (0.7 default; 0.5 = more sober).
3. The system prompt (e.g. add "Target readers are working professionals;
   use one concrete numeric example in every concept").

## 3. Batch the four plans

Sequential, one command (each plan checkpoints after every pill, so
Ctrl+C / power cuts only lose the current pill — rerunning resumes):

```bash
for N in 90 180 270 365; do
  python pill_factory.py generate --pdf-dir ./pdfs --plan $N --model qwen2.5:14b
done
```

Or use the app if you prefer buttons and a progress bar:

```bash
python pill_factory.py serve --pdf-dir ./pdfs     # http://localhost:8765
```

Practical notes:
- Laptop: disable sleep-on-lid-close, plug it in, run overnight.
- The four plans are independent — two machines can split the work; the
  output JSONs merge trivially (they're separate files).
- Each plan is regenerable forever: the pipeline is deterministic in
  structure, only the LLM text varies.

## 4. Quality gate — non-negotiable before publishing

```bash
for N in 90 180 270 365; do
  python validate_plan.py plans/plan-$N.json --pdf-dir ./pdfs
done
```

`--pdf-dir` activates the **originality check**: any pill sharing a verbatim
10-word sequence with the source PDFs is flagged as an error. Those pills
must be rewritten (delete them from the JSON and rerun `generate` — resume
only fills missing days ─ or hand-edit). The source is copyrighted material:
this gate is what keeps your product legally clean. Structure errors
(missing choices, broken day sequence) also block with exit code 1.

## 5. Version & commit

```bash
git add plans/*.json
git commit -m "plans v20260715 — qwen2.5:14b, originality-clean"
```

Plans in Git = diffable, reviewable, and every subscriber's `plan_version`
pins to an immutable snapshot (see plan-engine-design.md §3).

## 6. Seed the engine

```bash
# Option A — one SQL file per plan (works on D1/Postgres/SQLite):
python seed_plan.py plans/plan-*.json
wrangler d1 execute dailycharter --file=seed-L1-180.sql   # etc.

# Option B — straight into a local SQLite (dev / self-hosted engine):
python seed_plan.py plans/plan-*.json --sqlite engine.db
```

Re-seeding the same plan_id+version is idempotent (it replaces its pills).

## 7. The full lifecycle at a glance

```
scan → pilot(90) → read 10 pills → tune → batch(90/180/270/365)
     → validate (+originality) → git commit → seed → cron starts sending
```

Total hands-on time: ~1 hour. Machine time: one night.
After that, content is a solved problem — everything else is distribution.

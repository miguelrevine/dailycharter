#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
validate_plan.py — quality gate for generated plans
------------------------------------------------------------
Run this on every plan BEFORE committing/seeding it.

  python validate_plan.py plans/plan-180.json
  python validate_plan.py plans/plan-180.json --pdf-dir ./pdfs   # + copy check

Checks:
  STRUCTURE   plan fields, days == len(pills), day sequence 1..N
              (--allow-partial skips this for pilot/in-progress runs)
  PILLS       title/lesson present, lesson is a real explanation (word-count
              floor, not a bare list), exam_traps present, 3 choices A/B/C,
              valid correct_key, every distractor has a "why"
  DUPLICATES  repeated titles (exact + case-insensitive)
  BALANCE     topic distribution vs exam weights (±3 pills tolerance)
  ORIGINALITY (with --pdf-dir) flags any pill sharing a verbatim
              10-word sequence with the source PDFs → rewrite those.

Exit code 0 = publishable · 1 = fix issues first.
============================================================
"""

import argparse, json, re, sys
from collections import Counter

# Reuse extraction + weights from the factory (same folder)
from pill_factory import build_topic_corpus, TOPIC_WEIGHTS

NGRAM = 10       # verbatim window: 10 consecutive identical words = copying
MIN_LESSON_WORDS = 250   # v2 lesson floor (spec: 300-450 word target)
MAX_LESSON_WORDS = 600   # generous ceiling — catches runaway generations

def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())

def shingles(text, n=NGRAM):
    w = words(text)
    return {" ".join(w[i:i+n]) for i in range(len(w) - n + 1)}

def pill_text(p):
    parts = [p.get("lesson", p.get("concept", "")),
             p.get("worked_example") or "",
             " ".join(p.get("exam_traps") or p.get("exam_tips") or [])]
    q = p.get("question") or {}
    parts.append(q.get("stem",""))
    parts += [c.get("why","") for c in q.get("choices",[])]
    return " ".join(parts)

def write_review(plan, n, out="review.html"):
    """Render n random pills into the interactive review page
    (template: review_template.html next to this script)."""
    import os, random
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "review_template.html")
    if not os.path.exists(tpl_path):
        sys.exit(f"✗ Missing template {tpl_path} — restore it from git.")
    picks = sorted(random.sample(plan["pills"], min(n, len(plan["pills"]))),
                   key=lambda x: x["day"])
    data = {
        "plan_id": plan.get("plan_id", "?"),
        "version": plan.get("version", ""),
        "model":   plan.get("model", ""),
        "total":   len(plan["pills"]),
        "pills":   picks,
    }
    doc = open(tpl_path, encoding="utf-8").read()
    doc = doc.replace("{{PLAN_ID}}", str(data["plan_id"]))
    # </script> inside JSON strings would end the script block early
    doc = doc.replace("{{PLAN_JSON}}",
                      json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    open(out, "w", encoding="utf-8").write(doc)
    print(f"\n▸ Human-review file → {out} ({len(picks)} pills). Open it in a browser.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json")
    ap.add_argument("--pdf-dir", help="source PDFs folder → enables copy check")
    ap.add_argument("--review", type=int, metavar="N",
                    help="also write review.html with N random pills for human reading")
    ap.add_argument("--allow-partial", action="store_true",
                    help="skip the days==len(pills) check — for pilot/in-progress runs")
    a = ap.parse_args()

    errors, warns = [], []

    # ---------- STRUCTURE ----------
    try:
        plan = json.load(open(a.plan_json, encoding="utf-8"))
    except Exception as e:
        sys.exit(f"✗ Cannot parse {a.plan_json}: {e}")

    for field in ("plan_id", "version", "days", "pills"):
        if field not in plan:
            errors.append(f"missing top-level field '{field}'")
    pills = plan.get("pills", [])
    days  = plan.get("days", 0)

    if len(pills) != days and not a.allow_partial:
        errors.append(f"days={days} but pills={len(pills)} (pass --allow-partial for a pilot slice)")
    seq = [p.get("day") for p in pills]
    if seq != list(range(1, len(seq)+1)):
        errors.append("pill 'day' fields are not a clean 1..N sequence")

    # ---------- PILLS ----------
    for p in pills:
        d = p.get("day", "?")
        if not p.get("title"):   errors.append(f"day {d}: missing title")
        lesson = p.get("lesson", p.get("concept", ""))
        n_words = len(words(lesson))
        if not lesson:
            errors.append(f"day {d}: missing lesson")
        elif n_words < MIN_LESSON_WORDS:
            warns.append(f"day {d}: lesson too short ({n_words} words, want ≥{MIN_LESSON_WORDS})")
        elif n_words > MAX_LESSON_WORDS:
            warns.append(f"day {d}: lesson too long ({n_words} words, want ≤{MAX_LESSON_WORDS})")
        traps = p.get("exam_traps", p.get("exam_tips"))
        if not traps:
            warns.append(f"day {d}: missing exam_traps")
        elif len(traps) < 2:
            warns.append(f"day {d}: only {len(traps)} exam_traps (want 2-3)")
        if "worked_example" not in p:
            warns.append(f"day {d}: worked_example key missing (use null explicitly if qualitative)")
        q = p.get("question") or {}
        keys = [ch.get("key") for ch in q.get("choices",[])]
        if sorted(keys) != ["A","B","C"]:
            errors.append(f"day {d}: choices must be exactly A/B/C (got {keys})")
        elif q.get("correct_key") not in keys:
            errors.append(f"day {d}: correct_key '{q.get('correct_key')}' not in choices")
        for ch in q.get("choices",[]):
            if not ch.get("why"):
                warns.append(f"day {d}: choice {ch.get('key')} lacks a 'why'")

    # ---------- DUPLICATES ----------
    titles = Counter((p.get("title") or "").strip().lower() for p in pills)
    for t, n in titles.items():
        if t and n > 1:
            warns.append(f"title repeated ×{n}: “{t}”")

    # ---------- BALANCE (skipped for pilot slices — meaningless on a partial plan) ----------
    if a.allow_partial:
        print("\nTopic distribution vs exam weight: skipped (--allow-partial)")
    else:
        total_w = sum(TOPIC_WEIGHTS.values())
        dist = Counter(p.get("topic") for p in pills)
        print("\nTopic distribution vs exam weight:")
        for topic, w in sorted(TOPIC_WEIGHTS.items(), key=lambda x:-x[1]):
            expected = round(w/total_w * days)
            got = dist.get(topic, 0)
            flag = "" if abs(got-expected) <= 3 else "  ← off balance"
            if flag: warns.append(f"topic '{topic}': {got} pills, expected ≈{expected}")
            bar = "█" * max(1, got*40//max(1,days))
            print(f"  {topic:<36} {got:>3} (≈{expected:>3}) {bar}{flag}")

    # ---------- ORIGINALITY ----------
    if a.pdf_dir:
        print(f"\nOriginality check ({NGRAM}-word verbatim windows) — extracting source…")
        corpus = build_topic_corpus(a.pdf_dir, log=lambda *x: None)
        src_shingles = {t: shingles(txt) for t, txt in corpus.items()}
        flagged = 0
        for p in pills:
            own = shingles(pill_text(p))
            hits = own & src_shingles.get(p.get("topic"), set())
            if hits:
                flagged += 1
                sample = next(iter(hits))
                errors.append(f"day {p['day']}: verbatim overlap with source → “{sample[:80]}…”")
        print(f"  {flagged} pill(s) flagged" if flagged else "  clean ✓")
    else:
        warns.append("originality check skipped (pass --pdf-dir to enable) — run it before publishing")

    # ---------- VERDICT ----------
    print(f"\n{'—'*56}")
    for w in warns:  print(f"  ⚠ {w}")
    for e in errors: print(f"  ✗ {e}")
    if a.review:
        write_review(plan, a.review)
    if errors:
        print(f"\n✗ {len(errors)} error(s), {len(warns)} warning(s) — fix before seeding.")
        sys.exit(1)
    print(f"\n✔ Plan '{plan.get('plan_id')}' {plan.get('version')} is publishable "
          f"({len(pills)} pills, {len(warns)} warning(s)).")

if __name__ == "__main__":
    main()

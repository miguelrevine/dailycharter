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
  PILLS       title/concept present, 3 choices A/B/C, valid correct_key,
              every distractor has a "why", concept length sane
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

NGRAM = 10  # verbatim window: 10 consecutive identical words = copying

def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())

def shingles(text, n=NGRAM):
    w = words(text)
    return {" ".join(w[i:i+n]) for i in range(len(w) - n + 1)}

def pill_text(p):
    parts = [p.get("concept",""), " ".join(p.get("exam_tips") or [])]
    q = p.get("question") or {}
    parts.append(q.get("stem",""))
    parts += [c.get("why","") for c in q.get("choices",[])]
    return " ".join(parts)

def write_review(plan, n, out="review.html"):
    """Render n random pills as cards for the mandatory human read-through."""
    import html as H, random
    picks = random.sample(plan["pills"], min(n, len(plan["pills"])))
    cards = []
    for p in sorted(picks, key=lambda x: x["day"]):
        q = p.get("question") or {}
        chs = "".join(
            f"<li><b>{H.escape(c.get('key',''))}.</b> {H.escape(c.get('text',''))}"
            f"{' ✓' if c.get('key')==q.get('correct_key') else ''}"
            f"<br><small>{H.escape(c.get('why',''))}</small></li>"
            for c in q.get("choices", []))
        tips = "".join(f"<li>{H.escape(t)}</li>" for t in (p.get("exam_tips") or []))
        cards.append(f"""
<div class="pill"><div class="meta">Day {p['day']} · {H.escape(p.get('topic',''))}</div>
<h2>{H.escape(p.get('title',''))}</h2>
<p>{H.escape(p.get('concept',''))}</p>
{'<pre>'+H.escape(p['formula'])+'</pre>' if p.get('formula') else ''}
{'<ul class="tips">'+tips+'</ul>' if tips else ''}
<p class="stem">{H.escape(q.get('stem',''))}</p><ol class="chs">{chs}</ol></div>""")
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Review — {plan['plan_id']}</title>
<style>body{{font-family:Arial;background:#FBFAF7;color:#13253A;max-width:720px;margin:30px auto;padding:0 20px}}
.pill{{background:#fff;border:1px solid #D8D4C8;border-radius:10px;padding:22px;margin-bottom:24px}}
.meta{{font-family:monospace;font-size:.75rem;color:#5B6B7C}}h2{{margin:6px 0 10px}}
pre{{background:#F2F0EA;border-left:3px solid #0E7C5B;padding:10px 14px}}
.tips li{{font-size:.9rem}}.stem{{font-weight:bold;border-top:1px dashed #D8D4C8;padding-top:12px}}
.chs li{{margin:8px 0}}small{{color:#5B6B7C}}</style></head>
<body><h1>Human review — {plan['plan_id']} {plan.get('version','')} · {len(picks)} random pills</h1>
<p>Read each like a subscriber: is the concept taught (not just named)?
Is the question answerable from the text? Are distractors plausible mistakes?</p>
{''.join(cards)}</body></html>"""
    open(out, "w", encoding="utf-8").write(doc)
    print(f"\n▸ Human-review file → {out} ({len(picks)} pills). Open it in a browser.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json")
    ap.add_argument("--pdf-dir", help="source PDFs folder → enables copy check")
    ap.add_argument("--review", type=int, metavar="N",
                    help="also write review.html with N random pills for human reading")
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

    if len(pills) != days:
        errors.append(f"days={days} but pills={len(pills)}")
    seq = [p.get("day") for p in pills]
    if seq != list(range(1, len(pills)+1)):
        errors.append("pill 'day' fields are not a clean 1..N sequence")

    # ---------- PILLS ----------
    for p in pills:
        d = p.get("day", "?")
        if not p.get("title"):   errors.append(f"day {d}: missing title")
        c = p.get("concept","")
        if len(c) < 80:          warns.append(f"day {d}: concept very short ({len(c)} chars)")
        if len(c) > 1200:        warns.append(f"day {d}: concept very long ({len(c)} chars)")
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

    # ---------- BALANCE ----------
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

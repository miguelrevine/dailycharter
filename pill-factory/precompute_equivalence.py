#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
precompute_equivalence.py — plan-switch day mapping (accounts-design.md §4)
------------------------------------------------------------
  python precompute_equivalence.py plans/plan-*.json

For every ordered pair of plans (A, B) and every day D of A, finds the
smallest day D' of B whose cumulative per-topic pill counts are at least
as large as A's, once A's counts are scaled by daysB/daysA:

  D' = min day in B such that for every topic t:
         countsB_upto(D')[t] >= countsA_upto(D)[t] * (daysB/daysA)

This is NOT round(D/daysA*daysB) — distribute_days() is a deficit
scheduler, so each plan rounds topic interleaving slightly differently;
matching cumulative topic coverage is the exact answer, the day count
ratio is only a fallback (accounts-design.md §4, applied by the Worker
when a cell is somehow missing).

Only meant to run on plans that already validated clean (0 errors,
0 warnings) — re-checks plan structure and refuses otherwise, since a
malformed 'topic' field would silently corrupt the mapping.

Output: pill-factory/plans/seed-equivalence.sql (same INSERT-statement
style as seed_plan.py) — apply with:
  wrangler d1 execute <DB_NAME> --file=plans/seed-equivalence.sql
============================================================
"""

import argparse, bisect, glob, json, sys
from collections import defaultdict


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


def check_clean(plan, path):
    """Minimal structural gate — the same invariants validate_plan.py
    enforces (STRUCTURE + PILLS), so a plan that fails these could never
    have passed --pdf-dir validation either. Doesn't repeat the slow
    originality/PDF check: that's assumed already clean per the workflow
    (qa_loop.sh only stops once validate_plan.py reports 0 warnings)."""
    errors = []
    pills = plan.get("pills", [])
    days = plan.get("days", 0)
    if len(pills) != days:
        errors.append(f"days={days} but pills={len(pills)}")
    seq = [p.get("day") for p in pills]
    if seq != list(range(1, len(pills) + 1)):
        errors.append("pill 'day' fields are not a clean 1..N sequence")
    for p in pills:
        if not p.get("topic"):
            errors.append(f"day {p.get('day', '?')}: missing topic")
    if errors:
        sys.exit(f"✗ {path} is not a clean plan — refusing to compute equivalence:\n  "
                  + "\n  ".join(errors))


def cumulative_topic_counts(plan):
    """{topic: [0, count_upto_day1, count_upto_day2, ...]} — index i is
    the cumulative count through day i (index 0 is the empty prefix)."""
    days = plan["days"]
    topics = sorted({p["topic"] for p in plan["pills"]})
    cum = {t: [0] * (days + 1) for t in topics}
    running = defaultdict(int)
    for p in sorted(plan["pills"], key=lambda x: x["day"]):
        running[p["topic"]] += 1
        d = p["day"]
        for t in topics:
            cum[t][d] = running[t]
    return cum


def target_day(cum_a, day_a, cum_b, days_a, days_b):
    """D' in B for day D of A, per the §4 algorithm."""
    ratio = days_b / days_a
    best = 1
    for topic, arr_a in cum_a.items():
        count_a = arr_a[day_a]
        if count_a <= 0:
            continue
        threshold = count_a * ratio
        arr_b = cum_b.get(topic)
        if arr_b is None:
            continue  # topic doesn't exist in B — no constraint from it
        i = bisect.bisect_left(arr_b, threshold)
        i = max(i, 1)
        best = max(best, i)
    return min(best, days_b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json", nargs="+", help="plan JSON files (globs ok)")
    ap.add_argument("--out", default="pill-factory/plans/seed-equivalence.sql")
    ap.add_argument("--sample", nargs=3, metavar=("FROM_PLAN_ID", "FROM_DAY", "TO_PLAN_ID"),
                     help="print one mapped day after computing, e.g. L1-90 30 L1-270")
    a = ap.parse_args()

    files = sorted({f for pat in a.plan_json for f in (glob.glob(pat) or [pat])})
    if len(files) < 2:
        sys.exit("Need at least 2 plans to compute equivalence.")

    plans = {}
    for path in files:
        plan = json.load(open(path, encoding="utf-8"))
        check_clean(plan, path)
        plans[plan["plan_id"]] = plan
        print(f"✔ {plan['plan_id']} ({plan['days']} days) — structurally clean, loaded")

    cum = {pid: cumulative_topic_counts(p) for pid, p in plans.items()}

    rows = []
    lookup = {}  # (from_id, from_day, to_id) -> to_day, for the --sample flag
    for from_id, from_plan in plans.items():
        for to_id, to_plan in plans.items():
            if from_id == to_id:
                continue
            days_a, days_b = from_plan["days"], to_plan["days"]
            cum_a, cum_b = cum[from_id], cum[to_id]
            for day_a in range(1, days_a + 1):
                day_b = target_day(
                    {t: arr for t, arr in cum_a.items()}, day_a, cum_b, days_a, days_b)
                rows.append((from_id, day_a, to_id, day_b))
                lookup[(from_id, day_a, to_id)] = day_b
            print(f"  {from_id} → {to_id}: {days_a} day(s) mapped")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("-- generated by precompute_equivalence.py — apply with:\n")
        f.write(f"--   wrangler d1 execute <DB_NAME> --file={a.out}\n")
        f.write("DELETE FROM plan_equivalence;\n")
        for from_id, day_a, to_id, day_b in rows:
            f.write(f"INSERT INTO plan_equivalence VALUES "
                     f"({q(from_id)},{day_a},{q(to_id)},{day_b});\n")
    print(f"\n✔ {len(rows)} row(s) → {a.out}")

    if a.sample:
        from_id, from_day, to_id = a.sample[0], int(a.sample[1]), a.sample[2]
        result = lookup.get((from_id, from_day, to_id))
        if result is None:
            print(f"\n(no row for {from_id} day {from_day} → {to_id} — check plan_ids)")
        else:
            print(f"\nSample: {from_id} day {from_day} → {to_id} day {result}")


if __name__ == "__main__":
    main()

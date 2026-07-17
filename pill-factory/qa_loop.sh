#!/bin/bash
# qa_loop.sh <plan_days> [max_rounds]
# Validate → regen (errors + duplicate titles + per-day warnings) → repeat
# until clean or max_rounds. Survives a crashed regen round (retries next).
d=$1; rounds=${2:-6}
plan="pill-factory/plans/plan-$d.json"
AVOID="compared to public equity which of the following is least likely to characterize; which of the following is least likely. Prefer scenario-style stems about a specific investor or firm asking what is most accurate. If this concept was already covered earlier in the plan, choose a DIFFERENT testable concept from the reference and give it a distinct title"

for i in $(seq 1 "$rounds"); do
  PYTHONUTF8=1 python -u pill-factory/validate_plan.py "$plan" \
    --pdf-dir pill-factory/pdfs > "pill-factory/validate-$d.log" 2>&1
  errdays=$(grep -oE '✗ day [0-9]+' "pill-factory/validate-$d.log" | grep -oE '[0-9]+')
  warndays=$(grep -oE '⚠ day [0-9]+' "pill-factory/validate-$d.log" | grep -oE '[0-9]+')
  dupdays=$(python - "$plan" <<'PY'
import json, sys
from collections import defaultdict
p = json.load(open(sys.argv[1], encoding="utf-8"))
t = defaultdict(list)
for x in p["pills"]:
    t[x["title"].strip().lower()].append(x["day"])
print("\n".join(str(day) for v in t.values() if len(v) > 1 for day in v[1:]))
PY
)
  all=$(printf '%s\n%s\n%s\n' "$errdays" "$warndays" "$dupdays" | grep -E '^[0-9]+$' | sort -un | tr '\n' ',' | sed 's/,$//')
  if [ -z "$all" ]; then
    echo "PLAN-$d CLEAN after $((i-1)) regen round(s)"
    exit 0
  fi
  n=$(echo "$all" | tr ',' '\n' | wc -l)
  echo "PLAN-$d round $i: regenerating $n day(s): $all"
  PYTHONUTF8=1 python -u pill-factory/pill_factory.py regen \
    --pdf-dir pill-factory/pdfs --plan-json "$plan" --days "$all" \
    --model qwen3:14b --avoid "$AVOID" >> "pill-factory/regen-$d.log" 2>&1 \
    || echo "PLAN-$d round $i: regen crashed (will retry what's left next round)"
done
echo "PLAN-$d NOT CLEAN after $rounds rounds — needs manual attention"
exit 1

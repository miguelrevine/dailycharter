#!/bin/bash
# Fase 5: generación nocturna 180/270/365 + validación de cada plan.
for d in 180 270 365; do
  echo "=== GENERATE $d START $(date '+%H:%M') ==="
  if PYTHONUTF8=1 python -u pill-factory/pill_factory.py generate \
      --pdf-dir pill-factory/pdfs --plan $d --model qwen3:14b \
      > pill-factory/generate-$d.log 2>&1; then
    echo "=== GENERATE $d OK $(date '+%H:%M') ==="
  else
    echo "=== GENERATE $d FAILED $(date '+%H:%M') — see generate-$d.log ==="
    continue
  fi
  if PYTHONUTF8=1 python -u pill-factory/validate_plan.py \
      pill-factory/plans/plan-$d.json --pdf-dir pill-factory/pdfs \
      > pill-factory/validate-$d.log 2>&1; then
    echo "=== VALIDATE $d CLEAN ==="
  else
    echo "=== VALIDATE $d FLAGGED: $(grep -c 'verbatim overlap' pill-factory/validate-$d.log) pill(s) ==="
  fi
done
echo "=== OVERNIGHT DONE $(date '+%H:%M') ==="

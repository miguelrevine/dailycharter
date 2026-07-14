# Pill Factory (local)

PDFs → local LLM (Ollama) → plan JSONs for DailyCharter. 100% on your machine.

## Setup
    pip install pypdf requests
    ollama pull llama3.1        # or mistral, qwen2.5, phi4…

## Use
    python pill_factory.py scan     --pdf-dir ./pdfs         # check topic mapping
    python pill_factory.py serve    --pdf-dir ./pdfs         # web app on :8765
    python pill_factory.py generate --pdf-dir ./pdfs --plan 270 --model llama3.1

Plans: 90 (Sprint) · 180 (Standard) · 270 (Extended) · 365 (Marathon).
Output: plans/plan-<N>.json — commit these to Git (see plan-engine-design.md).

Generation checkpoints after every pill (plan-N.json.partial), so you can
Ctrl+C and resume anytime. A 365-day plan on a laptop takes hours: leave it
overnight.

⚠ Content policy: the PDFs are copyrighted reference material. The prompt
forces ORIGINAL writing and forbids copying; still, spot-check generated
pills against the source before publishing.

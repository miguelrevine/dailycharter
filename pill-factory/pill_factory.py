#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
Pill Factory — local pill-generation pipeline for DailyCharter
------------------------------------------------------------
PDFs folder ──► text extraction ──► local LLM (Ollama) ──► plan JSON

Everything runs ON YOUR MACHINE. No cloud calls: the LLM is
your local Ollama server (http://localhost:11434).

USAGE
  python pill_factory.py scan     --pdf-dir ./pdfs
  python pill_factory.py generate --pdf-dir ./pdfs --plan 180 --model llama3.1
  python pill_factory.py serve    --pdf-dir ./pdfs        # web app → http://localhost:8765

REQUIREMENTS
  pip install pypdf requests
  ollama pull llama3.1            (or any model you prefer)

OUTPUT
  plans/plan-<DAYS>.json          one self-contained file per plan
                                  (see plan-engine-design.md for how the
                                   mail engine consumes these)

IMPORTANT — CONTENT POLICY
  The source PDFs are copyrighted study material. They are used as
  REFERENCE so the model writes accurate ORIGINAL explanations of the
  public CFA Level I learning outcomes. The prompt explicitly forbids
  copying or closely paraphrasing sentences from the source. Review a
  sample of generated pills against the source before publishing.
============================================================
"""

import argparse, json, os, re, sys, time, threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

# ──────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("PILL_MODEL", "llama3.1")
PLANS_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans")

# Exam topic weights (midpoints of official ranges, normalized at runtime)
TOPIC_WEIGHTS = {
    "Ethical & Professional Standards": 17.5,
    "Financial Reporting & Analysis":   15.0,
    "Equity Investments":               11.0,
    "Fixed Income":                     11.0,
    "Quantitative Methods":             10.0,
    "Economics":                        10.0,
    "Corporate Finance":                 9.0,
    "Portfolio Management":              6.5,
    "Derivatives":                       6.5,
    "Alternative Investments":           6.5,
}

# Map PDF filenames → topics they contain (keyword, case-insensitive).
# Adjust freely if your folder uses other names.
PDF_TOPIC_KEYWORDS = {
    "ethics":      ["Ethical & Professional Standards", "Quantitative Methods"],
    "economics":   ["Economics"],
    "reporting":   ["Financial Reporting & Analysis"],
    "analisis":    ["Financial Reporting & Analysis"],
    "corporate":   ["Corporate Finance", "Equity Investments"],
    "derivatives": ["Fixed Income", "Derivatives",
                    "Alternative Investments", "Portfolio Management"],
    "management":  ["Portfolio Management"],
}

# Plan catalogue offered by the app
PLAN_CATALOG = {
    90:  {"name": "Sprint",    "tagline": "Crunch mode — 2 concepts/day pace, for a close exam window."},
    180: {"name": "Standard",  "tagline": "The classic 6-month runway. One pill a day, exam-weighted."},
    270: {"name": "Extended",  "tagline": "9 relaxed months with deeper coverage per topic."},
    365: {"name": "Marathon",  "tagline": "A full year: maximum granularity, gentlest daily load."},
}

# ──────────────────────────────────────────────────────────
# 1) PDF collection & extraction
# ──────────────────────────────────────────────────────────

def find_pdfs(pdf_dir):
    """Collect every PDF in the folder (non-recursive by design: one
    folder = one curriculum). Returns sorted list of absolute paths."""
    if not os.path.isdir(pdf_dir):
        raise SystemExit(f"PDF folder not found: {pdf_dir}")
    pdfs = sorted(
        os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir)
        if f.lower().endswith(".pdf")
    )
    if not pdfs:
        raise SystemExit(f"No PDFs found in {pdf_dir}")
    return pdfs

def topics_for_pdf(path):
    name = os.path.basename(path).lower()
    hits = []
    for kw, topics in PDF_TOPIC_KEYWORDS.items():
        if kw in name:
            for t in topics:
                if t not in hits:
                    hits.append(t)
    return hits or ["General"]

def extract_text(path, log=print):
    """Extract plain text per PDF using pypdf. Returns one big string."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("Missing dependency: pip install pypdf")
    log(f"  extracting {os.path.basename(path)} …")
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    log(f"    {len(reader.pages)} pages, {len(text):,} chars")
    return text

def build_topic_corpus(pdf_dir, log=print):
    """{topic: concatenated reference text} across all PDFs."""
    corpus = {}
    for path in find_pdfs(pdf_dir):
        text = extract_text(path, log)
        tlist = topics_for_pdf(path)
        share = max(1, len(tlist))
        chunk = len(text) // share
        for i, topic in enumerate(tlist):   # split book text across its topics
            part = text[i*chunk : (i+1)*chunk if i < share-1 else len(text)]
            corpus.setdefault(topic, "")
            corpus[topic] += "\n\n" + part
    return corpus

# ──────────────────────────────────────────────────────────
# 2) Curriculum distribution (which topic on which day)
# ──────────────────────────────────────────────────────────

def distribute_days(days):
    """Assign a topic to every day 1..N, interleaved by exam weight.
    Greedy deficit scheduler: each day, the topic furthest behind its
    ideal share gets the slot → topics mix instead of forming blocks."""
    total_w = sum(TOPIC_WEIGHTS.values())
    ideal   = {t: w/total_w for t, w in TOPIC_WEIGHTS.items()}
    given   = {t: 0 for t in TOPIC_WEIGHTS}
    schedule = []
    for day in range(1, days+1):
        topic = max(ideal, key=lambda t: ideal[t]*day - given[t])
        given[topic] += 1
        schedule.append(topic)
    return schedule  # list index 0 = day 1

def slice_reference(corpus_text, index, total, max_chars=6000):
    """Give pill #index (of `total` in this topic) its slice of the
    topic's reference text, so pills progress through the material."""
    if not corpus_text:
        return ""
    n = max(1, total)
    size = len(corpus_text) // n
    start = index * size
    return corpus_text[start : start + max(size, max_chars)][:max_chars]

# ──────────────────────────────────────────────────────────
# 3) Local LLM (Ollama)
# ──────────────────────────────────────────────────────────

PILL_SCHEMA_HINT = """{
  "title": "short, specific concept title",
  "concept": "2-4 sentence ORIGINAL plain-language explanation",
  "exam_tips": ["tip 1", "tip 2"],
  "formula": "the key formula in plain text, or null",
  "question": {
    "stem": "one exam-style question",
    "choices": [
      {"key":"A","text":"…","why":"why this distractor is tempting/wrong"},
      {"key":"B","text":"…","why":"…"},
      {"key":"C","text":"…","why":"…"}
    ],
    "correct_key": "A|B|C"
  }
}"""

def ollama_ready():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.ok
    except requests.RequestException:
        return False

def require_model(model):
    """Fail fast with a clear message if `model` isn't pulled in Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        raise SystemExit(f"Ollama not reachable at {OLLAMA_URL}")
    names = [m["name"] for m in r.json().get("models", [])]
    if model not in names and f"{model}:latest" not in names:
        raise SystemExit(
            f"Model '{model}' not found in Ollama. Available: {', '.join(names) or '(none)'}\n"
            f"Pass --model <name> or pull it: ollama pull {model}")

def generate_pill(model, topic, day, days, reference, retries=4,
                  extra_rules="", temperature=0.7):
    """One LLM call → one validated pill dict."""
    system = (
        "You write daily micro-lessons ('pills') for CFA Level I candidates. "
        "You are given REFERENCE MATERIAL for factual accuracy only. "
        "STRICT RULES: write completely ORIGINAL text — never copy or closely "
        "paraphrase sentences from the reference; explain in your own words. "
        "One concept per pill. B-level English, friendly but precise. "
        "The three answer choices must include realistic distractors based on "
        "common candidate mistakes. " + extra_rules +
        "Respond with ONLY valid JSON, no markdown, "
        f"matching exactly this schema:\n{PILL_SCHEMA_HINT}"
    )
    user = (
        f"Topic: {topic}\nThis is pill for day {day} of a {days}-day plan. "
        f"Pick ONE testable concept that appears in the reference below and "
        f"write the pill.\n\nREFERENCE MATERIAL (accuracy only, do not copy):\n"
        f"{reference}"
    )
    for attempt in range(retries + 1):
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model,
                "messages": [{"role":"system","content":system},
                             {"role":"user","content":user}],
                "format": "json",
                "stream": False,
                "options": {"temperature": temperature},
            }, timeout=600)
            r.raise_for_status()
        # Ollama hiccups (404 while the model reloads, timeouts, resets)
        # are transient — back off and retry instead of killing the run.
        except requests.RequestException as e:
            body = getattr(getattr(e, "response", None), "text", "")
            print(f"  ! Ollama error day {day} attempt {attempt+1}: {e} {body[:200]}",
                  file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(15 * (attempt + 1))
            continue
        raw = r.json().get("message", {}).get("content", "")
        try:
            pill = json.loads(raw)
            assert isinstance(pill, dict)
            assert pill.get("title") and pill.get("concept")
            q = pill.get("question") or {}
            keys = [c.get("key") for c in q.get("choices", [])]
            assert sorted(keys) == ["A","B","C"] and q.get("correct_key") in keys
            return pill
        # AttributeError/TypeError: model returned the right JSON but the
        # wrong shape (e.g. choices as plain strings) — retry, don't crash.
        except (json.JSONDecodeError, AssertionError, AttributeError, TypeError):
            if attempt == retries:
                raise ValueError(f"Model returned invalid pill JSON (day {day})")
            time.sleep(1)

# ──────────────────────────────────────────────────────────
# 4) Plan generation
# ──────────────────────────────────────────────────────────

def generate_plan(pdf_dir, days, model, log=print, progress=None):
    if days not in PLAN_CATALOG:
        raise SystemExit(f"Plan must be one of {sorted(PLAN_CATALOG)}")
    if not ollama_ready():
        raise SystemExit(f"Cannot reach Ollama at {OLLAMA_URL}. Is it running? (ollama serve)")

    log(f"▸ Building corpus from {pdf_dir}")
    corpus   = build_topic_corpus(pdf_dir, log)
    schedule = distribute_days(days)
    counts   = {t: schedule.count(t) for t in set(schedule)}
    seen     = {t: 0 for t in counts}

    plan = {
        "plan_id":      f"L1-{days}",
        "version":      datetime.now().strftime("v%Y%m%d"),
        "days":         days,
        "name":         PLAN_CATALOG[days]["name"],
        "model":        model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pills":        [],
    }

    os.makedirs(PLANS_DIR, exist_ok=True)
    out_path    = os.path.join(PLANS_DIR, f"plan-{days}.json")
    resume_path = out_path + ".partial"

    # Resume support: long runs on local hardware can be interrupted.
    if os.path.exists(resume_path):
        with open(resume_path, encoding="utf-8") as f:
            plan = json.load(f)
        for p in plan["pills"]:
            seen[p["topic"]] = seen.get(p["topic"], 0) + 1
        log(f"▸ Resuming: {len(plan['pills'])} pills already generated")

    start_day = len(plan["pills"]) + 1
    t0 = time.time()
    for day in range(start_day, days + 1):
        topic = schedule[day - 1]
        ref   = slice_reference(corpus.get(topic, ""), seen[topic], counts[topic])
        pill  = generate_pill(model, topic, day, days, ref)
        pill.update({"day": day, "topic": topic,
                     "id": f"{plan['plan_id']}-{day:03d}"})
        plan["pills"].append(pill)
        seen[topic] += 1

        with open(resume_path, "w", encoding="utf-8") as f:   # checkpoint every pill
            json.dump(plan, f, ensure_ascii=False)

        done = day - start_day + 1
        rate = (time.time() - t0) / done
        eta  = int(rate * (days - day) / 60)
        msg  = f"  [{day:>3}/{days}] {topic[:34]:<34} ~{eta} min left"
        log(msg)
        if progress:
            progress(day, days, msg)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    os.remove(resume_path)
    log(f"✔ Plan written to {out_path}  ({len(plan['pills'])} pills)")
    return out_path

def regen_pills(pdf_dir, plan_path, days_list, model, avoid="", log=print):
    """Regenerate specific days of an existing plan JSON in place.
    Pre-seed QA use only — once a plan is seeded its version is immutable."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    total    = plan["days"]
    corpus   = build_topic_corpus(pdf_dir, log)
    schedule = distribute_days(total)
    counts   = {t: schedule.count(t) for t in set(schedule)}
    by_day   = {p["day"]: i for i, p in enumerate(plan["pills"])}
    for day in days_list:
        topic = schedule[day - 1]
        index = schedule[:day - 1].count(topic)  # same slice as the original run
        ref   = slice_reference(corpus.get(topic, ""), index, counts[topic])
        # regen only runs on QA-rejected pills — push harder against copying
        # and add sampling variance so retries don't reproduce the same text.
        rules = (
            "A previous draft of this pill was REJECTED for copying wording "
            "from the reference. Never reuse any sequence of 6+ consecutive "
            "words from the reference: restructure every sentence, change the "
            "order of ideas, and use your own examples and phrasing. ")
        if avoid:
            banned = "; ".join(f"“{p.strip()}”"
                               for p in avoid.split(";") if p.strip())
            rules += ("These phrases from rejected drafts are BANNED — write "
                      f"nothing resembling them: {banned}. ")
        pill  = generate_pill(model, topic, day, total, ref,
                              extra_rules=rules, temperature=0.85)
        pill.update({"day": day, "topic": topic,
                     "id": f"{plan['plan_id']}-{day:03d}"})
        plan["pills"][by_day[day]] = pill
        with open(plan_path, "w", encoding="utf-8") as f:   # keep progress on crash
            json.dump(plan, f, ensure_ascii=False, indent=1)
        log(f"  regenerated day {day:>3}  ({topic})")
    log(f"✔ {len(days_list)} pill(s) regenerated in {plan_path}")

# ──────────────────────────────────────────────────────────
# 5) Local web app (plan selector)  —  stdlib only
# ──────────────────────────────────────────────────────────

JOB = {"running": False, "done": 0, "total": 0, "log": [], "error": None, "out": None}

APP_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pill Factory — DailyCharter</title><style>
:root{--ink:#13253A;--paper:#FBFAF7;--paper2:#F2F0EA;--green:#0E7C5B;--marker:#FFE86B;--rule:#D8D4C8;--muted:#5B6B7C}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,Helvetica,sans-serif;background:var(--paper);color:var(--ink);
background-image:repeating-linear-gradient(transparent 0 31px,rgba(19,37,58,.035) 31px 32px);padding:40px 20px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:1.7rem;letter-spacing:-.02em;margin-bottom:4px}
h1 s{color:var(--green);text-decoration:none}
.sub{color:var(--muted);font-size:.95rem;margin-bottom:28px}
.card{background:#fff;border:1px solid var(--rule);border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 10px 30px rgba(19,37,58,.07)}
.card h2{font-size:1.05rem;margin-bottom:14px}
.mono{font-family:'Courier New',monospace;font-size:.8rem;color:var(--muted)}
.pdfs li{font-family:'Courier New',monospace;font-size:.82rem;padding:6px 0;border-bottom:1px dashed var(--rule);list-style:none}
.plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.plan{border:1.5px solid var(--rule);border-radius:10px;padding:16px;cursor:pointer;background:var(--paper)}
.plan:hover{border-color:var(--ink)}
.plan.sel{border-color:var(--ink);box-shadow:0 0 0 1px var(--ink);background:#fff}
.plan b{font-size:1.3rem;display:block}
.plan .nm{font-family:'Courier New',monospace;font-size:.72rem;color:var(--green);letter-spacing:.05em}
.plan p{font-size:.78rem;color:var(--muted);margin-top:6px}
label{font-weight:bold;font-size:.85rem;display:block;margin:14px 0 6px}
input{width:100%;padding:11px 13px;border:1px solid var(--rule);border-radius:6px;font-size:.95rem}
.btn{margin-top:18px;background:var(--ink);color:#fff;border:none;border-radius:6px;padding:13px 26px;font-weight:bold;font-size:.95rem;cursor:pointer}
.btn:disabled{opacity:.5;cursor:not-allowed}
.bar{height:10px;background:var(--paper2);border-radius:5px;overflow:hidden;margin:14px 0 8px;display:none}
.bar i{display:block;height:100%;width:0;background:var(--green);transition:width .4s}
#log{font-family:'Courier New',monospace;font-size:.75rem;color:var(--muted);white-space:pre-wrap;max-height:220px;overflow:auto;background:var(--paper2);border-radius:8px;padding:12px;display:none}
.ok{color:var(--green);font-weight:bold}.err{color:#C0564F;font-weight:bold}
.badge{display:inline-block;background:var(--marker);font-family:'Courier New',monospace;font-size:.68rem;font-weight:bold;padding:2px 9px;border-radius:10px;margin-left:8px}
</style></head><body><div class="wrap">
<h1>Pill Factory<s>.</s> <span class="badge">100% LOCAL</span></h1>
<p class="sub">PDFs → local LLM (Ollama) → plan JSON. Nothing leaves this machine.</p>

<div class="card"><h2>1 · Curriculum PDFs <span class="mono" id="pdf-dir"></span></h2>
<ul class="pdfs" id="pdf-list"><li>Loading…</li></ul></div>

<div class="card"><h2>2 · Choose the plan to generate</h2>
<div class="plans" id="plans"></div>
<label for="model">Ollama model</label>
<input id="model" value="__MODEL__">
<p class="mono" style="margin-top:6px">Server: __OLLAMA__ · status: <span id="ollama-st">checking…</span></p>
<button class="btn" id="go" disabled>Generate plan</button>
<div class="bar" id="bar"><i id="bar-i"></i></div>
<p class="mono" id="pct"></p>
<div id="log"></div></div>

<script>
var sel=null, CAT=__CATALOG__;
fetch('/api/pdfs').then(r=>r.json()).then(d=>{
  document.getElementById('pdf-dir').textContent='· '+d.dir;
  document.getElementById('pdf-list').innerHTML =
    d.pdfs.map(p=>'<li>📄 '+p.name+' <span style="float:right">'+p.topics.join(', ')+'</span></li>').join('')
    || '<li>No PDFs found in this folder.</li>';
});
fetch('/api/ollama').then(r=>r.json()).then(d=>{
  document.getElementById('ollama-st').innerHTML = d.ok
    ? '<span class="ok">connected ✓</span>'
    : '<span class="err">unreachable — run: ollama serve</span>';
});
var box=document.getElementById('plans');
Object.keys(CAT).forEach(function(k){
  var d=document.createElement('div'); d.className='plan'; d.dataset.days=k;
  d.innerHTML='<span class="nm">'+CAT[k].name.toUpperCase()+'</span><b>'+k+' days</b><p>'+CAT[k].tagline+'</p>';
  d.onclick=function(){document.querySelectorAll('.plan').forEach(p=>p.classList.remove('sel'));
    d.classList.add('sel'); sel=k; document.getElementById('go').disabled=false;};
  box.appendChild(d);
});
document.getElementById('go').onclick=function(){
  this.disabled=true;
  fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({days:parseInt(sel),model:document.getElementById('model').value})})
  .then(()=>{document.getElementById('bar').style.display='block';
             document.getElementById('log').style.display='block'; poll();});
};
function poll(){
  fetch('/api/status').then(r=>r.json()).then(function(s){
    document.getElementById('bar-i').style.width=(s.total? s.done*100/s.total:0)+'%';
    document.getElementById('pct').textContent=s.done+' / '+s.total+' pills';
    document.getElementById('log').textContent=s.log.slice(-40).join('\\n');
    var el=document.getElementById('log'); el.scrollTop=el.scrollHeight;
    if(s.error){document.getElementById('pct').innerHTML='<span class="err">'+s.error+'</span>';return;}
    if(s.out){document.getElementById('pct').innerHTML='<span class="ok">✔ Done → '+s.out+'</span>';return;}
    setTimeout(poll,1500);
  });
}
</script></div></body></html>"""

def make_handler(pdf_dir, default_model):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            if ctype.startswith("text/html"): data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a): pass  # silence default request logging

        def do_GET(self):
            p = urlparse(self.path).path
            if p == "/":
                html = (APP_HTML.replace("__MODEL__", default_model)
                                .replace("__OLLAMA__", OLLAMA_URL)
                                .replace("__CATALOG__", json.dumps(PLAN_CATALOG)))
                self._send(200, html, "text/html; charset=utf-8")
            elif p == "/api/pdfs":
                pdfs = [{"name": os.path.basename(x), "topics": topics_for_pdf(x)}
                        for x in find_pdfs(pdf_dir)]
                self._send(200, {"dir": os.path.abspath(pdf_dir), "pdfs": pdfs})
            elif p == "/api/ollama":
                self._send(200, {"ok": ollama_ready()})
            elif p == "/api/status":
                self._send(200, JOB)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/api/generate":
                return self._send(404, {"error": "not found"})
            if JOB["running"]:
                return self._send(409, {"error": "a generation job is already running"})
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            days, model = int(body["days"]), body.get("model") or default_model
            JOB.update(running=True, done=0, total=days, log=[], error=None, out=None)

            def worker():
                try:
                    out = generate_plan(
                        pdf_dir, days, model,
                        log=lambda m: JOB["log"].append(str(m)),
                        progress=lambda d, t, m: JOB.update(done=d, total=t))
                    JOB["out"] = out
                except BaseException as e:
                    JOB["error"] = str(e)
                finally:
                    JOB["running"] = False
            threading.Thread(target=worker, daemon=True).start()
            self._send(202, {"started": True})
    return H

# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="DailyCharter Pill Factory (local)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("scan", help="list PDFs found and their topic mapping")
    p1.add_argument("--pdf-dir", required=True)

    p2 = sub.add_parser("generate", help="generate one plan from the CLI")
    p2.add_argument("--pdf-dir", required=True)
    p2.add_argument("--plan", type=int, required=True,
                    choices=sorted(PLAN_CATALOG), help="plan length in days")
    p2.add_argument("--model", default=DEFAULT_MODEL)

    p4 = sub.add_parser("regen", help="regenerate specific days of an existing plan (pre-seed QA)")
    p4.add_argument("--pdf-dir", required=True)
    p4.add_argument("--plan-json", required=True)
    p4.add_argument("--days", required=True, help="comma-separated day numbers, e.g. 5,7,17")
    p4.add_argument("--model", default=DEFAULT_MODEL)
    p4.add_argument("--avoid", default="",
                    help="';'-separated phrases the new pills must not contain")

    p3 = sub.add_parser("serve", help="local web app to pick & generate plans")
    p3.add_argument("--pdf-dir", required=True)
    p3.add_argument("--port", type=int, default=8765)
    p3.add_argument("--model", default=DEFAULT_MODEL)

    a = ap.parse_args()
    if a.cmd == "scan":
        for path in find_pdfs(a.pdf_dir):
            print(f"📄 {os.path.basename(path)}")
            print(f"   topics → {', '.join(topics_for_pdf(path))}")
    elif a.cmd == "generate":
        require_model(a.model)
        generate_plan(a.pdf_dir, a.plan, a.model)
    elif a.cmd == "regen":
        require_model(a.model)
        regen_pills(a.pdf_dir, a.plan_json,
                    [int(x) for x in a.days.split(",")], a.model, a.avoid)
    elif a.cmd == "serve":
        find_pdfs(a.pdf_dir)  # fail fast if folder is wrong
        print(f"▸ Pill Factory app → http://localhost:{a.port}")
        HTTPServer(("127.0.0.1", a.port),
                   make_handler(a.pdf_dir, a.model)).serve_forever()

if __name__ == "__main__":
    main()

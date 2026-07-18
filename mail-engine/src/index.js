/* ============================================================
   DailyCharter mail engine — Cloudflare Worker + D1
   ------------------------------------------------------------
   scheduled()  hourly cron: the next_day JOIN → render → ESP →
                advance pointer. See plan-engine-design.md §5.
   fetch()      quiz + subscription API:
     POST /api/subscribe      {email, first_name, plan_days, exam_date?}
     GET  /api/question       ?token&pill_id     (no correct_key leaks)
     POST /api/attempts       {token, pill_id, choice, source}
     GET  /api/review-next    ?token
     GET  /unsubscribe        ?u=token   → confirm page (GET never writes)
     POST /unsubscribe        {token}    → actually cancels
     GET  /health

     Accounts (accounts-design.md) — a SEPARATE, short-lived session
     token, never to be confused with the quiz token above:
     POST /api/signup                {email, password, first_name, plan_days, exam_date?}
     POST /api/login                 {email, password} → {session_token}
     POST /api/logout                {session_token}
     GET  /api/account                Authorization: Bearer <session_token>
     GET  /api/account/plan-options  ?new_plan_days=  Authorization: Bearer <session_token>
                                      (addition beyond §3 — lets the frontend show the
                                      restart-vs-resume outcome before the user picks one)
     POST /api/account/change-plan   {session_token, new_plan_days, mode: restart|resume}
     POST /api/account/cancel        {session_token}
     POST /api/account/password      {session_token, current_password, new_password}
     GET  /api/admin/subscribers     Authorization: Bearer <ADMIN_TOKEN>  ?limit=&offset=
   Secrets:  TOKEN_SECRET, ESP_API_KEY, ADMIN_TOKEN   (wrangler secret put …)
   Vars:     SITE_URL, FROM_EMAIL            (wrangler.toml)
   ============================================================ */

// ──────────────────────────────────────────────
// Tokens: subscriber_id.HMAC(secret, subscriber_id)  — spec §5
// ──────────────────────────────────────────────
const enc = new TextEncoder();

function b64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64url(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}

export async function makeToken(env, subscriberId) {
  return `${subscriberId}.${await hmac(env.TOKEN_SECRET, subscriberId)}`;
}

async function verifyToken(env, token) {
  const dot = (token || "").lastIndexOf(".");
  if (dot < 1) return null;
  const id = token.slice(0, dot), sig = token.slice(dot + 1);
  return (await hmac(env.TOKEN_SECRET, id)) === sig ? id : null;
}

// ──────────────────────────────────────────────
// Accounts: passwords (PBKDF2 — bcrypt isn't available in Workers),
// sessions (short-lived, browser-only — distinct from the quiz token
// above, which must keep working forever even with no password set)
// accounts-design.md §2
// ──────────────────────────────────────────────
async function hashPassword(password, salt) {
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: enc.encode(salt), iterations: 100000, hash: "SHA-256" },
    key, 256);
  return b64url(bits);
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function verifyPassword(password, salt, hash) {
  return timingSafeEqual(await hashPassword(password, salt), hash);
}

function newSessionToken() {
  return b64url(crypto.getRandomValues(new Uint8Array(32)));
}

// SQLite datetime() output format ('YYYY-MM-DD HH:MM:SS') — sessions.expires_at
// must use the same format so `WHERE expires_at > datetime('now')` compares correctly.
function sqliteDatetime(date) {
  return date.toISOString().slice(0, 19).replace("T", " ");
}

async function sessionSubscriberByToken(env, token) {
  if (!token) return null;
  return env.DB.prepare(
    `SELECT s.* FROM sessions se JOIN subscribers s ON s.id = se.subscriber_id
     WHERE se.token=? AND se.expires_at > datetime('now')`).bind(token).first();
}

function bearerToken(req) {
  const h = req.headers.get("Authorization") || "";
  return h.startsWith("Bearer ") ? h.slice(7) : null;
}

// Create a subscriber row shared by /api/subscribe (no password, checkout/
// no-login flow) and /api/signup (sets password_hash/salt too) — same
// validation and plan lookup either way, per accounts-design.md §3.
async function createSubscriber(env, { email, first_name, plan_days, exam_date, password }) {
  if (!email || !plan_days) return { error: "email and plan_days required", status: 400 };
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
    return { error: "That doesn't look like a valid email address", status: 400 };
  if (password !== undefined && password.length < 8)
    return { error: "Password must be at least 8 characters", status: 400 };
  const planId = `L1-${parseInt(plan_days)}`;
  const plan = await env.DB.prepare(
    `SELECT plan_version FROM plans WHERE plan_id=?
     ORDER BY plan_version DESC LIMIT 1`).bind(planId).first();
  if (!plan) return { error: "This plan length isn't available yet", status: 404 };

  const id = crypto.randomUUID();
  let passwordHash = null, passwordSalt = null;
  if (password) {
    passwordSalt = crypto.randomUUID();
    passwordHash = await hashPassword(password, passwordSalt);
  }
  try {
    await env.DB.prepare(
      `INSERT INTO subscribers (id, email, first_name, plan_id, plan_version, exam_date, password_hash, password_salt)
       VALUES (?,?,?,?,?,?,?,?)`)
      .bind(id, email.toLowerCase().trim(), first_name || null, planId, plan.plan_version,
            exam_date || null, passwordHash, passwordSalt).run();
  } catch { return { error: "email already subscribed", status: 409 }; }
  return { id };
}

// Plan-switch target day — accounts-design.md §4. The lookup table is
// precomputed offline (pill-factory/precompute_equivalence.py); this is
// deliberately a cheap SELECT, never a live recomputation. Falls back to
// percentage mapping only if a cell is somehow missing.
async function resolveResumeDay(env, fromPlanId, fromDay, toPlanId, fromDays, toDays) {
  const row = await env.DB.prepare(
    `SELECT to_day FROM plan_equivalence WHERE from_plan_id=? AND from_day=? AND to_plan_id=?`)
    .bind(fromPlanId, fromDay, toPlanId).first();
  if (row) return row.to_day;
  return Math.min(toDays, Math.max(1, Math.round((fromDay / fromDays) * toDays)));
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────
function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...extra },
  });
}

function cors(env) {
  // ACAO must be an origin (scheme+host), not a URL with a path —
  // SITE_URL is e.g. https://user.github.io/dailycharter
  return {
    "Access-Control-Allow-Origin": new URL(env.SITE_URL).origin,
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

const nextSunday = () => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + ((7 - d.getUTCDay()) % 7 || 7));
  return d.toISOString().slice(0, 10);
};
const plusDays = (n) => {
  const d = new Date(); d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

// ──────────────────────────────────────────────
// Stats (streak, accuracy, progress)
// ──────────────────────────────────────────────
async function statsFor(env, sub) {
  const daysRows = await env.DB.prepare(
    `SELECT DISTINCT date(created_at) d FROM attempts
     WHERE subscriber_id=? ORDER BY d DESC LIMIT 60`).bind(sub.id).all();
  let streak = 0;
  const today = new Date();
  for (const { d } of daysRows.results) {
    const expect = new Date(today); expect.setUTCDate(today.getUTCDate() - streak);
    if (d === expect.toISOString().slice(0, 10)) streak++;
    else if (streak === 0 && d === plusDays(-1)) { streak = 1; } // yesterday counts
    else break;
  }
  const acc = await env.DB.prepare(
    `SELECT COUNT(*) n, SUM(is_correct) ok FROM attempts
     WHERE subscriber_id=? AND created_at >= datetime('now','-30 days')`)
    .bind(sub.id).first();
  const plan = await env.DB.prepare(
    `SELECT days FROM plans WHERE plan_id=? AND plan_version=?`)
    .bind(sub.plan_id, sub.plan_version).first();
  return {
    streak_days: streak,
    accuracy_pct: acc?.n ? Math.round((acc.ok / acc.n) * 100) : 0,
    progress_pct: plan ? Math.min(100, Math.round(((sub.next_day - 1) / plan.days) * 100)) : 0,
  };
}

// ──────────────────────────────────────────────
// Email rendering (compact branded template; the full-fat
// pill-email.html lives in your ESP if you prefer templates there)
// ──────────────────────────────────────────────
function renderEmail(env, sub, pill, token, stats, planDays) {
  const q = JSON.parse(pill.question);
  // "exam_tips" is the DB column name for both schema versions — v1 plans
  // stored short tips there, v2 plans store the new exam_traps list; the
  // column itself was never renamed (see accounts-design-era commits).
  const traps  = JSON.parse(pill.exam_tips || "[]");
  const lesson = pill.concept || "";         // v1: 2-4 sentences · v2: 300-450 word lesson
  const quizUrl = (k) =>
    `${env.SITE_URL}/quiz.html?pill=${encodeURIComponent(pill.id)}&u=${token}` + (k ? `&a=${k}` : "");
  const choice = (c) => `
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
      <tr><td style="background:#FBFAF7;border:1px solid #D8D4C8;border-radius:8px;">
        <a href="${quizUrl(c.key)}" style="display:block;padding:13px 16px;font-family:Arial,sans-serif;font-size:15px;color:#13253A;text-decoration:none;">
          <span style="display:inline-block;width:24px;height:24px;line-height:24px;text-align:center;background:#13253A;color:#fff;border-radius:50%;font-weight:bold;font-size:13px;">${c.key}</span>
          &nbsp;&nbsp;${c.text}
        </a>
      </td></tr>
    </table>`;
  const pct = Math.round(((pill.day - 1) / planDays) * 100);

  return `<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F2F0EA;">
  <center><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F2F0EA;"><tr><td align="center" style="padding:28px 12px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;">
    <tr><td style="padding:0 8px 14px;font-family:Arial,sans-serif;font-size:18px;font-weight:800;color:#13253A;">
      DailyCharter<span style="color:#0E7C5B;">.</span></td></tr>
    <tr><td style="background:#fff;border:1px solid #D8D4C8;border-radius:12px;overflow:hidden;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td width="82%" height="5" style="background:#0E7C5B;font-size:0;">&nbsp;</td>
            <td width="18%" height="5" style="background:#FFE86B;font-size:0;">&nbsp;</td></tr>
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:16px 28px;border-bottom:1px dashed #D8D4C8;font-family:'Courier New',monospace;font-size:12px;color:#5B6B7C;">
        Pill ${String(pill.day).padStart(3, "0")} / ${planDays} · ${pill.topic}
        &nbsp;·&nbsp; 🔥 ${stats.streak_days}-day streak &nbsp;·&nbsp; ${pct}% done
      </td></tr>
      <tr><td style="padding:22px 28px 28px;">
        <p style="margin:0 0 6px;font-family:Arial,sans-serif;font-size:14px;color:#5B6B7C;">Good morning ${sub.first_name || "there"},</p>
        <h1 style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:22px;line-height:1.25;color:#13253A;">${pill.title}</h1>
        ${lesson.split(/\n\s*\n/).map((para) =>
          `<p style="margin:0 0 12px;font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#13253A;">${para.trim()}</p>`
        ).join("")}
        ${pill.formula ? `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 16px;"><tr>
          <td width="4" style="background:#0E7C5B;font-size:0;">&nbsp;</td>
          <td style="background:#F2F0EA;padding:14px 18px;" align="center"><span style="font-family:'Courier New',monospace;font-size:17px;font-weight:bold;color:#13253A;">${pill.formula}</span></td>
        </tr></table>` : ""}
        ${pill.worked_example ? `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #D8D4C8;border-radius:8px;margin:0 0 16px;overflow:hidden;"><tr>
          <td style="background:#F2F0EA;padding:6px 14px;font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#5B6B7C;">Worked example</td>
        </tr><tr><td style="padding:12px 16px;font-family:'Courier New',monospace;font-size:13px;line-height:1.6;color:#13253A;white-space:pre-wrap;">${pill.worked_example}</td>
        </tr></table>` : ""}
        ${traps.length ? `<p style="margin:14px 0 4px;font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#5B6B7C;">Exam traps</p>` : ""}
        ${traps.map((t, i) => `<p style="margin:0 0 6px;font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#13253A;"><b style="color:#0E7C5B;">${i + 1}.</b>&nbsp;${t}</p>`).join("")}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #D8D4C8;margin-top:18px;"><tr><td style="padding-top:20px;">
          <p style="margin:0 0 4px;font-family:'Courier New',monospace;font-size:11px;letter-spacing:1px;color:#0E7C5B;">✎ TEST YOURSELF · TAP YOUR ANSWER</p>
          <p style="margin:0 0 16px;font-family:Arial,sans-serif;font-size:15px;font-weight:bold;color:#13253A;">${q.stem}</p>
          ${q.choices.map(choice).join("")}
          <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;color:#5B6B7C;" align="center">
            Your tap feeds Sunday's recap. Prefer to peek?
            <a href="${quizUrl("")}" style="color:#0E7C5B;text-decoration:underline;">Open the question</a>.
          </p>
        </td></tr></table>
      </td></tr></table>
    </td></tr>
    <tr><td align="center" style="padding:24px 8px 8px;font-family:Arial,sans-serif;font-size:11px;line-height:1.7;color:#8A94A0;">
      © 2026 DailyCharter · Daily Charter S.L. · Calle García Treviño, 28023 Madrid, Spain<br>
      Original study content, not affiliated with CFA Institute.
      CFA® is a registered trademark owned by CFA Institute.<br>
      <a href="${env.SITE_URL}" style="color:#5B6B7C;">Website</a> ·
      <a href="${env.WORKER_URL || ""}/unsubscribe?u=${token}" style="color:#5B6B7C;">Unsubscribe</a>
    </td></tr>
  </table></td></tr></table></center></body></html>`;
}

// ──────────────────────────────────────────────
// ESP delivery (Resend-style API; swap sendEmail() for Postmark etc.)
// ──────────────────────────────────────────────
async function sendEmail(env, to, subject, html) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.ESP_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ from: env.FROM_EMAIL, to: [to], subject, html }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`ESP ${r.status}: ${JSON.stringify(body)}`);
  return body;   // { id: "…" } on success — logged by the caller for observability
}

// ──────────────────────────────────────────────
// CRON: the whole mail engine is this function
// ──────────────────────────────────────────────
async function runHourlySend(env, collectDetails) {
  const hour = new Date().getUTCHours();

  // THE JOIN — day-20-of-270 and day-1-of-365 users resolve identically:
  const due = await env.DB.prepare(
    `SELECT s.id sub_id, s.email, s.first_name, s.plan_id, s.plan_version,
            s.next_day, pl.days plan_days, p.*
     FROM subscribers s
     JOIN plans pl ON pl.plan_id = s.plan_id AND pl.plan_version = s.plan_version
     JOIN pills p  ON p.plan_id  = s.plan_id AND p.plan_version  = s.plan_version
                  AND p.day      = s.next_day
     WHERE s.status = 'active' AND s.send_hour_utc = ?`).bind(hour).all();

  let sent = 0, skipped = 0, failed = 0;
  const details = [];
  for (const row of due.results) {
    // 1) idempotency guard BEFORE the ESP call
    try {
      await env.DB.prepare(
        `INSERT INTO sends (subscriber_id, plan_id, day) VALUES (?,?,?)`)
        .bind(row.sub_id, row.plan_id, row.next_day).run();
    } catch { skipped++; continue; }               // already sent → skip

    // 2) render + send; 3) advance pointer only on success
    try {
      const sub = { id: row.sub_id, first_name: row.first_name,
                    plan_id: row.plan_id, plan_version: row.plan_version,
                    next_day: row.next_day };
      const token = await makeToken(env, row.sub_id);
      const stats = await statsFor(env, sub);
      const html  = renderEmail(env, sub, row, token, stats, row.plan_days);
      const esp   = await sendEmail(env, row.email,
        `Pill ${String(row.day).padStart(3, "0")}: ${row.title}`, html);
      console.log(`ESP accepted: to=${row.email} day=${row.next_day} esp_id=${esp.id || "?"}`);
      if (collectDetails) details.push({ email: row.email, day: row.next_day, esp });

      const done = row.next_day + 1 > row.plan_days;
      await env.DB.prepare(
        `UPDATE subscribers SET next_day = next_day + 1,
                status = CASE WHEN ? THEN 'completed' ELSE status END
         WHERE id = ?`).bind(done ? 1 : 0, row.sub_id).run();
      sent++;
    } catch (e) {
      // undo the send-log so tomorrow retries this same day
      await env.DB.prepare(
        `DELETE FROM sends WHERE subscriber_id=? AND plan_id=? AND day=?`)
        .bind(row.sub_id, row.plan_id, row.next_day).run();
      failed++;
      if (collectDetails) details.push({ email: row.email, day: row.next_day, error: e.message });
      console.error(`send failed for ${row.email}:`, e.message);
    }
  }
  console.log(`cron h${hour}: sent=${sent} skipped=${skipped} failed=${failed}`);
  return { hour, sent, skipped, failed, details };
}

// ──────────────────────────────────────────────
// Leitner update after an attempt  — spec §4
// ──────────────────────────────────────────────
async function updateLeitner(env, subId, pillId, correct) {
  if (!correct) {
    await env.DB.prepare(
      `INSERT INTO review_queue (subscriber_id, pill_id, box, due_date)
       VALUES (?,?,1,?)
       ON CONFLICT(subscriber_id, pill_id)
       DO UPDATE SET box = 1, due_date = excluded.due_date`)
      .bind(subId, pillId, nextSunday()).run();
    return;
  }
  const row = await env.DB.prepare(
    `SELECT box FROM review_queue WHERE subscriber_id=? AND pill_id=?`)
    .bind(subId, pillId).first();
  if (!row) return;                                   // never missed → no queue
  const box = Math.min(row.box + 1, 3);
  const due = box === 2 ? plusDays(14) : plusDays(45); // box3 ≈ pre-exam window
  await env.DB.prepare(
    `UPDATE review_queue SET box=?, due_date=? WHERE subscriber_id=? AND pill_id=?`)
    .bind(box, due, subId, pillId).run();
}

// ──────────────────────────────────────────────
// HTTP API
// ──────────────────────────────────────────────
async function handleFetch(req, env) {
  const url = new URL(req.url);
  const C = cors(env);
  if (req.method === "OPTIONS") return new Response(null, { headers: C });

  // ---- health ----
  if (url.pathname === "/health") return json({ ok: true }, 200, C);

  // ---- available plan lengths (site selector greys out unseeded ones) ----
  if (url.pathname === "/api/plans" && req.method === "GET") {
    const rows = await env.DB.prepare(`SELECT DISTINCT days FROM plans`).all();
    return json({ days: rows.results.map((r) => r.days) }, 200, C);
  }

  // ---- signup (from the website form / checkout success hook) ----
  if (url.pathname === "/api/subscribe" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    const r = await createSubscriber(env, {
      email: b.email, first_name: b.first_name, plan_days: b.plan_days, exam_date: b.exam_date,
    });
    if (r.error) return json({ error: r.error }, r.status, C);
    return json({ ok: true, token: await makeToken(env, r.id) }, 201, C);
  }

  // ---- signup with a password (extends /api/subscribe — accounts-design.md §3) ----
  if (url.pathname === "/api/signup" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    if (!b.password) return json({ error: "password required" }, 400, C);
    const r = await createSubscriber(env, {
      email: b.email, first_name: b.first_name, plan_days: b.plan_days,
      exam_date: b.exam_date, password: b.password,
    });
    if (r.error) return json({ error: r.error }, r.status, C);
    // Log the new account in immediately — no separate /api/login round trip.
    const sessionToken = newSessionToken();
    await env.DB.prepare(`INSERT INTO sessions (token, subscriber_id, expires_at) VALUES (?,?,?)`)
      .bind(sessionToken, r.id, sqliteDatetime(new Date(Date.now() + 30 * 86400000))).run();
    return json({ ok: true, token: await makeToken(env, r.id), session_token: sessionToken }, 201, C);
  }

  // ---- login: generic failure message always, rate-limited per email+IP ----
  if (url.pathname === "/api/login" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    const email = (b.email || "").toLowerCase().trim();
    const ip = req.headers.get("cf-connecting-ip") || "unknown";
    const key = `${email}|${ip}`;
    const recent = await env.DB.prepare(
      `SELECT COUNT(*) n FROM login_attempts WHERE attempt_key=? AND created_at >= datetime('now','-1 hour')`)
      .bind(key).first();
    if (recent.n >= 10)
      return json({ error: "Too many login attempts. Try again in an hour." }, 429, C);
    await env.DB.prepare(`INSERT INTO login_attempts (attempt_key) VALUES (?)`).bind(key).run();

    const invalid = () => json({ error: "Invalid email or password" }, 401, C);
    const sub = await env.DB.prepare(`SELECT * FROM subscribers WHERE email=?`).bind(email).first();
    if (!sub || !sub.password_hash) return invalid();
    if (!(await verifyPassword(b.password || "", sub.password_salt, sub.password_hash))) return invalid();

    const sessionToken = newSessionToken();
    await env.DB.prepare(`INSERT INTO sessions (token, subscriber_id, expires_at) VALUES (?,?,?)`)
      .bind(sessionToken, sub.id, sqliteDatetime(new Date(Date.now() + 30 * 86400000))).run();
    return json({ session_token: sessionToken }, 200, C);
  }

  // ---- logout ----
  if (url.pathname === "/api/logout" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    if (b.session_token) await env.DB.prepare(`DELETE FROM sessions WHERE token=?`).bind(b.session_token).run();
    return json({ ok: true }, 200, C);
  }

  // ---- account portal ----
  if (url.pathname === "/api/account" && req.method === "GET") {
    const sub = await sessionSubscriberByToken(env, bearerToken(req));
    if (!sub) return json({ error: "invalid or expired session" }, 401, C);
    const plan = await env.DB.prepare(`SELECT days FROM plans WHERE plan_id=? AND plan_version=?`)
      .bind(sub.plan_id, sub.plan_version).first();
    return json({
      email: sub.email, first_name: sub.first_name, plan_id: sub.plan_id,
      plan_days: plan?.days ?? null, next_day: sub.next_day, status: sub.status,
      progress_pct: plan ? Math.min(100, Math.round(((sub.next_day - 1) / plan.days) * 100)) : 0,
      stats: await statsFor(env, sub),
    }, 200, C);
  }

  // ---- plan-switch preview: both concrete outcomes before the user picks ----
  if (url.pathname === "/api/account/plan-options" && req.method === "GET") {
    const sub = await sessionSubscriberByToken(env, bearerToken(req));
    if (!sub) return json({ error: "invalid or expired session" }, 401, C);
    const newPlanId = `L1-${parseInt(url.searchParams.get("new_plan_days"))}`;
    const newPlan = await env.DB.prepare(
      `SELECT days FROM plans WHERE plan_id=? ORDER BY plan_version DESC LIMIT 1`)
      .bind(newPlanId).first();
    if (!newPlan) return json({ error: "This plan length isn't available yet" }, 404, C);
    const curPlan = await env.DB.prepare(`SELECT days FROM plans WHERE plan_id=? AND plan_version=?`)
      .bind(sub.plan_id, sub.plan_version).first();
    const resumeDay = await resolveResumeDay(
      env, sub.plan_id, sub.next_day, newPlanId, curPlan.days, newPlan.days);
    return json({
      current: { plan_id: sub.plan_id, day: sub.next_day, days: curPlan.days },
      restart: { plan_id: newPlanId, day: 1, days: newPlan.days },
      resume: { plan_id: newPlanId, day: resumeDay, days: newPlan.days },
    }, 200, C);
  }

  // ---- change plan: restart at day 1, or resume via plan_equivalence ----
  if (url.pathname === "/api/account/change-plan" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    const sub = await sessionSubscriberByToken(env, b.session_token);
    if (!sub) return json({ error: "invalid or expired session" }, 401, C);
    if (!["restart", "resume"].includes(b.mode))
      return json({ error: "mode must be 'restart' or 'resume'" }, 400, C);
    const newPlanId = `L1-${parseInt(b.new_plan_days)}`;
    const newPlan = await env.DB.prepare(
      `SELECT plan_version, days FROM plans WHERE plan_id=? ORDER BY plan_version DESC LIMIT 1`)
      .bind(newPlanId).first();
    if (!newPlan) return json({ error: "This plan length isn't available yet" }, 404, C);

    let newDay = 1;
    if (b.mode === "resume") {
      const curPlan = await env.DB.prepare(`SELECT days FROM plans WHERE plan_id=? AND plan_version=?`)
        .bind(sub.plan_id, sub.plan_version).first();
      newDay = await resolveResumeDay(env, sub.plan_id, sub.next_day, newPlanId, curPlan.days, newPlan.days);
    }
    await env.DB.prepare(
      `UPDATE subscribers SET plan_id=?, plan_version=?, next_day=?, status='active' WHERE id=?`)
      .bind(newPlanId, newPlan.plan_version, newDay, sub.id).run();
    return json({ ok: true, plan_id: newPlanId, next_day: newDay }, 200, C);
  }

  // ---- cancel (same effect as the email unsubscribe link) ----
  if (url.pathname === "/api/account/cancel" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    const sub = await sessionSubscriberByToken(env, b.session_token);
    if (!sub) return json({ error: "invalid or expired session" }, 401, C);
    await env.DB.prepare(`UPDATE subscribers SET status='cancelled' WHERE id=?`).bind(sub.id).run();
    return json({ ok: true }, 200, C);
  }

  // ---- change password (bootstraps one if the account never set one) ----
  if (url.pathname === "/api/account/password" && req.method === "POST") {
    const b = await req.json().catch(() => ({}));
    const sub = await sessionSubscriberByToken(env, b.session_token);
    if (!sub) return json({ error: "invalid or expired session" }, 401, C);
    if (!b.new_password || b.new_password.length < 8)
      return json({ error: "New password must be at least 8 characters" }, 400, C);
    if (sub.password_hash) {
      if (!(await verifyPassword(b.current_password || "", sub.password_salt, sub.password_hash)))
        return json({ error: "Current password is incorrect" }, 401, C);
    }
    const salt = crypto.randomUUID();
    const hash = await hashPassword(b.new_password, salt);
    await env.DB.prepare(`UPDATE subscribers SET password_hash=?, password_salt=? WHERE id=?`)
      .bind(hash, salt, sub.id).run();
    return json({ ok: true }, 200, C);
  }

  // ---- admin: manually run the hourly send against THIS deployed Worker's
  // real secrets/D1 (wrangler dev can't use real secrets — they're write-only
  // once set via `wrangler secret put`) — same code path as the real cron,
  // returns the ESP response per subscriber sent for fire-test verification ----
  if (url.pathname === "/api/admin/run-cron" && req.method === "POST") {
    if (!timingSafeEqual(bearerToken(req) || "", env.ADMIN_TOKEN || ""))
      return json({ error: "unauthorized" }, 401, C);
    return json(await runHourlySend(env, true), 200, C);
  }

  // ---- admin: read-only, single shared long-lived token (§6) ----
  if (url.pathname === "/api/admin/subscribers" && req.method === "GET") {
    if (!timingSafeEqual(bearerToken(req) || "", env.ADMIN_TOKEN || ""))
      return json({ error: "unauthorized" }, 401, C);
    const limit = Math.min(parseInt(url.searchParams.get("limit")) || 50, 200);
    const offset = Math.max(parseInt(url.searchParams.get("offset")) || 0, 0);
    const rows = await env.DB.prepare(
      `SELECT email, plan_id, next_day, status, created_at FROM subscribers
       ORDER BY created_at DESC LIMIT ? OFFSET ?`).bind(limit, offset).all();
    const total = await env.DB.prepare(`SELECT COUNT(*) n FROM subscribers`).first();
    return json({ subscribers: rows.results, total: total.n, limit, offset }, 200, C);
  }

  // Everything below needs a valid token
  const token = url.searchParams.get("token") || url.searchParams.get("u") ||
                (req.method === "POST" ? (await req.clone().json().catch(() => ({}))).token : null);
  const subId = await verifyToken(env, token);

  // ---- question payload for quiz.html (correct_key NEVER leaves here) ----
  if (url.pathname === "/api/question" && req.method === "GET") {
    if (!subId) return json({ error: "invalid token" }, 401, C);
    const pill = await env.DB.prepare(`SELECT * FROM pills WHERE id=?`)
      .bind(url.searchParams.get("pill_id")).first();
    if (!pill) return json({ error: "pill not found" }, 404, C);
    const plan = await env.DB.prepare(
      `SELECT days FROM plans WHERE plan_id=? AND plan_version=?`)
      .bind(pill.plan_id, pill.plan_version).first();
    const q = JSON.parse(pill.question);
    return json({
      pill_id: pill.id,
      label: `Pill ${String(pill.day).padStart(3, "0")} / ${plan?.days ?? "?"} · ${pill.topic}`,
      stem: q.stem,
      choices: q.choices.map((c) => ({ key: c.key, text: c.text })),   // no why/correct
    }, 200, C);
  }

  // ---- record an attempt (the only write in the quiz flow) ----
  if (url.pathname === "/api/attempts" && req.method === "POST") {
    if (!subId) return json({ error: "invalid token" }, 401, C);
    const b = await req.json().catch(() => ({}));
    const pill = await env.DB.prepare(`SELECT * FROM pills WHERE id=?`)
      .bind(b.pill_id).first();
    if (!pill || !["A", "B", "C"].includes(b.choice))
      return json({ error: "bad pill_id or choice" }, 400, C);

    const q = JSON.parse(pill.question);
    const correct = b.choice === q.correct_key;
    try {
      await env.DB.prepare(
        `INSERT INTO attempts (id, subscriber_id, pill_id, choice, is_correct, source)
         VALUES (?,?,?,?,?,?)`)
        .bind(crypto.randomUUID(), subId, pill.id, b.choice,
              correct ? 1 : 0, b.source || "web").run();
      await updateLeitner(env, subId, pill.id, correct);
    } catch { /* uniq_attempt_day hit → already answered today: return stored verdict */ }

    const sub = await env.DB.prepare(`SELECT * FROM subscribers WHERE id=?`)
      .bind(subId).first();
    return json({
      correct, correct_key: q.correct_key, picked: b.choice,
      explanations: Object.fromEntries(q.choices.map((c) => [c.key, c.why])),
      stats: await statsFor(env, sub),
    }, 200, C);
  }

  // ---- next due review question (bonus button) ----
  if (url.pathname === "/api/review-next" && req.method === "GET") {
    if (!subId) return json({ error: "invalid token" }, 401, C);
    const row = await env.DB.prepare(
      `SELECT p.* FROM review_queue r JOIN pills p ON p.id = r.pill_id
       WHERE r.subscriber_id=? AND r.due_date <= date('now')
       ORDER BY r.box ASC, r.due_date ASC LIMIT 1`).bind(subId).first();
    if (!row) return new Response(null, { status: 204, headers: C });
    const q = JSON.parse(row.question);
    return json({
      pill_id: row.id,
      label: `Review · Pill ${String(row.day).padStart(3, "0")} · ${row.topic}`,
      stem: q.stem,
      choices: q.choices.map((c) => ({ key: c.key, text: c.text })),
    }, 200, C);
  }

  // ---- unsubscribe: GET shows confirm page (GET never writes), POST cancels ----
  if (url.pathname === "/unsubscribe") {
    if (req.method === "GET") {
      return new Response(
        `<!DOCTYPE html><html><body style="font-family:Arial;background:#FBFAF7;color:#13253A;text-align:center;padding:70px 20px;">
         <h2>Unsubscribe from DailyCharter?</h2>
         <p style="color:#5B6B7C">You keep every pill already delivered. This stops future ones.</p>
         <form method="POST" action="/unsubscribe?u=${encodeURIComponent(token || "")}">
           <button style="background:#13253A;color:#fff;border:0;border-radius:6px;padding:13px 26px;font-weight:bold;cursor:pointer">Yes, unsubscribe me</button>
         </form></body></html>`,
        { headers: { "Content-Type": "text/html" } });
    }
    if (req.method === "POST") {
      if (!subId) return json({ error: "invalid token" }, 401);
      await env.DB.prepare(`UPDATE subscribers SET status='cancelled' WHERE id=?`)
        .bind(subId).run();
      return new Response(
        `<!DOCTYPE html><html><body style="font-family:Arial;background:#FBFAF7;color:#13253A;text-align:center;padding:70px 20px;">
         <h2>Done — no more emails.</h2><p style="color:#5B6B7C">Good luck on exam day. You've got this.</p></body></html>`,
        { headers: { "Content-Type": "text/html" } });
    }
  }

  return json({ error: "not found" }, 404, C);
}

export default {
  fetch: (req, env) => handleFetch(req, env),
  scheduled: (event, env, ctx) => ctx.waitUntil(runHourlySend(env)),
};

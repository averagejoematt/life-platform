/*
  evidence_shared.js — small pure helpers shared by every /data/, /protocols/ and
  /method/ renderer (escaping, formatting, fetch-and-tolerate-failure, the fig/figs/sec
  HTML micro-builders). Split out of evidence.js (#581) — no behavior change.
*/

export const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }

export async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }

// Reader-participation switch-on (2026-07): the sanctioned POST write surface
// (votes/follows/checkins/suggestions/findings, all DDB-rate-limited server-side,
// see CLAUDE.md "Site API is primarily read-only"). One shared fetch wrapper so
// every write control handles the 429/5xx/network-fail states the same honest way
// instead of three near-duplicate try/catches.
export async function postJSON(path, body) {
  try {
    const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    let data = null;
    try { data = await r.json(); } catch (e) { /* no body */ }
    return { ok: r.ok, status: r.status, data: data || {} };
  } catch (e) {
    return { ok: false, status: 0, data: {} };
  }
}

export const isBad = (v) => { if (v == null) return true; const s = String(v).trim(); return s === "" || /^\[.*\]$/.test(s) || s.toUpperCase() === "N/A"; };

export const has = (v) => v != null && v !== "" && !(Array.isArray(v) && !v.length);

export function fmt(v, d) { if (v == null || v === "") return "—"; const n = Number(v); return Number.isFinite(n) && typeof v !== "boolean" ? (d != null ? n.toFixed(d) : (Number.isInteger(n) ? String(n) : n.toFixed(1))) : esc(v); }

export const ttl = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Sleep/recovery are wake-date-keyed: a record dated D describes the night of D-1.
// Returns a short "Jun 16" label for the night a wake-date reading came from.
export const _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const fmtShort = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_MON[+m[2] - 1]} ${+m[3]}` : ""; };

// Sleep/recovery are wake-date-keyed: a record dated D describes the night of D-1.
// Returns a short "Jun 16" label for the night a wake-date reading came from.
export function nightOf(wakeIso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(wakeIso || ""));
  if (!m) return "";
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  d.setUTCDate(d.getUTCDate() - 1);
  return `${_MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

// The night a sleep readout came from: the unified record already exposes night_of
// (the evening date); otherwise derive it from the sleep-detail wake date.
export const lastNightDate = (s, uni) => (uni && uni.night_of) ? fmtShort(uni.night_of) : nightOf(s && s.as_of_date);

// #491/M-5: today/yesterday in the experiment's timezone (PT) — used to
// date-condition recency labels so an 8-day-old weigh-in is never "today".
export const todayPT = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });

export const dayBefore = (iso) => { const t = Date.parse(String(iso || "").slice(0, 10)); return Number.isFinite(t) ? new Date(t - 86400000).toISOString().slice(0, 10) : ""; };

// `method` (optional, 4th arg) is a methods-registry key (#544) — when present it tags the
// tile with data-method so provenance_popover.js can attach a code-drawn "how is this
// computed?" popover fed straight from /api/methods (never hand-written formula text).
export const fig = (v, k, extra, method) => `<div class="fig"${method ? ` data-method="${esc(method)}"` : ""}><span class="fig-v num">${esc(v)}</span><span class="fig-k label">${esc(k)}</span>${extra ? `<span class="rd-delta">${esc(extra)}</span>` : ""}</div>`;

export const figs = (a) => `<div class="figs">${a.filter(Boolean).join("")}</div>`;

export const sec = (t, inner) => inner ? `<section class="rd-sec"><h2 class="rd-h">${esc(t)}</h2>${inner}</section>` : "";

export const empty = (m) => `<p class="rd-archive">${esc(m)}</p>`;

// #1371: the "warming up" grammar — hollow marks filling toward an instrument's
// real arming threshold. current/threshold are the engine's OWN numbers (served in
// the API's gates block), never authored. Renders nothing without a real threshold;
// an unmeasurable current renders all-hollow with an honest "—", never a fake 0.
export function warmup(current, threshold, label) {
  const t = Number(threshold);
  if (!Number.isFinite(t) || t <= 0) return "";
  const cur = current != null && Number.isFinite(Number(current)) ? Math.max(0, Math.min(Number(current), t)) : null;
  const marks = Math.min(t, 12); // cap the row — each mark stands for t/marks days
  const litMarks = cur == null ? 0 : Math.floor((cur / t) * marks);
  let dots = "";
  for (let i = 0; i < marks; i++) dots += `<span class="wu-dot${i < litMarks ? " lit" : ""}" aria-hidden="true"></span>`;
  const progress = `${cur == null ? "—" : fmt(cur)}/${fmt(t)}`;
  return `<p class="warmup" role="img" aria-label="${esc(label)}: ${esc(progress)}">` +
    `<span class="wu-marks">${dots}</span><span class="wu-label label">${esc(label)} · ${esc(progress)}</span></p>`;
}

export const note = (t) => `<p class="correlative">${t} <span class="confidence conf-low">N=1</span></p>`;

export function evClass(ev) { const s = String(ev || "").toLowerCase(); if (/strong|high|robust/.test(s)) return ["backed-strong", "well supported"]; if (/mod|some|emerg|mixed/.test(s)) return ["backed-some", "moderate support"]; return ["backed-thin", "preliminary"]; }

// Render one value for a kv row. Handles nested objects (compact "k v · k v" of their
// scalar children) + arrays (count) — previously these fell through to "—", which turned
// nutrition periodization / eating-window and the genome category tables into walls of dashes.
export function kvval(v, f, k) {
  if (v == null) return "—";
  if (f && f[k]) return f[k](v);
  if (Array.isArray(v)) return v.length ? `${v.length} item${v.length > 1 ? "s" : ""}` : "—";
  if (typeof v === "object") {
    if (v.summary || v.label || v.value) return v.summary || v.label || v.value;
    const inner = Object.entries(v).filter(([ik, iv]) => !ik.startsWith("_") && iv != null && typeof iv !== "object").map(([ik, iv]) => `${ttl(ik)} ${fmt(iv)}`);
    return inner.length ? inner.join(" · ") : "—";
  }
  return fmt(v);
}

export function kvtable(o, f) {
  // Drop rows whose value renders empty ("—") so nested-null objects don't leave dash rows.
  const r = Object.entries(o || {}).filter(([k, v]) => !k.startsWith("_") && v != null).map(([k, v]) => [k, kvval(v, f, k)]).filter(([, val]) => val !== "—").map(([k, val]) => `<tr><td class="rd-name">${esc(ttl(k))}</td><td class="num">${esc(val)}</td></tr>`).join("");
  return r ? `<table class="rd-tbl"><tbody>${r}</tbody></table>` : "";
}

/* ── Reader participation controls — switch-on (2026-07) ──────────────────────
   The catalog/library vote+follow markup + wiring is identical shape on the
   Challenges and Experiments pages (both back onto sibling endpoint pairs:
   challenge_vote/challenge_follow, experiment_vote/experiment_follow) — one
   pair of helpers, two call sites. Honest by construction: a real 0 renders as
   "0 votes", never hidden or padded; every write is server rate-limited so the
   worst a reader can do is see "already voted" or a 500. */

// One card's vote button + follow toggle+form. `count` may be null (unknown —
// e.g. the votes endpoint didn't load); render "—" rather than fake a number.
export function voteFollowRow(endpointBase, idKey, id, count) {
  const shown = count == null ? "—" : String(count);
  return `<div class="part-row">` +
    `<button class="part-btn" type="button" data-vote-btn data-endpoint="/api/${esc(endpointBase)}_vote" data-idkey="${esc(idKey)}" data-id="${esc(id)}">Vote for this <span class="part-count" data-vote-count>${esc(shown)}</span></button>` +
    `<button class="part-btn" type="button" data-follow-btn data-endpoint="/api/${esc(endpointBase)}_follow" data-idkey="${esc(idKey)}" data-id="${esc(id)}">Notify me</button>` +
    `</div><p class="part-msg" data-vote-msg></p>` +
    `<form class="part-form" data-follow-form hidden><label class="label" for="fe-${esc(id)}">Email</label>` +
    `<input id="fe-${esc(id)}" type="email" placeholder="you@example.com" data-follow-email maxlength="200" autocomplete="email">` +
    `<button class="part-btn" type="submit" data-follow-submit>Follow</button><p class="part-msg" data-follow-msg></p></form>`;
}

export function wireVoteButtons(root = document) {
  root.querySelectorAll("[data-vote-btn]").forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = 1;
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      const { endpoint, idkey, id } = btn.dataset;
      const card = btn.closest("article") || btn.parentElement;
      const msgEl = card ? card.querySelector("[data-vote-msg]") : null;
      const countEl = btn.querySelector("[data-vote-count]");
      const { ok, status, data } = await postJSON(endpoint, { [idkey]: id });
      if (ok) {
        if (countEl && data && data.new_count != null) countEl.textContent = String(data.new_count);
        btn.classList.add("is-done");
        if (msgEl) { msgEl.textContent = "Thanks — your vote's counted."; msgEl.classList.remove("is-error"); }
      } else {
        btn.disabled = false;
        const fallback = status === 429 ? "Already voted for this in the last 24 hours." : "Couldn't record that vote — try again.";
        if (msgEl) { msgEl.textContent = (data && data.error) || fallback; msgEl.classList.add("is-error"); }
      }
    });
  });
}

export function wireFollowForms(root = document) {
  root.querySelectorAll("[data-follow-btn]").forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = 1;
    btn.addEventListener("click", () => {
      const card = btn.closest("article") || btn.parentElement;
      const form = card ? card.querySelector("[data-follow-form]") : null;
      if (form) { form.hidden = !form.hidden; if (!form.hidden) form.querySelector("[data-follow-email]").focus(); }
    });
  });
  root.querySelectorAll("[data-follow-form]").forEach((form) => {
    if (form.__wired) return;
    form.__wired = 1;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const card = form.closest("article");
      const voteBtn = card ? card.querySelector("[data-vote-btn]") : null;
      const followBtn = card ? card.querySelector("[data-follow-btn]") : null;
      const emailIn = form.querySelector("[data-follow-email]");
      const msgEl = form.querySelector("[data-follow-msg]");
      const submitBtn = form.querySelector("[data-follow-submit]");
      const email = emailIn ? emailIn.value.trim() : "";
      if (!email || !email.includes("@")) {
        if (msgEl) { msgEl.textContent = "Enter a valid email."; msgEl.classList.add("is-error"); }
        return;
      }
      const endpoint = (followBtn || voteBtn).dataset.endpoint;
      const idkey = (followBtn || voteBtn).dataset.idkey;
      const id = (followBtn || voteBtn).dataset.id;
      submitBtn.disabled = true;
      const { ok, data } = await postJSON(endpoint, { email, [idkey]: id });
      submitBtn.disabled = false;
      if (ok) {
        if (msgEl) { msgEl.textContent = data.already_following ? "Already on the list." : "You're in — an email lands when it launches."; msgEl.classList.remove("is-error"); }
        emailIn.value = "";
      } else if (msgEl) {
        msgEl.textContent = (data && data.error) || "Couldn't save that — try again.";
        msgEl.classList.add("is-error");
      }
    });
  });
}

/* ── Renderers (bound to real shapes) ─────────────────────────────────────── */

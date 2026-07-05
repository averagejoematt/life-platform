/*
  evidence_shared.js — small pure helpers shared by every /data/, /protocols/ and
  /method/ renderer (escaping, formatting, fetch-and-tolerate-failure, the fig/figs/sec
  HTML micro-builders). Split out of evidence.js (#581) — no behavior change.
*/

export const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }

export async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }

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

export const fig = (v, k, extra) => `<div class="fig"><span class="fig-v num">${esc(v)}</span><span class="fig-k label">${esc(k)}</span>${extra ? `<span class="rd-delta">${esc(extra)}</span>` : ""}</div>`;

export const figs = (a) => `<div class="figs">${a.filter(Boolean).join("")}</div>`;

export const sec = (t, inner) => inner ? `<section class="rd-sec"><h2 class="rd-h">${esc(t)}</h2>${inner}</section>` : "";

export const empty = (m) => `<p class="rd-archive">${esc(m)}</p>`;

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

/* ── Renderers (bound to real shapes) ─────────────────────────────────────── */

// v7_today.js — the v7 "Today" page (#4182, plan §2a row 2; CONCEPT §3 row 2).
//
// Matthew's morning screen, open to anyone. The three questions are three_questions.js
// mounted alone — the red team's 9/10 block, reused unchanged: How's the week? (the
// snapshot's journey), Last night? (its vitals), Today? (the routine's session as it is
// served — kind and counts — plus the food log). Then the one ask with its lateness
// (#4219, "7 days late" printed, never a stale ask posing as today's), what he skips in
// ONE vocabulary (absence_read.js's words for the dark areas of his life, the same words
// for the dark channels and the paused device in /api/source_freshness), a one-line note
// that this is his screen, and the dated return line. Nothing after it.
//
// The exercises and loads are deliberately NOT served by /api/routine (an owner privacy
// ruling on publishing loads comes first — plan E3); until /api/session exists the page
// says so, honestly, instead of inventing a list.
//
// The pure helpers are exported and unit-tested (tests/js/v7_today.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from.
import { weekLine, nightLine, sessionLine, proteinLine, askLine, unwrap } from "/assets/js/three_questions.js";
import { absenceLine, isDark } from "/assets/js/absence_read.js";
import { dayInWords, dayLabel, dataThrough, daysOverdue } from "/assets/js/entry_age.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const utcNoon = (d) => Date.parse(`${iso(d)}T12:00:00Z`);
const num = (x) => {
  if (x == null || x === "" || typeof x === "boolean") return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
};

/** The margin of an entry, from a served date: { d: "26", mo: "Sep", w: "Saturday" }. Null when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Sat Sep 26"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

/** YYYY-MM-DD plus n days. "" when unusable. */
export function plusDays(dateStr, n) {
  if (!isIso(dateStr)) return "";
  return new Date(utcNoon(dateStr) + n * 86400000).toISOString().slice(0, 10);
}

/** Whole days from `a` to `b` (both YYYY-MM-DD), UTC-noon pinned. Null when unusable. */
export function daysBetween(a, b) {
  if (!isIso(a) || !isIso(b)) return null;
  return Math.round((utcNoon(b) - utcNoon(a)) / 86400000);
}

/** The latest of the served data dates this page prints (the vitals' day, the last weigh-in,
 *  the food log's latest day) — a comparison, not a computation. "" when none is usable. */
export function throughDate({ journey, vitals, nutrition } = {}) {
  const n = unwrap(nutrition, "nutrition");
  const dates = [vitals && vitals.as_of_date, journey && journey.last_weighin_date, n && n.latest_date].map(iso).filter(isIso).sort();
  return dates.length ? dates[dates.length - 1] : "";
}

/** The ask askLine() will print — the first current one, else the first (its own rule, #4219). Null when none. */
export function chosenAsk(dash, now = new Date()) {
  const bad = (v) => v == null || /^\s*$|^n\/a$|^\[.*\]$/i.test(String(v));
  const list = (dash && Array.isArray(dash.open_actions) ? dash.open_actions : []).filter((x) => x && !bad(x.text));
  if (!list.length) return null;
  const lateBy = list.map((x) => daysOverdue(x, now) || 0);
  const cur = lateBy.findIndex((d) => d === 0);
  return list[cur >= 0 ? cur : 0];
}

/** The ask's line under its own heading: askLine's HTML with the "The one ask:" key dropped
 *  (the heading says it). "" when there is no ask. */
export function askBody(dash, now = new Date()) {
  return askLine(dash, now).replace(/^<span class="tq-ask-k">[^<]*<\/span>\s*/, "");
}

/** The session's loads, IF /api/session serves them: [{name, sets, reps, load}] rows from an
 *  `exercises[]` list. Null when the endpoint is absent or carries no list — the page then
 *  says the loads are on his phone, never a guessed list. */
export function loadRows(session) {
  const ex = session && Array.isArray(session.exercises) ? session.exercises : null;
  if (!ex || !ex.length) return null;
  const rows = ex
    .filter((e) => e && e.name)
    .map((e) => {
      const sets = num(e.sets), reps = num(e.reps), load = num(e.load_lbs != null ? e.load_lbs : e.load);
      const dose = [sets != null && reps != null ? `${sets} × ${reps}` : sets != null ? `${sets} sets` : "", load != null ? `${load} lb` : ""].filter(Boolean).join(" · ");
      return { name: String(e.name), dose };
    });
  return rows.length ? rows : null;
}

// The seven scored areas of his life, in a reader's words (the pillar name is an engine key).
const AREA = {
  sleep: "sleep",
  movement: "training",
  nutrition: "the food log",
  metabolic: "blood sugar",
  mind: "the journal",
  relationships: "relationships",
  consistency: "the habit list",
};
// The phone's manual channels, in a reader's words (the served label is the engine's).
const CHANNEL = { cgm: "the blood-sugar sensor", blood_pressure: "the blood-pressure cuff", state_of_mind: "the mood check-in" };

/** What he skips, counted, in one vocabulary: the dark areas (absence_read.js's own words,
 *  from `snapshot.character.pillars[].absence`), the dark channels on his phone
 *  (`source_freshness.sources[].datatypes[]`), the stale and paused sources. Each row:
 *  { key, label, text, days, src }. Empty when nothing is dark. */
export function skipsList({ pillars, freshness } = {}) {
  const out = [];
  const seen = new Set();
  const push = (row) => {
    if (row.key && seen.has(row.key)) return;
    seen.add(row.key);
    out.push(row);
  };
  for (const p of Array.isArray(pillars) ? pillars : []) {
    if (!p || !isDark(p)) continue;
    const a = p.absence || {};
    const days = num(a.days_since_last_log) != null ? num(a.days_since_last_log) : num(a.days_dark);
    push({ key: `area:${p.name}`, label: AREA[p.name] || String(p.name || "").replace(/_/g, " "), text: absenceLine(p, { short: true }) || "nothing logged", days, src: `api_snapshot.character.pillars[${p.name}].absence` });
  }
  const f = freshness || {};
  const today = iso(f.pacific_today);
  const sources = Array.isArray(f.sources) ? f.sources : [];
  for (const s of sources) {
    for (const d of Array.isArray(s.datatypes) ? s.datatypes : []) {
      if (!d || !d.dark) continue;
      const days = num(d.age_days) != null ? Math.round(num(d.age_days)) : daysBetween(d.last_seen, today);
      push({ key: `channel:${d.key}`, label: CHANNEL[d.key] || String(d.label || d.key || ""), text: days != null ? `nothing logged for ${days} day${days === 1 ? "" : "s"}` : "nothing logged", days, src: `api_source_freshness.sources[${s.id}].datatypes[${d.key}]` });
    }
  }
  for (const s of sources) {
    const st = String(s.status || "");
    if (st === "paused") {
      const days = daysBetween(s.last_update, today);
      push({ key: `source:${s.id}`, label: String(s.label || s.id), text: `paused by the site, not by him${days != null ? ` — nothing logged for ${days} days` : ""}`, days, src: `api_source_freshness.sources[${s.id}]` });
    } else if (/stale/.test(st)) {
      const days = num(s.age_hours) != null ? Math.round(num(s.age_hours) / 24) : daysBetween(s.last_update, today);
      push({ key: `source:${s.id}`, label: String(s.label || s.id), text: days != null ? `nothing logged for ${days} day${days === 1 ? "" : "s"}` : "nothing logged", days, src: `api_source_freshness.sources[${s.id}]` });
    }
  }
  return out;
}

/** The dated return line: rewritten every morning; the next weigh-in from the last one plus a day. */
export function returnLine(journey) {
  const nw = plusDays(journey && journey.last_weighin_date, 1);
  const w = dayInWords(nw);
  return { date: nw, text: w ? `Rewritten every morning. The next weigh-in is due ${w}.` : "Rewritten every morning." };
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
}

function fill(section, html) {
  if (!section) return;
  const body = section.querySelector(".td-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

const NOT_SERVED = '<p class="td-note">Not served this morning.</p>';

function renderWeek(journey) {
  const sec = document.getElementById("td-week");
  const line = weekLine(journey);
  fill(sec, line ? `<p class="td-a" data-src="api_snapshot.journey">${line}</p>` : NOT_SERVED);
  if (journey) setMargin(sec, journey.last_weighin_date);
}

function renderNight(vitals) {
  const sec = document.getElementById("td-night");
  const line = nightLine(vitals);
  fill(sec, line ? `<p class="td-a" data-src="api_snapshot.vitals">${line}</p>` : NOT_SERVED);
  if (vitals) setMargin(sec, vitals.night_of || vitals.as_of_date);
}

function renderToday({ rt, nut, session }) {
  const sec = document.getElementById("td-today");
  const bits = [];
  const s = sessionLine(rt);
  if (s) bits.push(`<p class="td-a" data-src="api_routine.routine">${s}</p>`);
  const rows = loadRows(session);
  if (rows) {
    bits.push(`<table class="td-loads" data-src="api_session.exercises"><tbody>${rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="n">${esc(r.dose)}</td></tr>`).join("")}</tbody></table>`);
  } else if (s) {
    bits.push('<p class="td-note">The exercises and the loads are on his phone; the site doesn’t publish them yet.</p>');
  }
  const p = proteinLine(nut);
  if (p) bits.push(`<p class="td-a" data-src="api_nutrition_overview.nutrition">${p}</p>`);
  fill(sec, bits.length ? bits.join("") : NOT_SERVED);
  const r = rt && rt.routine;
  setMargin(sec, (r && r.target_date) || (rt && rt.as_of_date) || (unwrap(nut, "nutrition") || {}).latest_date);
}

function renderAsk(dash, now) {
  const sec = document.getElementById("td-ask");
  const line = askBody(dash, now);
  if (!line) return fill(sec, '<p class="td-note" data-src="api_coaching-dashboard.open_actions">No open ask from a coach this morning.</p>');
  fill(sec, `<p class="td-a" data-src="api_coaching-dashboard.open_actions[]">${line}</p>`);
  const a = chosenAsk(dash, now);
  if (a) setMargin(sec, a.due || a.asked_on);
}

function renderSkips({ pillars, freshness }) {
  const sec = document.getElementById("td-skips");
  const rows = skipsList({ pillars, freshness });
  if (!rows.length) return fill(sec, '<p class="td-note" data-src="api_source_freshness.sources">Nothing skipped: every wired-in source reported inside its own window.</p>');
  fill(sec, `<ul class="td-skips">${rows.map((r) => `<li data-src="${esc(r.src)}"><b>${esc(r.label)}</b> — ${esc(r.text)}</li>`).join("")}</ul>`);
  if (freshness) setMargin(sec, freshness.pacific_today);
}

function renderReturn(journey) {
  const sec = document.getElementById("td-return");
  const el = document.getElementById("td-return-line");
  const r = returnLine(journey);
  if (el) {
    el.textContent = r.text;
    el.classList.remove("td-pending");
    el.setAttribute("data-src", "api_snapshot.journey.last_weighin_date + 1 day");
  }
  if (r.date) setMargin(sec, r.date);
}

async function getJSON(p) {
  try {
    const r = await fetch(p, { headers: { accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

async function main() {
  const [snap, rt, nut, dash, fresh, session] = await Promise.all([
    getJSON("/api/snapshot"),
    getJSON("/api/routine"),
    getJSON("/api/nutrition_overview"),
    getJSON("/api/coaching-dashboard"),
    getJSON("/api/source_freshness"),
    getJSON("/api/session"), // plan E3 — absent today; a 404 is the honest branch
  ]);
  const journey = snap ? unwrap(snap.journey, "journey") : null;
  const vitals = snap ? unwrap(snap.vitals, "vitals") : null;
  const character = snap ? unwrap(snap.character, "character") : null;
  const pillars = (snap && snap.character && snap.character.pillars) || (character && character.pillars) || [];
  const thr = document.getElementById("td-through");
  if (thr) thr.textContent = dataThrough(throughDate({ journey, vitals, nutrition: nut }));
  const now = new Date();
  renderWeek(journey);
  renderNight(vitals);
  renderToday({ rt, nut, session });
  renderAsk(dash, now);
  renderSkips({ pillars, freshness: fresh });
  renderReturn(journey);
}

if (typeof document !== "undefined" && document.getElementById("td-week")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}

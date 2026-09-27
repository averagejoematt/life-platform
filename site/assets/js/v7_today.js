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
// The exercises and loads come from /api/session (plan E3, #4318; owner ruling 2026-09-26:
// loads are public): names, sets × reps exactly as served (a range string "8–12" is printed
// verbatim), every set's load when they differ ("123 / 110 / 110 lb"), a Flex day named as
// an off-program session, and a served absence printed with its own reason. A null fetch
// says the list is not served right now — never a guessed list.
//
// The pure helpers are exported and unit-tested (tests/js/v7_today.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from — the margin day included.
//
// The R6 red-team classes, applied here (docs/design/v7/R6_BUILT_PAGES_REDTEAM.md):
//   * EMPTY is not UNREACHABLE. A null fetch (404, network) prints "<what> is not served
//     right now."; a served payload with nothing usable prints the fact sentence ("No open
//     ask from a coach this morning."). "Nothing skipped" is a claim about every source,
//     so it prints ONLY when both feeds it reads arrived (ADR-104).
//   * The ask is a coach's words through a guarded slot (#4225). It is linted client-side
//     with the coaches page's lintPublic (an ISO date, a percent sign, a device brand) plus
//     a second-person check; a hit folds the served text under <details> "as served" and
//     the line says the ask is not in public words today — never rewritten.
//   * three_questions.js is reused unchanged, so each of its lines carries the composite
//     data-src of the fields it reads; its "(n=21)" is folded to reader words here.
import { weekLine, nightLine, sessionLine, proteinLine, askLine, unwrap } from "/assets/js/three_questions.js";
import { absenceLine, isDark } from "/assets/js/absence_read.js";
import { dayInWords, dayLabel, dataThrough, daysOverdue, ptDaysAgo, nextWeighInText } from "/assets/js/entry_age.js";
import { lintPublic } from "/assets/js/v7_coaches.js";

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

/** Why a coach's ask cannot print on the main screen: lintPublic's reasons (an ISO date, a
 *  percent sign, a device brand — v7_coaches.js, not duplicated) plus "second person" when
 *  the text speaks to Matthew directly ("you", "your", or a vocative "Matthew,"). [] = clean. */
export function lintAsk(text) {
  const t = String(text || "");
  const why = lintPublic(t);
  if (/\byou(?:r|rs|'re|’re)?\b/i.test(t) || /(?:^|[.!?]\s+)Matthew\s*[,:—]|,\s*Matthew\s*[.!?]?\s*$/.test(t)) why.push("second person");
  return why;
}

/** The ask's line under its own heading: askLine's HTML with the "The one ask:" key dropped
 *  (the heading says it). A due day that is today says "due today" (#4224 — never "0 days
 *  late"). A text that fails lintAsk is folded under <details> "as served" and the line says
 *  so in its place. "" when there is no ask. */
export function askBody(dash, now = new Date()) {
  let html = readerWords(askLine(dash, now).replace(/^<span class="tq-ask-k">[^<]*<\/span>\s*/, ""));
  if (!html) return "";
  const a = chosenAsk(dash, now);
  if (a && ptDaysAgo(a.due, now) === 0) {
    const due = dayInWords(a.due, { weekday: false });
    if (due) html = html.replace(`due ${esc(due)}`, `due today, ${esc(due)}`);
  }
  const why = a ? lintAsk(a.text) : [];
  if (!why.length) return html;
  const m = /“<span data-verbatim>([\s\S]*?)<\/span>”/.exec(html);
  if (!m) return html;
  const line = html.replace(m[0], "The ask is not in public words today").replace(/^\s*—\s*/, "");
  return (
    `${line}` +
    `<details class="td-details"><summary>The ask, as served</summary>` +
    `<blockquote class="td-coach" data-src="api_coaching-dashboard.open_actions[].text"><span data-verbatim>${m[1]}</span></blockquote>` +
    `<p class="td-note">Kept off the main screen: it carries ${esc(why.join(", "))}. Served without edits.</p></details>`
  );
}

// three_questions.js is shared with the live v4 cockpit and reused unchanged, so its
// sentences are re-spelled HERE for the v7 reader rules (RULES: no `n=`, dates in words):
// "(n=21)" → "over 21 nights" (hrv_avg_n counts nightly readings), "Sep 26" → "September 26"
// (fmtDay's short month, expanded — the same day, never recomputed), ", already in Hevy" →
// ", already on his phone" (a brand the shell would have to gloss). Numbers, units and
// percentages stay: the 77% carries its window and its n in the same sentence.
const MONTH_WORDS = { Jan: "January", Feb: "February", Mar: "March", Apr: "April", May: "May", Jun: "June", Jul: "July", Aug: "August", Sep: "September", Oct: "October", Nov: "November", Dec: "December" };
export function readerWords(line) {
  return String(line || "")
    .replace(/\s*\(n=(\d+)\)/g, (_, n) => ` over ${n} night${n === "1" ? "" : "s"}`)
    .replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2})\b/g, (_, m, d) => `${MONTH_WORDS[m]} ${d}`)
    .replace(/, already in Hevy\b/g, ", already on his phone");
}

/** One entry's body, by state (R6 fix 1): the served line; a served-but-empty fact sentence
 *  with its data-src; or, when the fetch itself returned nothing, "<what> is not served
 *  right now." — never a fact sentence on a 404. */
export function stateHTML({ served, line, what, fact, src, cls = "td-a" }) {
  if (line) return `<p class="${cls}" data-src="${esc(src)}">${line}</p>`;
  if (!served) return `<p class="td-note">${esc(what)} is not served right now.</p>`;
  return `<p class="td-note" data-src="${esc(src)}">${esc(fact)}</p>`;
}

/** Served reps as the reader sees them: a number, or the served range string verbatim
 *  ("8–12" — Hevy's own range, never parsed into one number). "" when nothing usable. */
function repsText(r) {
  if (typeof r === "string") return r.trim();
  const n = num(r);
  return n != null ? String(n) : "";
}

/** The session's rows, IF /api/session serves an exercise list: [{i, name, sets, reps, loads,
 *  dose}] — `loads` is every set's pounds in order when they differ (a top set and its
 *  back-offs), else the one load; `dose` is the plain-text line. Null when the endpoint is
 *  absent or carries no list — never a guessed list. */
export function loadRows(session) {
  const ex = session && Array.isArray(session.exercises) ? session.exercises : null;
  if (!ex || !ex.length) return null;
  const rows = [];
  ex.forEach((e, i) => {
    if (!e || !e.name) return;
    const sets = num(e.sets);
    const reps = repsText(e.reps);
    const per = Array.isArray(e.loads_lbs) ? e.loads_lbs.map(num).filter((x) => x != null) : [];
    const one = num(e.load_lbs != null ? e.load_lbs : e.load);
    const distinct = new Set(per).size > 1;
    const loads = distinct ? per : one != null ? [one] : per.length ? [per[0]] : [];
    const loadSrc = distinct ? "loads_lbs" : one != null ? "load_lbs" : "loads_lbs";
    const setsTxt = sets != null && reps ? `${sets} × ${reps}` : sets != null ? `${sets} set${sets === 1 ? "" : "s"}` : reps ? `${reps} reps` : "";
    const dose = [setsTxt, loads.length ? `${loads.join(" / ")} lb` : ""].filter(Boolean).join(" · ");
    rows.push({ i, name: String(e.name), sets, reps, loads, loadSrc, dose });
  });
  return rows.length ? rows : null;
}

/** One row's dose as HTML — every figure in its own span carrying the served field it came from. */
export function doseHTML(r) {
  const at = (f) => `data-src="api_session.exercises[${r.i}].${f}"`;
  const s = r.sets != null ? `<span ${at("sets")}>${r.sets}</span>` : "";
  let setsPart = "";
  if (s && r.reps) setsPart = `${s} × <span ${at("reps")}>${esc(r.reps)}</span>`;
  else if (s) setsPart = `${s} set${r.sets === 1 ? "" : "s"}`;
  else if (r.reps) setsPart = `<span ${at("reps")}>${esc(r.reps)}</span> reps`;
  const loadPart = r.loads.length ? `<span ${at(r.loadSrc)}>${r.loads.join(" / ")}</span> lb` : "";
  return [setsPart, loadPart].filter(Boolean).join(" · ");
}

// The program's role labels (session_sequence: `_ROLE_LABEL[role].lower()`), in a reader's words.
const ROLE_WORDS = {
  "upper-heavy": "upper body, heavy",
  "lower-heavy": "lower body, heavy",
  "upper-volume": "upper body, more reps at a lighter weight",
  "lower-volume": "lower body, more reps at a lighter weight",
  heavy: "heavy",
  moderate: "moderate",
  "heavy-moderate": "heavy to moderate",
};
const isoToWords = (t) => String(t || "").replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (m) => dayInWords(m, { weekday: false }) || m);

/** The served position_label in reader words: "week 2 · session 3 of 4 · upper-heavy · DELOAD"
 *  → "week 2, session 3 of 4 — upper body, heavy, a lighter (deload) week". Any ISO date in it
 *  is spelled through entry_age.js. "" when nothing is served. */
export function positionWords(label) {
  const parts = String(label || "").split(" · ").map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return "";
  let deload = false;
  const out = [];
  let role = "";
  for (const p of parts) {
    if (/^deload$/i.test(p)) deload = true;
    else if (ROLE_WORDS[p.toLowerCase()]) role = ROLE_WORDS[p.toLowerCase()];
    else
      out.push(
        isoToWords(p.replace(/_/g, " ")).replace(/\s*\(extra — the \d+-day floor holds (week \d+) until ([^)]+)\)/, (_, w, d) => ` — an extra one; ${w} opens no sooner than ${d}`),
      );
  }
  let s = out.join(", ");
  if (role) s = s ? `${s} — ${role}` : role;
  if (deload) s += ", a lighter (deload) week";
  return s;
}

/** The session block under the /api/routine line: a heading naming the day and the program
 *  position (or the off-program day), then the table; a served absence prints its reason; a
 *  null fetch says the list is not served right now. "" only when there is nothing to say. */
export function sessionBlockHTML(session, { served = session != null } = {}) {
  if (!served || !session) return '<p class="td-note">Today’s exercise list is not served right now.</p>';
  if (session.state === "absent") {
    const why = isoToWords(session.reason);
    return `<p class="td-note" data-src="api_session.reason">No exercise list for today${why ? `: ${esc(why)}` : ""}.</p>`;
  }
  const rows = loadRows(session);
  const day = dayInWords(session.date);
  const daySpan = day ? `<span data-src="api_session.date">${esc(day)}</span>` : "Today";
  let head;
  if (session.kind === "complement") {
    head = `${daySpan} is <span data-src="api_session.kind">an off-program session</span> — extra work outside the program’s rotation, lifted like this:`;
  } else {
    const pos = positionWords(session.position_label);
    head = pos ? `${daySpan}, <span data-src="api_session.position_label">${esc(pos)}</span>, as it will be lifted:` : `${daySpan}, as it will be lifted:`;
  }
  const headHTML = `<p class="td-small">${head}</p>`;
  if (!rows) return `${headHTML}<p class="td-note" data-src="api_session.exercises">The session is served with no exercise list.</p>`;
  const body = rows.map((r) => `<tr><td data-src="api_session.exercises[${r.i}].name">${esc(r.name)}</td><td class="n">${doseHTML(r)}</td></tr>`).join("");
  return `${headHTML}<table class="td-loads" data-src="api_session.exercises"><tbody>${body}</tbody></table>`;
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
 *  (`source_freshness.sources[].datatypes[]` — the API's own per-channel dark flag), and the
 *  manual logs he let lapse. Each row: { key, label, text, days, src }. Empty when nothing
 *  is dark.
 *
 *  The SOURCE rule (driver finding, 2026-09-26): a source row is HIS skip only when the
 *  registry marks it behavioral — a manual log, status `behavioral-stale` — AND its last log
 *  falls inside the experiment (on or after `since`, journey.started_date). An automated pull
 *  that goes `stale` and a source `paused` by the site are the site's lapses, not his; a
 *  manual log quiet since before Day 1 ("Food delivery", last logged in March) is a parked
 *  channel, not something he skipped this morning. With `since` unknown no source row can
 *  be substantiated, so none prints. */
export function skipsList({ pillars, freshness, since } = {}) {
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
  const from = iso(since);
  for (const s of sources) {
    if (String(s.status || "") !== "behavioral-stale") continue; // `stale` and `paused` are the site's, not his
    if (!isIso(from) || !isIso(s.last_update) || iso(s.last_update) < from) continue; // quiet since before Day 1: parked, not skipped
    const days = num(s.age_hours) != null ? Math.round(num(s.age_hours) / 24) : daysBetween(s.last_update, today);
    push({ key: `source:${s.id}`, label: String(s.label || s.id), text: days != null ? `nothing logged for ${days} day${days === 1 ? "" : "s"}` : "nothing logged", days, src: `api_source_freshness.sources[${s.id}]` });
  }
  return out;
}

/** The dated return line: rewritten every morning; the next weigh-in in the ONE spelling every v7
 *  page uses (entry_age.nextWeighInText, R6 fix 4) — due when the day after the last weigh-in is on
 *  or after `through` (this page's data-through day), else "No weigh-in since <day> — N days". */
export function returnLine(journey, through) {
  const r = nextWeighInText(journey && journey.last_weighin_date, through, { capital: true });
  return { date: r.day, text: r.text ? `Rewritten every morning. ${r.text}.` : "Rewritten every morning." };
}

// ── rendering ────────────────────────────────────────────────────────────────
// The composite data-src each three_questions.js line carries — the fields it reads, named.
const SRC = {
  week: "api_snapshot.journey.{lost_lbs,weighin_count,current_weight_lbs,started_date,last_weighin_date,weekly_rate_lbs,weekly_rate_ci_low,weekly_rate_ci_high,rate_provisional,week_n}",
  night: "api_snapshot.vitals.{sleep_hours,recovery_pct,hrv_ms,hrv_avg_ms,hrv_avg_n,hrv_avg_window_days,night_of}",
  session: "api_routine.routine.{archetype,exercise_count,total_sets,days_out,target_date,pushed}",
  protein: "api_nutrition_overview.nutrition.{latest_protein_g,latest_date,protein_floor_g,protein_floor_hit_days,days_logged}",
};

function setMargin(section, dateStr, src) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
  if (src) m.setAttribute("data-src", src);
}

function fill(section, html) {
  if (!section) return;
  const body = section.querySelector(".td-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

function renderWeek(journey, served) {
  const sec = document.getElementById("td-week");
  fill(sec, stateHTML({ served, line: readerWords(weekLine(journey)), what: "The week", fact: "No weigh-in is on the record yet.", src: SRC.week }));
  if (journey) setMargin(sec, journey.last_weighin_date, "api_snapshot.journey.last_weighin_date");
}

function renderNight(vitals, served) {
  const sec = document.getElementById("td-night");
  fill(sec, stateHTML({ served, line: readerWords(nightLine(vitals)), what: "Last night", fact: "No sleep reading is on the record for last night.", src: SRC.night }));
  if (vitals) setMargin(sec, vitals.night_of || vitals.as_of_date, vitals.night_of ? "api_snapshot.vitals.night_of" : "api_snapshot.vitals.as_of_date");
}

function renderToday({ rt, nut, session }) {
  const sec = document.getElementById("td-today");
  const bits = [];
  const s = readerWords(sessionLine(rt));
  bits.push(stateHTML({ served: !!rt, line: s, what: "The session", fact: "No session is on the sheet for today.", src: SRC.session }));
  bits.push(sessionBlockHTML(session));
  bits.push(stateHTML({ served: !!nut, line: readerWords(proteinLine(nut)), what: "The food log", fact: "Nothing from the food log is on the record.", src: SRC.protein }));
  fill(sec, bits.join(""));
  const r = rt && rt.routine;
  const n = unwrap(nut, "nutrition") || {};
  if (r && r.target_date) setMargin(sec, r.target_date, "api_routine.routine.target_date");
  else if (rt && rt.as_of_date) setMargin(sec, rt.as_of_date, "api_routine.as_of_date");
  else setMargin(sec, n.latest_date, "api_nutrition_overview.nutrition.latest_date");
}

function renderAsk(dash, now) {
  const sec = document.getElementById("td-ask");
  const line = askBody(dash, now);
  fill(sec, stateHTML({ served: !!dash, line, what: "The coaches’ asks are", fact: "No open ask from a coach this morning.", src: line ? "api_coaching-dashboard.open_actions[]" : "api_coaching-dashboard.open_actions" }).replace("The coaches’ asks are is not", "The coaches’ asks are not"));
  const a = chosenAsk(dash, now);
  if (a) setMargin(sec, a.due || a.asked_on, a.due ? "api_coaching-dashboard.open_actions[].due" : "api_coaching-dashboard.open_actions[].asked_on");
}

/** The skips entry's body. "Nothing skipped" is a claim about EVERY source, so it needs both
 *  feeds served and empty; with a feed missing, the rows that did arrive print and the rest
 *  is said to be not served — never a clean sheet because a request failed. */
export function skipsHTML({ pillars, freshness, since, snapServed, freshServed }) {
  const rows = skipsList({ pillars, freshness, since });
  const list = rows.length ? `<ul class="td-skips">${rows.map((r) => `<li data-src="${esc(r.src)}"><b>${esc(r.label)}</b> — ${esc(r.text)}</li>`).join("")}</ul>` : "";
  if (snapServed && freshServed) {
    return list || '<p class="td-note" data-src="api_snapshot.character.pillars[].absence | api_source_freshness.sources">Nothing skipped: every wired-in source reported inside its own window.</p>';
  }
  const missing = !snapServed && !freshServed ? "What he skips is" : !snapServed ? "The rest — the areas of his life the site scores — is" : "The rest — his devices and the phone’s channels — is";
  return `${list}<p class="td-note">${missing} not served right now.</p>`;
}

function renderSkips({ pillars, freshness, since, snapServed, freshServed }) {
  const sec = document.getElementById("td-skips");
  fill(sec, skipsHTML({ pillars, freshness, since, snapServed, freshServed }));
  if (freshness) setMargin(sec, freshness.pacific_today, "api_source_freshness.pacific_today");
}

function renderReturn(journey, through) {
  const sec = document.getElementById("td-return");
  const el = document.getElementById("td-return-line");
  const r = returnLine(journey, through);
  if (el) {
    el.textContent = r.text;
    el.classList.remove("td-pending");
    el.setAttribute("data-src", "api_snapshot.journey.last_weighin_date");
  }
  if (r.date) setMargin(sec, r.date, "api_snapshot.journey.last_weighin_date + 1 day");
}

// A non-2xx answer is null — but its BODY IS READ FIRST. Chromium reports a fetch finished
// only once the body is consumed; returning on `r.ok` alone left CloudFront's keep-alive
// 404 for /api/session in flight forever, so Playwright's networkidle (the cut-over
// visual-QA gate's wait) never arrived on this page while every other /next/ page idled
// in seconds (driver sweep, build 6cb06c7, 2026-09-26 19:56 PT).
async function getJSON(p) {
  try {
    const r = await fetch(p, { headers: { accept: "application/json" } });
    if (!r.ok) {
      await r.text().catch(() => "");
      return null;
    }
    return await r.json();
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
    getJSON("/api/session"), // plan E3 (#4318) — a non-2xx is drained above and prints as not served
  ]);
  const journey = snap ? unwrap(snap.journey, "journey") : null;
  const vitals = snap ? unwrap(snap.vitals, "vitals") : null;
  const character = snap ? unwrap(snap.character, "character") : null;
  const pillars = (snap && snap.character && snap.character.pillars) || (character && character.pillars) || [];
  const thr = document.getElementById("td-through");
  const through = throughDate({ journey, vitals, nutrition: nut });
  if (thr) thr.textContent = dataThrough(through);
  const now = new Date();
  renderWeek(journey, !!snap);
  renderNight(vitals, !!snap);
  renderToday({ rt, nut, session });
  renderAsk(dash, now);
  renderSkips({ pillars, freshness: fresh, since: journey && journey.started_date, snapServed: !!snap, freshServed: !!fresh });
  renderReturn(journey, through);
}

if (typeof document !== "undefined" && document.getElementById("td-week")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}

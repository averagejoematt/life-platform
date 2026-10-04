// v7_numbers.js — the v7 "His numbers" page (#4182, plan §2a row 4; Prototype C screen IV).
//
// One scroll, six dated entries and a fold, every number served: weight (every weigh-in
// since the start, the smoothed trend, the rate with its interval — and "no date to goal"
// when the engine dates none), sleep (hours a night, last night by both instruments),
// eating (calories a day, the protein floor as k of n days, and the engine's refusal to
// publish a deficit, verbatim), training (minutes a day, the counts), blood tests (the
// last draw, dated; markers outside range by category; the full panel in place), then
// what is NOT being recorded — journal, blood-sugar sensor, blood pressure, state of mind,
// Garmin — each stated once as an absence with its day count, never as anyone "going
// dark"; then the engine's own score folded under a plain key.
//
// Under every chart: "CSV" — a client-side Blob built from the JSON this page already
// fetched (no new route, plan E11) — and "see all N", which opens the full series in
// place. The one-sentence reads reuse the pure halves of the /data/ topic modules
// (weightFoldLine, sleepFold, nutritionFold, labsFold) so the two surfaces can never
// disagree about a number. Dates in words come from entry_age.js — the one spelling
// every v7 page uses. Every rendered figure carries a data-src naming its served field.
// The pure helpers are exported and unit-tested (tests/js/v7_numbers.test.mjs); none
// reads the wall clock.
import { tryJSON, esc, fmt } from "/assets/js/evidence_shared.js";
import { dayInWords, dayLabel, dataThrough, goalWindowText } from "/assets/js/entry_age.js";
import { nextWriteUpLine, nextWeighInLine } from "/assets/js/v7_week.js";
import { weightTrendChart, lineChart, barChart } from "/assets/js/charts.js";
import { weightFoldLine } from "/assets/js/evidence_body.js";
import { sleepFold } from "/assets/js/evidence_sleep.js";
import { nutritionFold } from "/assets/js/evidence_nutrition.js";
import { labsFold, labName } from "/assets/js/evidence_body.js";

const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const num = (v, dp) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString("en-US", { minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0 }) : "");
const one = (v) => (Math.round(Number(v) * 10) / 10).toFixed(1);
const plural = (n, w) => `${num(n)} ${w}${Number(n) === 1 ? "" : "s"}`;

/** The margin of an entry, from a served date: { d: "26", mo: "Sep", w: "Saturday" }. Null when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Sat Sep 26"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

// ── CSV (plan E11): the JSON already in the browser, as a file ───────────────
/** RFC-4180-ish: a header row from `columns`, one row per object, quotes doubled, a cell
 *  quoted when it carries a comma, a quote or a newline. Null/undefined → empty cell. */
export function toCsv(rows, columns) {
  const cell = (v) => {
    if (v == null) return "";
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = columns.map(cell).join(",");
  const body = (Array.isArray(rows) ? rows : []).map((r) => columns.map((c) => cell(r && r[c])).join(","));
  return [head, ...body].join("\n") + "\n";
}

/** "weight_through_2026-09-26.csv" — the section and the day the series runs through. */
export function csvName(section, through) {
  return `${section}${isIso(through) ? `_through_${iso(through)}` : ""}.csv`;
}

// ── weight ───────────────────────────────────────────────────────────────────
/** The goal half, in the page's own words: goal, what's left, the rate WITH its interval and
 *  its provisional flag, and the refusal verbatim when the engine dates no projection. */
export function weightGoalSentence(j) {
  if (!j || j.goal_weight_lbs == null) return "";
  const bits = [`Goal <span data-src="api_journey.journey.goal_weight_lbs">${esc(fmt(j.goal_weight_lbs))}</span> lb${j.remaining_lbs != null ? `; <span data-src="api_journey.journey.remaining_lbs">${esc(one(j.remaining_lbs))}</span> lb to go` : ""}.`];
  const r = j.weekly_rate_lbs;
  if (r != null && Number(r) !== 0) {
    const n = Number(j.weighin_count) > 0 ? ` over <span data-src="api_journey.journey.weighin_count">${esc(num(j.weighin_count))}</span> weigh-ins` : "";
    const ci = j.weekly_rate_ci_low != null && j.weekly_rate_ci_high != null
      ? `; the likely range is <span data-src="api_journey.journey.weekly_rate_ci_high">${esc(one(Math.abs(Number(j.weekly_rate_ci_high))))}</span> to <span data-src="api_journey.journey.weekly_rate_ci_low">${esc(one(Math.abs(Number(j.weekly_rate_ci_low))))}</span>`
      : "";
    bits.push(`About <span data-src="api_journey.journey.weekly_rate_lbs">${esc(one(Math.abs(Number(r))))}</span> lb a week ${Number(r) < 0 ? "down" : "up"} so far${n}${j.rate_provisional ? ", provisional" : ""}${ci}.`);
  }
  if (!j.projected_goal_date) bits.push("No date to goal.");
  else bits.push(`<span data-src="api_journey.journey.{projected_goal_date,projected_goal_date_earliest,projected_goal_date_latest}">${esc(goalWindowText(j))}</span>`); // R7 fix 5: month, year, range
  return bits.join(" ");
}

/** The weight sentence, with ONE day count (R7 fix 6). The shared /data/ line counts the span
 *  between the first and last weigh-in (`weighin_span_days`, 27) where Home and Who he is count
 *  the days of the experiment (`day_n`, 28) — one span, two numbers. Here the count is the
 *  experiment's day when it is served; the shared line stands untouched when it is not. */
export function weightLine(j, today) {
  const line = weightFoldLine(j, today);
  const n = j && Number(j.day_n);
  if (!line || !Number.isInteger(n) || n < 1) return line;
  return line.replace(/, (\d+) weigh-ins in \d+ days\.$/, `, $1 weigh-ins in ${n} days.`);
}

/** The weigh-ins as served, oldest first, only the usable rows. */
export function weightSeries(wp) {
  return (Array.isArray(wp) ? wp : [])
    .filter((r) => r && isIso(r.date) && r.weight_lbs != null && Number.isFinite(Number(r.weight_lbs)))
    .map((r) => ({ date: iso(r.date), weight_lbs: Number(r.weight_lbs) }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ── sleep ────────────────────────────────────────────────────────────────────
/** Nights with an hours reading, oldest first: [{date, hours, sleep_score, recovery_score, hrv, rhr}]. */
export function sleepSeries(trend) {
  return (Array.isArray(trend) ? trend : [])
    .filter((r) => r && isIso(r.date) && r.hours != null && Number.isFinite(Number(r.hours)))
    .map((r) => ({ date: iso(r.date), hours: Number(r.hours), sleep_score: r.sleep_score ?? null, recovery_score: r.recovery_score ?? null, hrv: r.hrv ?? null, rhr: r.rhr ?? null }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ── eating ───────────────────────────────────────────────────────────────────
/** Logged days with a calorie count, oldest first. */
export function eatingSeries(trend) {
  return (Array.isArray(trend) ? trend : [])
    .filter((r) => r && isIso(r.date) && r.calories != null && Number.isFinite(Number(r.calories)))
    .map((r) => ({ date: iso(r.date), calories: Number(r.calories), protein_g: r.protein_g ?? null, carbs_g: r.carbs_g ?? null, fat_g: r.fat_g ?? null }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ── training ─────────────────────────────────────────────────────────────────
/** The served day rows, oldest first, with a `label` (the day of the month) for the bars. With a
 *  served start day, only the rows on or after it: the feed's trailing window can open a day
 *  early, and "28 of 29 days since September 6" counted a day before the start (R7 fix 6). */
export function trainingSeries(daily, startedDate) {
  const from = isIso(startedDate) ? iso(startedDate) : "";
  return (Array.isArray(daily) ? daily : [])
    .filter((r) => r && isIso(r.date) && r.total_min != null && Number.isFinite(Number(r.total_min)) && (!from || iso(r.date) >= from))
    .map((r) => ({ ...r, date: iso(r.date), total_min: Number(r.total_min) }))
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((r, i, all) => ({ ...r, label: barLabel(r.date, i, all.length) }));
}

/** The bar label for a day: the day of the month on the 1st, 5th, 10th … and on the first and
 *  last bar; "" between, so twenty-one bars stay readable at 390px. */
export function barLabel(date, i, n) {
  const dom = +iso(date).slice(8, 10);
  return i === 0 || i === n - 1 || dom === 1 || dom % 5 === 0 ? String(dom) : "";
}

/** "Trained on k of n days since <day>: … " — every count a served field, the day in words. */
export function trainingSentence(t, startedDate) {
  const days = trainingSeries(t && t.daily_modality_minutes_30d, startedDate);
  if (!days.length) return "";
  const trained = days.filter((d) => d.total_min > 0).length;
  const tr = (t && t.training) || {};
  const wk = (t && Array.isArray(t.weekly_trend) && t.weekly_trend.length) ? t.weekly_trend[t.weekly_trend.length - 1] : null;
  const walk = (t && t.walking) || {};
  const since = isIso(startedDate) ? ` since ${esc(dayInWords(startedDate, { weekday: false }))}` : "";
  const bits = [`Trained on <span data-src="api_training_overview.daily_modality_minutes_30d[].total_min">${esc(num(trained))}</span> of <span data-src="api_training_overview.daily_modality_minutes_30d.length">${esc(num(days.length))}</span> days${since}.`];
  const parts = [];
  if (tr.workouts_30d != null) parts.push(`<span data-src="api_training_overview.training.workouts_30d">${esc(num(tr.workouts_30d))}</span> workouts`);
  if (tr.strength_sessions_30d != null) parts.push(`<span data-src="api_training_overview.training.strength_sessions_30d">${esc(num(tr.strength_sessions_30d))}</span> of them strength`);
  if (walk.total_walks_30d != null) parts.push(`<span data-src="api_training_overview.walking.total_walks_30d">${esc(num(walk.total_walks_30d))}</span> walks`);
  if (parts.length) bits.push(`In the last thirty days: ${parts.join(", ")}.`);
  if (wk && wk.workouts != null && wk.minutes != null) bits.push(`This calendar week so far: <span data-src="api_training_overview.weekly_trend[].workouts">${esc(num(wk.workouts))}</span> workout${Number(wk.workouts) === 1 ? "" : "s"}, <span data-src="api_training_overview.weekly_trend[].minutes">${esc(num(wk.minutes))}</span> minutes.`);
  if (walk.avg_daily_steps != null && walk.avg_daily_steps_n != null) bits.push(`<span data-src="api_training_overview.walking.avg_daily_steps">${esc(num(walk.avg_daily_steps))}</span> steps a day on average over <span data-src="api_training_overview.walking.avg_daily_steps_n">${esc(num(walk.avg_daily_steps_n))}</span> days.`);
  return bits.join(" ");
}

// ── blood tests ──────────────────────────────────────────────────────────────
const flagged = (b) => !!b.flag && String(b.flag).toLowerCase() !== "null";
/** Markers outside their reference range, by category: [{label, flagged, total}] in served order. */
export function flaggedByCategory(biomarkers) {
  const by = new Map();
  for (const b of Array.isArray(biomarkers) ? biomarkers : []) {
    if (!b) continue;
    const cat = b.category || "Other";
    const row = by.get(cat) || { label: cat, flagged: 0, total: 0 };
    row.total += 1;
    if (flagged(b)) row.flagged += 1;
    by.set(cat, row);
  }
  return [...by.values()];
}

/** The labs chart: one row per category with a marker outside range, most first; the fill is that
 *  category's share outside range (k of n), drawn on tokens.css's .suf-* row classes. "" when none. */
export function labsBars(cats) {
  const rows = (Array.isArray(cats) ? cats : []).filter((c) => c && c.flagged > 0 && c.total > 0).sort((a, b) => b.flagged - a.flagged || a.label.localeCompare(b.label));
  if (!rows.length) return "";
  const row = (r) => `<div class="suf-row" role="img" aria-label="${esc(`${r.label}: ${r.flagged} of ${r.total} markers outside the reference range`)}"><span class="suf-l">${esc(r.label)}</span>` +
    `<span class="suf-track"><span class="suf-fill suf-ink" style="width:${((r.flagged / r.total) * 100).toFixed(1)}%"></span></span>` +
    `<span class="suf-v mono"><span data-src="api_labs.labs.biomarkers[].flag">${esc(num(r.flagged))}</span> of <span data-src="api_labs.labs.biomarkers[].category">${esc(num(r.total))}</span></span></div>`;
  return `<figure class="chart suf"><div class="suf-rows" role="img" aria-label="Markers outside their reference range, by category">${rows.map(row).join("")}</div>` +
    `<figcaption class="chart-cap label">Markers outside the lab’s reference range, by category — the bar is that category’s share</figcaption></figure>`;
}

/** The panel rows for the CSV and the in-place table, flagged rows first. */
export function labRows(biomarkers) {
  const rows = (Array.isArray(biomarkers) ? biomarkers : []).filter(Boolean).map((b) => ({
    marker: labName(b.name), value: b.value ?? null, unit: b.unit || "", range: b.range || "", flag: flagged(b) ? ({ H: "high", L: "low" })[String(b.flag).toUpperCase()] || String(b.flag) : "", category: b.category || "",
  }));
  return rows.filter((r) => r.flag).concat(rows.filter((r) => !r.flag));
}

// ── the absence strip ────────────────────────────────────────────────────────
// The five instruments the strip names, in the design order (CONCEPT §14 "the skips, in one
// vocabulary"). Each row is stated as an absence with its served day count; none of them is
// narrated as anyone going dark. `key` is the apple_health datatype key on /api/source_freshness.
const ABSENT = [
  { id: "journal", label: "Journal" },
  { id: "cgm", label: "Blood-sugar sensor", key: "cgm" },
  { id: "blood_pressure", label: "Blood pressure", key: "blood_pressure" },
  { id: "state_of_mind", label: "State of mind", key: "state_of_mind" },
  { id: "garmin", label: "Garmin" },
];

const NOT_SERVED = "not served right now";
const NO_ROW = "nothing on record";
const notServed = (what) => `<p class="nm-note">${esc(what)} is not served right now.</p>`;

const dayCount = (n) => (Number.isFinite(Number(n)) ? `${num(Math.round(Number(n)))} day${Math.round(Number(n)) === 1 ? "" : "s"}` : "");

/** [{id, label, text, src}] — the text is HTML with the count wrapped in its data-src. A row whose
 *  feed did not answer says "not served right now"; a served feed with no row for the instrument
 *  says "nothing on record" (R7 fix 9 — two different facts, and neither is "the payload"); a row
 *  that is being recorded says that. */
export function absenceRows({ freshness, pulse } = {}) {
  const sources = (freshness && freshness.sources) || [];
  const ah = sources.find((s) => s && s.id === "apple_health") || null;
  const dts = (ah && Array.isArray(ah.datatypes)) ? ah.datatypes : null;
  const garmin = sources.find((s) => s && s.id === "garmin") || null;
  const journal = pulse && pulse.pulse && pulse.pulse.glyphs && pulse.pulse.glyphs.journal;
  return ABSENT.map((row) => {
    if (row.id === "journal") {
      if (!journal) return { ...row, text: pulse ? NO_ROW : NOT_SERVED, src: "api_pulse.pulse.glyphs.journal" };
      if (journal.written_today) return { ...row, text: "an entry today", src: "api_pulse.pulse.glyphs.journal.written_today" };
      const gap = Number(journal.gap_days);
      return { ...row, text: Number.isFinite(gap) && gap > 0 ? `nothing written for <span data-src="api_pulse.pulse.glyphs.journal.gap_days">${esc(dayCount(gap))}</span>` : "no entry on record", src: "api_pulse.pulse.glyphs.journal.gap_days" };
    }
    if (row.id === "garmin") {
      if (!garmin) return { ...row, text: freshness ? NO_ROW : NOT_SERVED, src: "api_source_freshness.sources[garmin]" };
      const dk = garmin.days_dark;
      const paused = garmin.status === "paused";
      const count = Number.isFinite(Number(dk)) ? `<span data-src="api_source_freshness.sources[garmin].days_dark">${esc(dayCount(dk))}</span> without a record` : "no record since it stopped";
      return { ...row, text: paused ? `paused — ${count}; it cannot report, so the gap is a hole in the record, not a fact about him` : count, src: "api_source_freshness.sources[garmin].days_dark" };
    }
    const src = `api_source_freshness.sources[apple_health].datatypes[${row.key}]`;
    if (!dts) return { ...row, text: freshness ? NO_ROW : NOT_SERVED, src };
    const dt = dts.find((d) => d && d.key === row.key);
    if (!dt) return { ...row, text: NO_ROW, src };
    const floor = dt.age_days == null && dt.age_floor_days != null ? `more than <span data-src="${src}.age_floor_days">${esc(dayCount(dt.age_floor_days))}</span>` : `<span data-src="${src}.age_days">${esc(dayCount(dt.age_days))}</span>`;
    if (!dt.dark) return { ...row, text: `being recorded; last reading ${esc(dayInWords(dt.last_seen) || "on record")}`, src };
    if (row.id === "cgm") return { ...row, text: `no sensor worn; ${floor} without a reading`, src };
    return { ...row, text: `${floor} without ${row.id === "state_of_mind" ? "an entry" : "a reading"}`, src };
  });
}

// ── the engine's score ───────────────────────────────────────────────────────
/** The plain key and the rows behind the fold, from /api/character. Null when nothing is served. */
export function engineKey(ch) {
  const c = ch && ch.character;
  if (!c) return null;
  const pillars = (ch && Array.isArray(ch.pillars)) ? ch.pillars : [];
  const k = c.composite_pillar_count, n = c.composite_pillar_total;
  const day = dayInWords(c.as_of_date);
  const bits = ["The engine scores seven areas of his life from his own data, each from 0 to 100, and averages the ones it can see."];
  if (c.composite_score != null) bits.push(`On ${esc(day) || "the last day it ran"}: <span data-src="api_character.character.composite_score">${esc(one(c.composite_score))}</span>${k != null && n != null ? `, from <span data-src="api_character.character.composite_pillar_count">${esc(num(k))}</span> of <span data-src="api_character.character.composite_pillar_total">${esc(num(n))}</span> areas${Number(n) - Number(k) > 0 ? ` (${esc(num(Number(n) - Number(k)))} ${Number(n) - Number(k) === 1 ? "has" : "have"} no instrument yet)` : ""}` : ""}.`);
  if (c.level != null) bits.push(`Its level, <span data-src="api_character.character.level">${esc(num(c.level))}</span>, is how many weeks the areas have held up.`);
  const rows = pillars.filter((p) => p && p.name).map((p) => ({
    name: String(p.name).replace(/_/g, " "),
    score: p.not_instrumented ? null : (p.raw_score != null ? Number(p.raw_score) : null),
    // The served not_instrumented_note is builder prose (it names the internal term and an issue);
    // the reader gets the fact in the page's own words.
    note: p.not_instrumented ? "no instrument yet" : (p.coverage_hold ? "held — too little data" : ""),
  }));
  return { key: bits.join(" "), rows, as_of: c.as_of_date || "" };
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
  const body = section.querySelector(".nm-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

function csvHref(text) {
  try {
    return URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  } catch (e) {
    return "data:text/csv;charset=utf-8," + encodeURIComponent(text);
  }
}

/** The tools row under a chart: CSV (a Blob of the served rows) · the count · "see all N" in place. */
function tools({ rows, columns, section, through, unit, table }) {
  const n = rows.length;
  const href = csvHref(toCsv(rows, columns));
  return `<p class="nm-tools"><a class="nm-csv" href="${esc(href)}" download="${esc(csvName(section, through))}">CSV</a><span>${esc(plural(n, unit))}</span></p>` +
    (n && table ? `<details class="nm-all"><summary class="nm-tools">see all ${esc(num(n))}</summary>${table}</details>` : "");
}

const td = (v, cls) => `<td${cls ? ` class="${cls}"` : ""}>${esc(v == null || v === "" ? "—" : v)}</td>`;
const dateCell = (d) => `<td class="d"><time datetime="${esc(d)}">${esc(dayLabel(d))}</time></td>`;
const tableOf = (head, rowsHtml, dated = true) => `<table>${dated ? '<colgroup><col class="d"></colgroup>' : ""}<thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rowsHtml}</tbody></table>`;

function renderWeight(journey, wp, today) {
  const sec = document.getElementById("nm-weight");
  const j = journey && journey.journey;
  const rows = weightSeries(wp && wp.weight_progress);
  if (!journey || !wp) return fill(sec, notServed("The weigh-in record"));
  if (!j || !rows.length) return fill(sec, '<p class="nm-note">No weigh-in is on record yet.</p>');
  const since = j.started_date ? dayInWords(j.started_date, { weekday: false }) : "";
  const chart = weightTrendChart(rows, { label: `Weight, lb — every weigh-in${since ? ` since ${since}` : ""}` });
  const line = weightLine(j, today);
  fill(
    sec,
    chart +
      (line ? `<p class="nm-line" data-src="api_journey.journey">${esc(line)}</p>` : "") +
      `<p class="nm-small">${weightGoalSentence(j)}</p>` +
      tools({
        rows, columns: ["date", "weight_lbs"], section: "weight", through: j.last_weighin_date, unit: "weigh-in",
        table: tableOf(["day", "lb"], rows.map((r) => `<tr>${dateCell(r.date)}${td(one(r.weight_lbs), "n")}</tr>`).join("")),
      }),
  );
  setMargin(sec, j.last_weighin_date);
}

function renderSleep(sleep) {
  const sec = document.getElementById("nm-sleep");
  const rows = sleepSeries(sleep && sleep.sleep_trend);
  const fold = sleepFold(sleep);
  if (!sleep) return fill(sec, notServed("The sleep record"));
  if (!rows.length && !fold) return fill(sec, '<p class="nm-note">No night is on record yet.</p>');
  const chart = lineChart(rows, { valueKey: "hours", dateKey: "date", unit: " h", label: "Hours asleep a night", spine: true, emptyMsg: "No night served yet." });
  const s = (sleep && sleep.sleep_detail) || {};
  const through = s.as_of_date || (rows.length ? rows[rows.length - 1].date : "");
  fill(
    sec,
    chart +
      (fold ? `<p class="nm-line" data-src="api_sleep_detail.sleep_detail">${esc(fold.text)}</p>` : "") +
      tools({
        rows, columns: ["date", "hours", "sleep_score", "recovery_score", "hrv", "rhr"], section: "sleep", through, unit: "night",
        table: tableOf(["woke", "hours", "recovery"], rows.map((r) => `<tr>${dateCell(r.date)}${td(one(r.hours), "n")}${td(r.recovery_score != null ? `${fmt(r.recovery_score)}%` : "", "n")}</tr>`).join("")),
      }),
  );
  setMargin(sec, (fold && fold.through) || through);
}

function renderEating(nut) {
  const sec = document.getElementById("nm-eating");
  const rows = eatingSeries(nut && nut.nutrition_trend);
  const fold = nutritionFold(nut, null);
  if (!nut) return fill(sec, notServed("The food log"));
  if (!rows.length && !fold) return fill(sec, '<p class="nm-note">No logged day is on record yet.</p>');
  const chart = lineChart(rows, { valueKey: "calories", dateKey: "date", unit: "", label: "Calories logged a day", spine: true, emptyMsg: "No logged day served yet." });
  const n = (nut && nut.nutrition) || {};
  const through = n.latest_date || n.as_of || (rows.length ? rows[rows.length - 1].date : "");
  fill(
    sec,
    chart +
      (fold ? `<p class="nm-line" data-src="api_nutrition_overview.nutrition">${esc(fold.text)}</p>` : "") +
      tools({
        rows, columns: ["date", "calories", "protein_g", "carbs_g", "fat_g"], section: "eating", through, unit: "logged day",
        table: tableOf(["day", "calories", "protein g"], rows.map((r) => `<tr>${dateCell(r.date)}${td(num(r.calories), "n")}${td(r.protein_g != null ? num(r.protein_g) : "", "n")}</tr>`).join("")),
      }),
  );
  setMargin(sec, through);
}

function renderTraining(t, startedDate) {
  const sec = document.getElementById("nm-training");
  if (!t) return fill(sec, notServed("The training record"));
  const rows = trainingSeries(t.daily_modality_minutes_30d, startedDate);
  if (!rows.length) return fill(sec, '<p class="nm-note">No training day is on record yet.</p>');
  const since = isIso(startedDate) ? ` since ${dayInWords(startedDate, { weekday: false })}` : "";
  const chart = barChart(rows, { valueKey: "total_min", labelKey: "label", label: `Minutes trained a day${since} — the label is the day of the month` });
  const through = rows[rows.length - 1].date;
  const cols = ["date", "total_min", "strength_min", "walking_min", "cycling_min", "stretching_min", "soccer_min", "hiking_min", "breathwork_min", "other_min"];
  fill(
    sec,
    chart +
      `<p class="nm-line">${trainingSentence(t, startedDate)}</p>` +
      tools({
        rows, columns: cols, section: "training", through, unit: "day",
        table: tableOf(["day", "minutes", "strength", "walking"], rows.map((r) => `<tr>${dateCell(r.date)}${td(num(r.total_min), "n")}${td(num(r.strength_min || 0), "n")}${td(num(r.walking_min || 0), "n")}</tr>`).join("")),
      }),
  );
  setMargin(sec, through);
}

function renderLabs(labs) {
  const sec = document.getElementById("nm-labs");
  const L = labs && labs.labs;
  const fold = labsFold(labs);
  if (!labs) return fill(sec, '<p class="nm-note">The blood tests are not served right now.</p>');
  if (!L || !fold) return fill(sec, '<p class="nm-note">No blood test is on record yet.</p>');
  const chart = labsBars(flaggedByCategory(L.biomarkers));
  const rows = labRows(L.biomarkers);
  fill(
    sec,
    chart +
      `<p class="nm-line" data-src="api_labs.labs">${esc(fold.text)}</p>` +
      `<p class="nm-small">Reference ranges are the lab’s own; nothing here is medical advice. <span data-src="api_labs.labs.total_draws">${esc(num(L.total_draws))}</span> draws all time.</p>` +
      tools({
        rows, columns: ["marker", "value", "unit", "range", "flag", "category"], section: "blood_tests", through: L.latest_draw_date, unit: "marker",
        table: tableOf(["marker", "result", "reference range"], rows.map((r) => `<tr${r.flag ? ' class="flag"' : ""}>${td(r.marker)}${td(`${r.value ?? "—"}${r.unit ? ` ${r.unit}` : ""}${r.flag ? ` — ${r.flag}` : ""}`, "n")}${td(r.range)}</tr>`).join(""), false),
      }),
  );
  setMargin(sec, L.latest_draw_date);
}

function renderAbsent(freshness, pulse) {
  const sec = document.getElementById("nm-absent");
  const rows = absenceRows({ freshness, pulse });
  const today = (freshness && freshness.pacific_today) || "";
  fill(
    sec,
    `<p class="nm-small">Each of these is a gap in the record${today ? `, counted to ${esc(dayInWords(today))}` : ""} — stated once, here, so no chart above has to pretend.</p>` +
      `<ul class="nm-absent">${rows.map((r) => `<li data-src="${esc(r.src)}"><b>${esc(r.label)}</b> — ${r.text}.</li>`).join("")}</ul>`,
  );
  if (today) setMargin(sec, today);
}

function renderEngine(ch) {
  const body = document.getElementById("nm-engine-body");
  if (!body) return;
  const k = engineKey(ch);
  if (!k) { body.innerHTML = ch ? '<p class="nm-note">No score is on record yet.</p>' : notServed("The engine’s score"); return; }
  const rows = k.rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="n">${r.score != null ? esc(one(r.score)) : "—"}</td><td class="muted">${esc(r.note)}</td></tr>`).join("");
  body.innerHTML = `<p class="nm-key">${k.key}</p>` + (rows ? `<table data-src="api_character.pillars[]"><thead><tr><th>area</th><th>score</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : "");
}

/** The page's last entry (R7 fix 10): the two dated things to come back for — the next write-up
 *  (a held draft's served words win) and the next weigh-in, in the one spelling every v7 page
 *  uses. { html, day } — html "" when neither is served. */
export function nextEntry({ cad, pending, journey, clock }) {
  const lines = [];
  const wu = nextWriteUpLine(cad, pending);
  if (wu) lines.push(`<p class="nm-small" data-src="${pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date"}">${esc(wu)}</p>`);
  const w = nextWeighInLine(journey, clock);
  if (w.text) {
    const t = w.text.charAt(0).toUpperCase() + w.text.slice(1);
    lines.push(`<p class="nm-small">${esc(t).replace(esc(dayInWords(w.day)), `<time datetime="${esc(w.day)}" data-src="api_journey.journey.last_weighin_date">${esc(dayInWords(w.day))}</time>`)}.</p>`);
  }
  const c = cad && cad.chronicle;
  const day = (pending && pending.expected_date) || (c && !c.paused && c.next_date) || w.day || "";
  return { html: lines.join(""), day };
}

function renderNext({ cad, pending, journey, clock }) {
  const sec = document.getElementById("nm-next");
  if (!sec) return;
  const n = nextEntry({ cad, pending, journey, clock });
  if (!n.html) return fill(sec, cad && journey ? '<p class="nm-note">Nothing is scheduled.</p>' : notServed("What comes next"));
  fill(sec, n.html);
  if (n.day) setMargin(sec, n.day);
}

async function main() {
  const [journey, wp, sleep, nut, training, labs, freshness, pulse, character, cad, postsJson] = await Promise.all([
    tryJSON("/api/journey"),
    tryJSON("/api/weight_progress"),
    tryJSON("/api/sleep_detail"),
    tryJSON("/api/nutrition_overview"),
    tryJSON("/api/training_overview"),
    tryJSON("/api/labs"),
    tryJSON("/api/source_freshness"),
    tryJSON("/api/pulse"),
    tryJSON("/api/character"),
    tryJSON("/api/content_cadence"),
    tryJSON("/journal/posts.json"),
  ]);
  const j = journey && journey.journey;
  const through = j && j.last_weighin_date;
  const thr = document.getElementById("nm-through");
  if (thr) thr.textContent = dataThrough(through);
  const today = (freshness && freshness.pacific_today) || through || "";
  renderWeight(journey, wp, today);
  renderSleep(sleep);
  renderEating(nut);
  renderTraining(training, j && j.started_date);
  renderLabs(labs);
  renderAbsent(freshness, pulse);
  renderEngine(character);
  renderNext({ cad, pending: postsJson && postsJson.pending, journey, clock: (pulse && pulse.pulse && pulse.pulse.date) || today });
}

if (typeof document !== "undefined" && document.getElementById("nm-weight")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}

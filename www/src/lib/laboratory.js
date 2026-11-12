// The Laboratory's words and figures (L1, built dark — src/lib/lab.js). Pure functions over the snapshot's lab.json
// and its series files; no DOM, no clock, nothing computed that a page would present as a statistic (README
// requirement A): every effect, interval, arm size and verdict is carried as /api/hypotheses served it. What this
// module does is put those served fields into plain words, and lay the served readings on a dated axis.
// Proven by tests/laboratory.test.mjs.
import { svgChart } from "./chart.js";
import { dayInWords, num } from "./format.js";

/** The hypothesis engine's metric names in words, with their units (a name not listed falls back to its words). */
export const METRIC_WORDS = {
  protein_g: ["protein", "g"],
  carbs_g: ["carbohydrate", "g"],
  fat_g: ["fat", "g"],
  calories: ["calories", "kcal"],
  recovery: ["recovery score", "points"],
  hrv: ["heart-rate variability", "ms"],
  rhr: ["resting heart rate", "bpm"],
  sleep_score: ["sleep score", "points"],
  sleep_efficiency: ["sleep efficiency", "points"],
  sleep_onset_min: ["time to fall asleep", "minutes"],
  total_sleep_hrs: ["sleep", "hours"],
  daylight_min: ["daylight", "minutes"],
  cardio_7d_min: ["cardio over the past seven days", "minutes"],
  zone2_7d_min: ["zone 2 over the past seven days", "minutes"],
  vo2max: ["VO2 max", "ml/kg/min"],
  steps: ["steps", "steps"],
  weight_lbs: ["weight", "lb"],
};

export function metricWords(m) {
  return (METRIC_WORDS[m] || [String(m || "a metric").replace(/_/g, " ")])[0];
}

export function metricUnit(m, served = null) {
  return served || (METRIC_WORDS[m] || [null, ""])[1] || "";
}

/** Signed number in words: "+6.8", "−1.4" (a true minus sign). */
export function signed(v, decimals = 1) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${num(Math.abs(n), decimals)}`;
}

/** The ISO day `n` days after `iso` (negative = before). Pure date arithmetic, UTC. */
export function addDays(iso, n) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** The condition of a test in words — its arm, as the frozen spec states it. */
export function conditionWords(spec) {
  if (!spec || !spec.condition_metric) return "a condition the platform did not serve";
  const what = metricWords(spec.condition_metric);
  const unit = metricUnit(spec.condition_metric);
  if (spec.condition_op === "<=" && spec.condition_threshold != null) return `days with ${what} at or below ${num(spec.condition_threshold)} ${unit}`.trim();
  if (spec.condition_op === ">=" && spec.condition_threshold != null) return `days with ${what} at or above ${num(spec.condition_threshold)} ${unit}`.trim();
  if (spec.condition_op === "median_split") return `days with more ${what} than the window's median`;
  return `days marked by ${what}`;
}

/** One plain sentence for a pre-registered test: "On days with protein at or below 120 g, recovery score a day later is lower." */
export function testSentence(t) {
  const s = (t && t.spec) || null;
  if (!s || !s.outcome_metric) return t && t.statement ? t.statement : "A test whose specification was not served.";
  const lag = s.lag_days ? (s.lag_days === 1 ? " a day later" : ` ${num(s.lag_days)} days later`) : " the same day";
  const dir = s.direction === "lower" ? "lower" : s.direction === "higher" ? "higher" : "different";
  const cond = conditionWords(s);
  return `On ${cond}, ${metricWords(s.outcome_metric)}${lag} is ${dir} than on the other days.`;
}

/** The minimum effect in words, with where the number came from (its served provenance kind). */
export function minEffectText(t) {
  const s = (t && t.spec) || {};
  if (s.min_effect == null) return "No minimum effect was served for this test.";
  const unit = metricUnit(s.outcome_metric, s.min_effect_unit);
  const bar = `${num(s.min_effect, 2)} ${unit}`.trim();
  if (s.min_effect_kind === "personal_derivation" && s.baseline_window_days && s.baseline_sd != null)
    return `${bar} — set from his own day-to-day variation in the ${num(s.baseline_window_days)} days before the test was written (spread ${num(s.baseline_sd, 2)} ${unit}${s.baseline_n ? `, ${num(s.baseline_n)} days` : ""}).`;
  if (s.min_effect_kind === "population_constant") return `${bar} — a fixed value written into the test, not derived from his data.`;
  if (s.min_effect_kind === "model_proposed") return `${bar} — proposed when the test was written, not derived from his data.`;
  return `${bar}.`;
}

/** The stopping rule as the engine applies it (hypothesis_engine_lambda.evaluate_test_spec), with the served numbers. */
export function ruleText(t) {
  const s = (t && t.spec) || {};
  const per = t && t.min_days_per_arm != null ? num(t.min_days_per_arm) : null;
  const win = t && t.monitoring_window_days != null ? num(t.monitoring_window_days) : null;
  const parts = [];
  if (win) parts.push(`checked weekly over a ${win}-day window from the day it was written`);
  if (per) parts.push(`each side needs at least ${per} days before any difference is computed`);
  parts.push(
    `supported only when the 95% interval of the difference sits wholly on the predicted side of zero and the difference is at least the minimum effect; contradicted when it sits wholly on the other side; otherwise inconclusive`,
  );
  if (s.lag_days) parts.push(`each day is paired with the outcome ${s.lag_days === 1 ? "one day" : `${num(s.lag_days)} days`} later`);
  return parts.join("; ") + ".";
}

/** The verdict in words, with the honest reason when there is no result. */
export function verdictOf(t) {
  if (!t) return { key: "none", word: "No result yet", reason: "" };
  if (t.status === "archived") {
    const v = t.verdict ? verdictOf({ ...t, status: "pending" }) : null;
    return { key: "retired", word: "Retired", reason: v && v.key !== "none" ? `Last check: ${v.word.toLowerCase()}. ${v.reason}`.trim() : "Retired before a check was recorded." };
  }
  if (!t.verdict) return { key: "none", word: "Not checked yet", reason: "The weekly check has not graded this test yet." };
  if (t.verdict === "supported") return { key: "supported", word: "Supported", reason: "The interval sits on the predicted side of zero and clears the minimum effect." };
  if (t.verdict === "contradicted") return { key: "contradicted", word: "Contradicted", reason: "The interval sits on the opposite side of zero." };
  const per = t.min_days_per_arm;
  const nc = t.n_condition;
  const no = t.n_comparison;
  // the engine splits the days only once it has two sides' worth of paired days; before that it serves 0 and 0
  if (per != null && t.days_observed != null && t.days_observed < 2 * per && !nc && !no)
    return {
      key: "insufficient",
      word: "Insufficient data",
      reason: `${num(t.days_observed)} paired ${t.days_observed === 1 ? "day" : "days"} so far; the check splits them only once there are ${num(2 * per)} (${num(per)} a side).`,
    };
  if (per != null && nc != null && no != null && (nc < per || no < per))
    return {
      key: "insufficient",
      word: "Insufficient data",
      reason: `${num(nc)} ${nc === 1 ? "day" : "days"} on the test side and ${num(no)} on the other; each needs ${num(per)}.`,
    };
  if (t.ci95_low == null) return { key: "insufficient", word: "Insufficient data", reason: "No interval could be computed from the days so far." };
  return { key: "inconclusive", word: "Inconclusive", reason: "The interval still includes zero." };
}

/** The served effect and its interval in words, or null when none was served. */
export function intervalText(t) {
  if (!t || t.effect_size == null) return null;
  const unit = metricUnit(t.spec && t.spec.outcome_metric, t.spec && t.spec.min_effect_unit);
  const ci = t.ci95_low != null && t.ci95_high != null ? ` (95% interval ${signed(t.ci95_low, 1)} to ${signed(t.ci95_high, 1)})` : "";
  return `${signed(t.effect_size, 1)} ${unit}${ci}`.replace(/\s+\(/, " (");
}

/** The interval as a figure: one horizontal bar on a symmetric axis with zero and the minimum effect marked. */
export function intervalFigure(t, { width = 600 } = {}) {
  if (!t || t.ci95_low == null || t.ci95_high == null || t.effect_size == null) return null;
  const me = t.spec && t.spec.min_effect != null ? Math.abs(t.spec.min_effect) : 0;
  const span = Math.max(Math.abs(t.ci95_low), Math.abs(t.ci95_high), me) * 1.15 || 1;
  const W = width;
  const H = 84;
  const pad = 16;
  const x = (v) => pad + ((v + span) / (2 * span)) * (W - 2 * pad);
  const fs = 12.5;
  const lab = (v, text, anchor, y) =>
    `<text x="${x(v).toFixed(1)}" y="${y}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#5C5C58">${text}</text>`;
  let g = `<line x1="${pad}" y1="44" x2="${W - pad}" y2="44" stroke="#C9C9C3" stroke-width="1"/>`;
  g += `<line x1="${x(0).toFixed(1)}" y1="24" x2="${x(0).toFixed(1)}" y2="62" stroke="#121212" stroke-width="1"/>` + lab(0, "0", "middle", 78);
  if (me) {
    const side = t.spec.direction === "lower" ? -me : me;
    g += `<line x1="${x(side).toFixed(1)}" y1="24" x2="${x(side).toFixed(1)}" y2="62" stroke="#121212" stroke-width="1" stroke-dasharray="3 4"/>`;
    // the label reads toward zero, so it never leaves the frame (the bar's span is padded past the needed mark)
    g += lab(side, `${signed(side, 1)} needed`, side < 0 ? "start" : "end", 18);
  }
  g += `<line x1="${x(t.ci95_low).toFixed(1)}" y1="44" x2="${x(t.ci95_high).toFixed(1)}" y2="44" stroke="#1B3FD6" stroke-width="6" stroke-linecap="round"/>`;
  g += `<circle cx="${x(t.effect_size).toFixed(1)}" cy="44" r="6" fill="#F4F4F0" stroke="#1B3FD6" stroke-width="2"/>`;
  const aria = `Difference ${signed(t.effect_size, 1)}, 95% interval ${signed(t.ci95_low, 1)} to ${signed(t.ci95_high, 1)}${me ? `, minimum effect ${num(me, 2)}` : ""}`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${aria}">${g}</svg>`;
}

/** The test's three dates: the start of the baseline the minimum effect was set from, the day it was written, the window's end. */
export function testDates(t) {
  const pre = t && t.pre_registered;
  if (!pre) return null;
  const base = t.spec && t.spec.baseline_window_days ? addDays(pre, -t.spec.baseline_window_days) : null;
  const end = t.monitoring_window_days ? addDays(pre, t.monitoring_window_days) : null;
  return { baselineFrom: base, preRegistered: pre, windowEnd: end };
}

/** A series' days within [from, to] (inclusive; either bound may be null = open). */
export function between(days, from, to) {
  return (days || []).filter((d) => (!from || d.date >= from) && (!to || d.date <= to));
}

/**
 * The baseline → window figure's options: the served daily readings from the baseline's start (or the test's day when
 * no baseline is served) to the window's end or the series' last day, with the test's day and the window's end marked.
 * Returns null when the series is absent or no reading falls in the range — the page then says so.
 */
export function windowChartOptions(t, series, role = "outcome") {
  const dates = testDates(t);
  if (!dates || !series || !Array.isArray(series.days)) return null;
  const from = dates.baselineFrom || dates.preRegistered;
  const days = between(series.days, from, dates.windowEnd);
  if (!days.some((d) => d.value != null && !d.gap)) return null;
  const markers = [{ date: dates.preRegistered, label: "test written" }];
  if (dates.windowEnd && days.some((d) => d.date === dates.windowEnd)) markers.push({ date: dates.windowEnd, label: "window ends" });
  const spec = t.spec || {};
  const metric = role === "outcome" ? spec.outcome_metric : spec.condition_metric;
  const dashed = role === "condition" && (spec.condition_op === "<=" || spec.condition_op === ">=") ? spec.condition_threshold : null;
  return {
    series: [{ days, color: role === "outcome" ? "#1B3FD6" : "#121212", name: metricWords(metric) }],
    unit: series.unit || metricUnit(metric),
    decimals: series.decimals == null ? 0 : series.decimals,
    markers,
    dashed,
    labelDay: (iso) => dayInWords(iso, { short: true }),
    aria: `${metricWords(metric)}, ${dayInWords(days[0].date)} to ${dayInWords(days[days.length - 1].date)}, the day the test was written marked${dashed != null ? `, the pre-registered line at ${num(dashed)} dashed` : ""}`,
  };
}

/** Draw a window chart (build: desktop width; the island redraws at the container's width on a phone). */
export function windowChart(opts, { mobile = false, width } = {}) {
  if (!opts) return "";
  const labelDay = (iso) => dayInWords(iso, { short: true });
  return svgChart({ ...opts, labelDay, mobile, width });
}

/**
 * Days by side, for the compliance strip: each served reading of the condition metric inside the test's window, and
 * which side of the PRE-REGISTERED line it fell on. Not the engine's arm count (it pairs each day with a later outcome
 * and drops days without both; that count is served as n_condition / n_comparison). A median split has no served
 * line, so every day's side is null.
 */
export function daysBySide(t, series) {
  const dates = testDates(t);
  if (!dates || !series) return [];
  const spec = t.spec || {};
  const thr = spec.condition_threshold;
  const op = spec.condition_op;
  return between(series.days, dates.preRegistered, dates.windowEnd).map((d) => {
    const v = d.gap ? null : d.value;
    let side = null;
    if (v != null && thr != null && op === "<=") side = v <= thr ? "test" : "other";
    if (v != null && thr != null && op === ">=") side = v >= thr ? "test" : "other";
    return { date: d.date, value: v, gap: Boolean(d.gap), side };
  });
}

/** The index's counts, carried from the data file (a count of the served rows, nothing more). */
export function labCounts(lab) {
  const xs = (lab && lab.lab_experiments) || [];
  const ts = (lab && lab.lab_tests) || [];
  const by = (g) => xs.filter((x) => x.group === g).length;
  return {
    running: by("running"),
    ready: by("ready"),
    backlog: by("backlog"),
    done: by("done"),
    testsOpen: ts.filter((t) => t.status !== "archived").length,
    testsRetired: ts.filter((t) => t.status === "archived").length,
  };
}

/** The pillar words for the backlog groups. */
export function pillarWords(p) {
  return p ? p.charAt(0).toUpperCase() + p.slice(1) : "Unfiled";
}

/** The backlog grouped by pillar, groups and members in a stable order. */
export function byPillar(experiments) {
  const m = new Map();
  for (const x of experiments) {
    const k = x.pillar || "";
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(x);
  }
  return [...m.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([pillar, items]) => ({ pillar, items: items.sort((a, b) => (a.name < b.name ? -1 : 1)) }));
}

/** "2026-W45" → "2026-11-02", the ISO week's Monday (null for anything else). */
export function weekMonday(w) {
  const m = /^(\d{4})-W(\d{2})$/.exec(String(w || ""));
  if (!m) return null;
  const y = Number(m[1]);
  const wk = Number(m[2]);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const monday = new Date(jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * 86400000 + (wk - 1) * 7 * 86400000);
  return monday.toISOString().slice(0, 10);
}

/** "2026-W45" → "the week of 2 November 2026" (ISO week, Monday); `short` → "week of 2 Nov". */
export function weekWords(w, { short = false } = {}) {
  const monday = weekMonday(w);
  if (!monday) return w || "an unnamed week";
  return short ? `week of ${dayInWords(monday, { short: true })}` : `the week of ${dayInWords(monday)}`;
}

/**
 * PRIVACY (owner rulings 2026-11-03/05/06; fail closed). Two metrics the weekly correlation run names changed METHOD:
 * the day grade (method 1 carries a journal component, scoring_engine.score_journal; the public grade is
 * health.day_grade_public) and habit completion (method 1 counted the journal habits; the public share is
 * health.habit_pct_public). A week computed before the public method correlated the private-by-inference version and
 * is never shown — not its r, not that it was listed, not a count. A finding naming either metric renders only with
 * the public method's stamp, carried from the record (common.activity_publication.PUBLIC_METRIC_METHODS — the same
 * versions, pinned equal by tests/test_lab_findings_over_time.py). Matched broadly: "Day grade", "habits", any case.
 */
export const PUBLIC_METHODS = { day_grade: ["day-grade-public-v1"], habit_pct: ["habit-pct-public-v1"] };
const METHOD_VERSIONED = [
  [/grade/i, "day_grade"],
  [/habit/i, "habit_pct"],
];

/** The method-versioned metric keys a finding names (a label or a key). */
function versionedKeys(f) {
  const keys = [];
  for (const name of [f && f.metric_a, f && f.metric_b]) for (const [rx, key] of METHOD_VERSIONED) if (rx.test(String(name || ""))) keys.push(key);
  return keys;
}

/** May this finding be shown? Every method-versioned metric it names carries its public method stamp. */
export function findingIsPublic(f) {
  if (!f || typeof f !== "object") return false;
  const stamps = f.methods && typeof f.methods === "object" ? f.methods : {};
  return versionedKeys(f).every((k) => (PUBLIC_METHODS[k] || []).includes(stamps[k]));
}

/**
 * The newest week's findings, each with how many weeks listed the same pair (`seen`) out of the weeks it could have
 * been listed in (`of`): every served week, or for a pair naming a method-versioned metric the weeks from the first
 * week its public method was stamped (never a week whose private-method record was withheld).
 */
export function latestFindings(findings) {
  const fs = (findings || []).filter(findingIsPublic);
  if (!fs.length) return { week: null, items: [], weeks: 0 };
  const weeks = [...new Set(fs.map((f) => f.week))].sort();
  const latest = weeks[weeks.length - 1];
  const key = (f) => `${f.metric_a}|${f.metric_b}`;
  const seen = new Map();
  for (const f of fs) seen.set(key(f), (seen.get(key(f)) || 0) + 1);
  const first = {};
  for (const f of fs) for (const k of versionedKeys(f)) if (!first[k] || f.week < first[k]) first[k] = f.week;
  const of = (f) => {
    const from = versionedKeys(f).reduce((m, k) => (first[k] > m ? first[k] : m), "");
    return weeks.filter((w) => w >= from).length;
  };
  const items = fs.filter((f) => f.week === latest).map((f) => ({ ...f, seen: seen.get(key(f)), of: of(f) }));
  items.sort((a, b) => Math.abs(b.r || 0) - Math.abs(a.r || 0));
  return { week: latest, items, weeks: weeks.length };
}

/** One finding in words: "HRV and recovery score moved together: r = +0.65 (95% interval +0.46 to +0.78), about 54 independent days." */
export function findingText(f) {
  const together = f.r != null && f.r < 0 ? "moved in opposite directions" : "moved together";
  const ci = f.ci95_low != null && f.ci95_high != null ? ` (95% interval ${signed(f.ci95_low, 2)} to ${signed(f.ci95_high, 2)})` : "";
  const neff = f.n_eff != null ? `, about ${num(f.n_eff)} independent days of ${num(f.n)}` : f.n != null ? `, ${num(f.n)} days` : "";
  return `${labelWords(f.metric_a)} and ${labelWords(f.metric_b)} ${together}: r = ${signed(f.r, 2)}${ci}${neff}.`;
}

/** A served metric label in words: the engine sometimes serves a key ("training_mins", "readiness") where a label belongs. */
export function labelWords(s) {
  const raw = String(s || "");
  if (!/_|^[a-z]/.test(raw)) return raw;
  const w = raw.replace(/_mins?$/, " minutes").replace(/_/g, " ");
  return w.charAt(0).toUpperCase() + w.slice(1);
}

/** A protocol's evidence split by the stance its sources were filed under. */
export function evidenceSplit(sources) {
  const s = sources || [];
  return { supports: s.filter((x) => x.stance === "supports"), challenges: s.filter((x) => x.stance === "challenges"), other: s.filter((x) => x.stance !== "supports" && x.stance !== "challenges") };
}

/** Served prose with every ISO date written in words (an ISO date on a page is a defect; the text is otherwise as served). */
export function prose(s) {
  if (s == null) return s;
  return String(s).replace(/\b(\d{4}-\d{2}-\d{2})(?:T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\b/g, (m, d) => dayInWords(d) || m);
}

/** The status word of an experiment group. */
export const GROUP_WORDS = { running: "Running", ready: "Ready to start", backlog: "In the backlog", done: "Finished" };

/**
 * Does this experiment earn a page of its own? (2026-11-09 readiness review: no empty shells.) A backlog entry that has
 * never run is a library card — its name, claim, evidence and source sit in the index's backlog list, and a page would
 * only repeat "not yet" four times. Running, ready and finished experiments, and anything with a served run, get one.
 */
export function experimentHasPage(x) {
  return Boolean(x) && (x.group !== "backlog" || Boolean(x.run));
}

/** Does this test earn a page? A test retired before any check was recorded has nothing to show beyond its sentence. */
export function testHasPage(t) {
  return Boolean(t) && !(t.status === "archived" && !t.verdict && !(t.check_count > 0));
}

/** True when a served interval sits wholly on one side of zero. */
function clearOfZero(f) {
  return f != null && f.ci95_low != null && f.ci95_high != null && (f.ci95_low > 0 || f.ci95_high < 0);
}

/** "the weeks of 19 and 26 Oct" / "the week of 2 Nov" — a list of served weeks in words. */
export function weeksInWords(ws) {
  const ds = (ws || []).map((w) => dayInWords(weekMonday(w), { short: true }) || w);
  if (!ds.length) return "";
  if (ds.length === 1) return `the week of ${ds[0]}`;
  return `the weeks of ${ds.slice(0, -1).join(", ")} and ${ds[ds.length - 1]}`;
}

/**
 * One pair's record across the weekly runs, in one honest line. The claim "held in N of N weeks" is made ONLY when the
 * pair was listed every week in its window AND every listed week's 95% interval excludes zero on the same side;
 * otherwise the line says what happened: the weeks it was not listed, the weeks its interval reached zero, or that it
 * changed direction. Nothing is recomputed — r and its interval are as served; this only counts and words them.
 */
export function stabilitySummary(p) {
  const listed = p.weeks.filter((w) => w.finding).map((w) => w.finding);
  const n = p.weeks.length;
  const missing = p.weeks.filter((w) => !w.finding).map((w) => w.week);
  const reached = p.weeks.filter((w) => w.finding && !clearOfZero(w.finding)).map((w) => w.week);
  const rs = listed.map((f) => f.r).filter((r) => r != null);
  const signs = new Set(rs.map((r) => Math.sign(r)).filter((x) => x !== 0));
  const lo = rs.length ? Math.min(...rs) : null;
  const hi = rs.length ? Math.max(...rs) : null;
  const range = lo == null ? "" : lo === hi ? `r = ${signed(lo, 2)}` : `r from ${signed(lo, 2)} to ${signed(hi, 2)}`;
  if (signs.size > 1) return { key: "flipped", text: `Changed direction: ${range} across the ${num(listed.length)} weeks it was listed.` };
  if (!missing.length && !reached.length && listed.length === n && n > 0)
    return { key: "held", text: `Held in ${num(n)} of ${num(n)} weeks: ${range}, every week's 95% interval clear of zero.` };
  const parts = [`Listed in ${num(listed.length)} of ${num(n)} weeks`];
  if (missing.length) parts.push(`not listed in ${weeksInWords(missing)}`);
  parts.push(reached.length ? `its interval reached zero in ${weeksInWords(reached)}` : `clear of zero each week it was listed (${range})`);
  return { key: reached.length ? "reached" : "partial", text: `${parts.join("; ")}.` };
}

/**
 * Findings over time: every pair the weekly correlation run listed in MORE THAN ONE served week, each with its week by
 * week finding (or null when that week's run did not list it) and its one-line summary. Only public findings
 * (findingIsPublic); a pair naming a method-versioned metric is counted over the weeks from the first week its public
 * method was stamped, never over weeks whose private-method record was withheld. Strongest record first.
 */
export function findingsOverTime(findings) {
  const fs = (findings || []).filter((f) => findingIsPublic(f) && /^\d{4}-W\d{2}$/.test(String(f.week || "")));
  const weeks = [...new Set(fs.map((f) => f.week))].sort();
  const first = {};
  for (const f of fs) for (const k of versionedKeys(f)) if (!first[k] || f.week < first[k]) first[k] = f.week;
  const groups = new Map();
  for (const f of fs) {
    const key = `${f.metric_a}|${f.metric_b}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(f);
  }
  const RANK = { held: 0, partial: 1, reached: 2, flipped: 3 };
  const pairs = [];
  for (const [key, items] of groups) {
    const from = versionedKeys(items[0]).reduce((m, k) => (first[k] > m ? first[k] : m), "");
    const window = weeks.filter((w) => w >= from);
    const byWeek = new Map(items.map((f) => [f.week, f]));
    const perWeek = window.map((w) => ({ week: w, finding: byWeek.get(w) || null }));
    const listed = perWeek.filter((w) => w.finding).length;
    if (listed < 2) continue;
    const p = { key, metric_a: items[0].metric_a, metric_b: items[0].metric_b, weeks: perWeek, listed, from: from || null };
    p.summary = stabilitySummary(p);
    pairs.push(p);
  }
  const latestR = (p) => Math.abs((p.weeks.filter((w) => w.finding).pop() || {}).finding.r || 0);
  pairs.sort((a, b) => RANK[a.summary.key] - RANK[b.summary.key] || b.listed - a.listed || latestR(b) - latestR(a) || (a.key < b.key ? -1 : 1));
  const newest = fs.filter((f) => f.week === weeks[weeks.length - 1] && f.window_start && f.window_end)[0] || null;
  return { weeks, pairs, window: newest ? { start: newest.window_start, end: newest.window_end } : null };
}

/** A pair's name in words: "HRV and recovery". */
export function pairWords(p) {
  return `${labelWords(p.metric_a)} and ${labelWords(p.metric_b)}`;
}

/**
 * One pair's small multiple: r with its 95% interval for each week of its window, on ONE fixed axis from −1 to +1 shared
 * by every multiple (so a reader compares pairs by eye honestly), zero drawn, a week the run did not list marked
 * "not listed" at zero. Carries data-points for the inspector. `width` is the viewBox width — on a phone the island
 * passes the container's width, so the 12.5-unit text stays ≥ 11 px (#1210).
 */
export function stabilityFigure(p, { width = 340 } = {}) {
  if (!p || !p.weeks || !p.weeks.length) return "";
  const W = Math.max(240, Math.round(width));
  const H = 168;
  const padL = 34;
  const padR = 12;
  const padT = 12;
  const padB = 30;
  const n = p.weeks.length;
  const x = (i) => padL + ((i + 0.5) / n) * (W - padL - padR);
  const y = (r) => padT + ((1 - r) / 2) * (H - padT - padB);
  const fs = 12.5;
  const text = (tx, ty, s, anchor = "middle", fill = "#5C5C58") =>
    `<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="${fill}">${s}</text>`;
  let g = "";
  for (const v of [1, -1]) g += `<line x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}" stroke="#E2E2DC" stroke-width="1"/>`;
  g += `<line x1="${padL}" y1="${y(0).toFixed(1)}" x2="${W - padR}" y2="${y(0).toFixed(1)}" stroke="#121212" stroke-width="1"/>`;
  g += text(padL - 6, y(1) + 4, "+1", "end") + text(padL - 6, y(0) + 4, "0", "end") + text(padL - 6, y(-1) + 4, "−1", "end");
  const points = [];
  p.weeks.forEach((w, i) => {
    const cx = x(i);
    const day = dayInWords(weekMonday(w.week), { short: true }) || w.week;
    g += text(cx, H - 9, day);
    const f = w.finding;
    if (!f || f.r == null) {
      g += `<line x1="${(cx - 7).toFixed(1)}" y1="${y(0).toFixed(1)}" x2="${(cx + 7).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="#8A8A84" stroke-width="3" stroke-linecap="round"/>`;
      points.push({ x: Number(cx.toFixed(1)), y: Number(y(0).toFixed(1)), label: `Week of ${day}: not listed by that week's run` });
      return;
    }
    const clear = clearOfZero(f);
    const ink = clear ? "#1B3FD6" : "#8A8A84";
    if (f.ci95_low != null && f.ci95_high != null)
      g += `<line x1="${cx.toFixed(1)}" y1="${y(f.ci95_high).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${y(f.ci95_low).toFixed(1)}" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>`;
    g += `<circle cx="${cx.toFixed(1)}" cy="${y(f.r).toFixed(1)}" r="5.5" fill="#F4F4F0" stroke="${ink}" stroke-width="2"/>`;
    const ci = f.ci95_low != null && f.ci95_high != null ? ` (95% interval ${signed(f.ci95_low, 2)} to ${signed(f.ci95_high, 2)})` : " (no interval served)";
    const neff = f.n_eff != null ? `, about ${num(f.n_eff)} independent days` : "";
    points.push({ x: Number(cx.toFixed(1)), y: Number(y(f.r).toFixed(1)), label: `Week of ${day}: r ${signed(f.r, 2)}${ci}${neff}` });
  });
  const aria = `${pairWords(p)}, r with its 95% interval in each of ${num(n)} weekly runs, on an axis from −1 to +1. ${p.summary ? p.summary.text : ""}`;
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}" data-chart data-points="${esc(JSON.stringify(points))}">${g}</svg>`;
}

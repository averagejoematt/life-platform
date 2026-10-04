// ck_depth.js — the detail layer of the living front page (#4586, epic #4580): a page per
// DAY and a page per TREND, in the kit and nothing else.
//
// Two rules carry the site's depth without a page per topic:
//   1. a day opens to everything recorded that day — what was lifted (every exercise,
//      sets, reps and load), what was eaten (calories and macros), sleep, recovery, steps;
//   2. every number on a day is a door to that number over the whole experiment.
// So the front page stays simple, a day is one tap away and a trend is two.
//
// Each page has its own address (`?d=2026-10-03`, `?m=steps`, `?m=lift&x=Squat (Barbell)`)
// so it can be linked and shared. Everything shown is read from routes the site already
// serves; a measure with no reading says so and is never drawn as a zero. Individual food
// log entries are owner-only, so a day shows that day's totals and the food trend shows
// the served summary of frequent meals.
//
// The builders are pure and exported for tests/js/ck_depth_4586.test.mjs; mount() is the
// only thing that touches the DOM.
import { tryJSON, esc, fmtShort } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";

const LB_PER_KG = 2.20462;
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
const whole = (v) => (num(v) === null ? "" : Math.round(v).toLocaleString("en-US"));
const lb = (kg) => (num(kg) === null ? null : Math.round(kg * LB_PER_KG));
const soft = (t) => (t ? `<p class="ck-soft">${esc(t)}</p>` : "");
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const isDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));
const byDate = (rows) => Object.fromEntries((rows || []).filter((r) => r && isDay(r.date)).map((r) => [r.date, r]));
const shift = (iso, days) => new Date(Date.parse(`${iso}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);

// ── the measures a trend page can show ─────────────────────────────────────────
// key -> its name, unit, where its daily values come from and how a value is written.
export const MEASURES = {
  weight: { name: "Weight", unit: "lb", write: (v) => `${v.toFixed(1)} lb`, about: "Every weigh-in since the start." },
  steps: { name: "Steps", unit: "steps", write: (v) => whole(v), about: "Steps counted each day." },
  sleep: { name: "Sleep", unit: "hours", write: (v) => `${trim1(v)} hours`, about: "Hours asleep each night." },
  recovery: { name: "Recovery", unit: "out of 100", write: (v) => `${whole(v)} out of 100`, about: "My wrist strap’s morning score out of 100." },
  protein: { name: "Protein", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of protein logged each day." },
  calories: { name: "Calories", unit: "kcal", write: (v) => `${whole(v)} kcal`, about: "Calories logged each day." },
  carbs: { name: "Carbs", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of carbohydrate logged each day." },
  fat: { name: "Fat", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of fat logged each day." },
  training: { name: "Training time", unit: "minutes", write: (v) => `${whole(v)} minutes`, about: "Minutes of training recorded each day." },
};

export const trendHref = (base, measure, lift) => `${base}trend/?m=${encodeURIComponent(measure)}${lift ? `&x=${encodeURIComponent(lift)}` : ""}`;
export const dayHref = (base, iso) => `${base}day/?d=${encodeURIComponent(iso)}`;

// One {date, value} series for a measure from the served bodies. Null readings are dropped:
// a day with no value is a gap in the line, never a zero.
export function seriesOf(measure, src, today = "") {
  const pick = (rows, field) => (rows || []).filter((r) => r && isDay(r.date) && num(r[field]) !== null).map((r) => ({ date: r.date, value: r[field] }));
  const pulse = src.pulse && src.pulse.pulse_history;
  const food = src.nutrition && src.nutrition.nutrition_trend;
  const out =
    {
      weight: () => pick(pulse, "weight_lbs"),
      steps: () => pick(pulse, "steps").filter((p) => p.date !== today),
      sleep: () => pick(pulse, "sleep_hours"),
      recovery: () => pick(pulse, "recovery_pct"),
      protein: () => pick(food, "protein_g"),
      calories: () => pick(food, "calories"),
      carbs: () => pick(food, "carbs_g"),
      fat: () => pick(food, "fat_g"),
      training: () => pick(src.training && src.training.daily_modality_minutes_30d, "total_min").filter((p) => p.date !== today || p.value > 0),
    }[measure] || (() => []);
  return out().sort((a, b) => a.date.localeCompare(b.date));
}

// ── a lift ─────────────────────────────────────────────────────────────────────
// A session's working sets for one exercise (warm-ups set aside), heaviest load first in
// the summary: "3 sets at 175 lb: 12, 12 and 10 reps".
const isWork = (s) => s && s.type !== "warmup" && num(s.reps) !== null;
export function liftSummary(exercise) {
  const sets = (exercise.sets || []).filter(isWork);
  const warm = (exercise.sets || []).length - sets.length;
  if (!sets.length) return warm ? `${warm} warm-up ${warm === 1 ? "set" : "sets"} only.` : "";
  const groups = [];
  for (const s of sets) {
    const load = lb(s.weight_kg);
    const g = groups.find((x) => x.load === load);
    if (g) g.reps.push(Math.round(s.reps));
    else groups.push({ load, reps: [Math.round(s.reps)] });
  }
  const words = (list) => (list.length < 2 ? String(list[0]) : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`);
  return groups
    .map((g) => {
      const n = `${g.reps.length} ${g.reps.length === 1 ? "set" : "sets"}`;
      const at = g.load ? ` at ${g.load} lb` : "";
      return `${n}${at}: ${words(g.reps)} reps`;
    })
    .join("; ");
}
// The heaviest working load for one exercise in each session it appears in.
export function liftSeries(workouts, name) {
  return (workouts || [])
    .map((w) => {
      const ex = (w.exercises || []).find((e) => e && e.name === name);
      const loads = ex ? (ex.sets || []).filter(isWork).map((s) => lb(s.weight_kg)).filter((v) => v) : [];
      return loads.length && isDay(w.date) ? { date: w.date, value: Math.max(...loads) } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ── the chart: one line, both ends labelled, and a sentence saying what it shows ─
export function trendChartHTML(points, write, name) {
  const pts = (points || []).filter((p) => p && isDay(p.date) && num(p.value) !== null);
  if (pts.length < 2) return "";
  const t = (iso) => Date.parse(`${iso}T12:00:00Z`);
  const [t0, t1] = [t(pts[0].date), t(pts[pts.length - 1].date)];
  const lo = Math.min(...pts.map((p) => p.value));
  const hi = Math.max(...pts.map((p) => p.value));
  const x = (p) => 8 + (624 * (t(p.date) - t0)) / (t1 - t0 || 1);
  const y = (p) => 20 + (122 * (hi - p.value)) / (hi - lo || 1);
  const line = pts.map((p) => `${x(p).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const [first, last] = [pts[0], pts[pts.length - 1]];
  const aria = `${name} from ${write(first.value)} on ${shortDay(first.date)} to ${write(last.value)} on ${shortDay(last.date)}, ${pts.length} readings, lowest ${write(lo)}, highest ${write(hi)}`;
  return `<svg class="ck-chart" viewBox="0 0 640 164" role="img" aria-label="${esc(aria)}"><polygon class="ck-chart__area" points="8.0,164 ${line} 632.0,164"/><polyline class="ck-chart__line" points="${line}"/><circle class="ck-chart__now" cx="${x(last).toFixed(1)}" cy="${y(last).toFixed(1)}" r="5"/></svg><div class="ck-ends"><span>${esc(`${shortDay(first.date)} · ${write(first.value)}`)}</span><span>${esc(`${shortDay(last.date)} · ${write(last.value)}`)}</span></div>`;
}
export function trendSentence(points, write) {
  const pts = points || [];
  if (!pts.length) return "";
  const values = pts.map((p) => p.value);
  const [lo, hi] = [Math.min(...values), Math.max(...values)];
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  if (pts.length === 1) return `One reading so far: ${write(pts[0].value)} on ${shortDay(pts[0].date)}.`;
  return `${pts.length} readings from ${shortDay(pts[0].date)} to ${shortDay(pts[pts.length - 1].date)}. Lowest ${write(lo)}, highest ${write(hi)}, average ${write(mean)}.`;
}
// The most recent readings, newest first, each a door to its day.
export function recentRowsHTML(points, write, base, limit = 10) {
  const rows = [...(points || [])].reverse().slice(0, limit);
  if (!rows.length) return "";
  return `<ul class="ck-rows ck-rows--chapters">${rows
    .map((p) => `<li><span class="ck-rows__key">${esc(fmtShort(p.date))}</span><a href="${esc(dayHref(base, p.date))}">${esc(dayInWords(p.date).split(",")[0])}</a><span class="ck-rows__value">${esc(write(p.value))}</span></li>`)
    .join("")}</ul>`;
}

// ── the day page ───────────────────────────────────────────────────────────────
export function latestDay(src) {
  const days = [...Object.keys(byDate(src.pulse && src.pulse.pulse_history)), ...Object.keys(byDate(src.workouts && src.workouts.workouts))].sort();
  return days[days.length - 1] || "";
}
// The day's measured facts, each a door to its trend. A measure with no reading is absent.
export function dayFactsHTML(iso, src, base) {
  const p = byDate(src.pulse && src.pulse.pulse_history)[iso] || {};
  const row = (measure, value) => {
    const m = MEASURES[measure];
    return num(value) === null ? "" : `<li><span class="ck-rows__key">${esc(m.name)}</span><a href="${esc(trendHref(base, measure))}">${esc(m.write(value))}</a><span class="ck-rows__value" aria-hidden="true">→</span></li>`;
  };
  const rows = [row("weight", p.weight_lbs), row("sleep", p.sleep_hours), row("recovery", p.recovery_pct), row("steps", p.steps)].join("");
  return rows ? `<ul class="ck-rows ck-rows--chapters">${rows}</ul>` : soft("Nothing was measured on this day.");
}
// What was lifted: every exercise with its working sets, each a door to that lift's trend.
export function dayLiftsHTML(iso, src, base) {
  const session = (src.workouts && src.workouts.workouts ? src.workouts.workouts : []).find((w) => w && w.date === iso);
  const minutes = byDate(src.training && src.training.daily_modality_minutes_30d)[iso];
  const other = minutes
    ? [["walking_min", "walking"], ["cycling_min", "cycling"], ["hiking_min", "hiking"], ["soccer_min", "soccer"], ["stretching_min", "stretching"]]
        .filter(([k]) => num(minutes[k]) && minutes[k] > 0)
        .map(([k, word]) => `${whole(minutes[k])} minutes of ${word}`)
    : [];
  const otherLine = other.length ? soft(`Also that day: ${other.join("; ")}.`) : "";
  if (!session || !(session.exercises || []).length) return otherLine || soft("No training was recorded on this day.");
  const named = session.exercises.filter((e) => e && e.name);
  const worked = named.filter((e) => (e.sets || []).some(isWork));
  // An entry with only warm-up sets (a few minutes on the bike, stretching) is named in one
  // line, not given a row that says nothing.
  const warm = named.filter((e) => !(e.sets || []).some(isWork)).map((e) => e.name);
  const warmLine = warm.length ? soft(`Warm-up: ${warm.join(", ")}.`) : "";
  const rows = worked
    .map((e) => `<li><a class="ck-coach__who" href="${esc(trendHref(base, "lift", e.name))}">${esc(e.name)}</a><span>${esc(liftSummary(e))}</span></li>`)
    .join("");
  const head = num(session.duration_min) !== null ? soft(`${whole(session.duration_min)} minutes, ${worked.length} ${worked.length === 1 ? "exercise" : "exercises"}. Each one opens its own trend.`) : "";
  return `${head}${rows ? `<ul class="ck-coach">${rows}</ul>` : ""}${warmLine}${otherLine}`;
}
// What was eaten: the day's totals. The log's individual entries are not public.
export function dayFoodHTML(iso, src, base) {
  const f = byDate(src.nutrition && src.nutrition.nutrition_trend)[iso];
  if (!f) return soft("No food was logged on this day.");
  const floor = num(src.nutrition && src.nutrition.nutrition && src.nutrition.nutrition.protein_floor_g);
  const row = (measure, value, note = "") => {
    const m = MEASURES[measure];
    return num(value) === null ? "" : `<li><span class="ck-rows__key">${esc(m.name)}</span><a href="${esc(trendHref(base, measure))}">${esc(m.write(value))}${esc(note)}</a><span class="ck-rows__value" aria-hidden="true">→</span></li>`;
  };
  const versus = floor !== null && num(f.protein_g) !== null ? (f.protein_g >= floor ? `, at or above the ${whole(floor)} g floor` : `, under the ${whole(floor)} g floor`) : "";
  return `<ul class="ck-rows ck-rows--chapters">${row("calories", f.calories)}${row("protein", f.protein_g, versus)}${row("carbs", f.carbs_g)}${row("fat", f.fat_g)}</ul>`;
}
export function dayNavHTML(iso, src, base) {
  const known = new Set([...Object.keys(byDate(src.pulse && src.pulse.pulse_history)), ...Object.keys(byDate(src.workouts && src.workouts.workouts))]);
  const link = (d, text) => (known.has(d) ? `<a class="ck-btn ck-btn--ghost" href="${esc(dayHref(base, d))}">${esc(text)}</a>` : "");
  const [prev, next] = [shift(iso, -1), shift(iso, 1)];
  const html = `${link(prev, `← ${dayInWords(prev).split(",")[0]}`)}${link(next, `${dayInWords(next).split(",")[0]} →`)}`;
  return html ? `<div class="ck-actions">${html}</div>` : "";
}

// ── the food trend's extra: what is eaten most often ───────────────────────────
export function frequentMealsHTML(body) {
  const meals = ((body && body.meals) || []).filter((m) => m && m.name && num(m.frequency) !== null).slice(0, 8);
  if (!meals.length) return "";
  const days = num(body.period_days);
  return `${soft(days ? `What I logged most often over ${whole(days)} days.` : "What I logged most often.")}<ul class="ck-rows ck-rows--chapters">${meals
    .map((m) => `<li><span class="ck-rows__key">${whole(m.frequency)} times</span><span>${esc(m.name)}</span><span class="ck-rows__value">${num(m.avg_protein_g) !== null ? `${whole(m.avg_protein_g)} g protein` : ""}</span></li>`)
    .join("")}</ul>`;
}

// ── mount ──────────────────────────────────────────────────────────────────────
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};
const param = (name) => new URLSearchParams(location.search).get(name) || "";

async function load(routes) {
  const entries = await Promise.all(Object.entries(routes).map(async ([key, path]) => [key, await tryJSON(path)]));
  return Object.fromEntries(entries);
}

async function mountDay(base) {
  const src = await load({ pulse: "/api/pulse_history", workouts: "/api/workouts", training: "/api/training_overview", nutrition: "/api/nutrition_overview" });
  const iso = isDay(param("d")) ? param("d") : latestDay(src);
  if (!iso) {
    fill("ck-title", "This day");
    fill("ck-facts", soft("The day’s record is not served right now."));
    return;
  }
  const row = byDate(src.pulse && src.pulse.pulse_history)[iso];
  fill("ck-label", esc(row && num(row.day_number) !== null ? `Day ${row.day_number}` : "One day"));
  fill("ck-title", esc(dayInWords(iso)));
  document.title = `${dayInWords(iso)} — Average Joe Matt`;
  fill("ck-nav", dayNavHTML(iso, src, base));
  fill("ck-facts", dayFactsHTML(iso, src, base));
  fill("ck-lifts", dayLiftsHTML(iso, src, base));
  fill("ck-food", dayFoodHTML(iso, src, base));
}

async function mountTrend(base) {
  const measure = param("m") || "weight";
  const lift = param("x");
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
  let points = [];
  let name = "";
  let about = "";
  let write = (v) => trim1(v);
  let extra = "";
  if (measure === "lift" && lift) {
    const src = await load({ workouts: "/api/workouts" });
    points = liftSeries(src.workouts && src.workouts.workouts, lift);
    name = lift;
    about = "The heaviest working set in each session.";
    write = (v) => `${whole(v)} lb`;
  } else if (MEASURES[measure]) {
    const food = ["protein", "calories", "carbs", "fat"].includes(measure);
    const src = await load(food ? { nutrition: "/api/nutrition_overview", meals: "/api/frequent_meals" } : measure === "training" ? { training: "/api/training_overview" } : { pulse: "/api/pulse_history" });
    points = seriesOf(measure, src, today);
    ({ name, about, write } = MEASURES[measure]);
    if (food) extra = frequentMealsHTML(src.meals);
  }
  if (!name) {
    fill("ck-title", "Not a measure");
    fill("ck-about", soft("This address does not name a measure the site records."));
    return;
  }
  fill("ck-title", esc(name));
  document.title = `${name} — Average Joe Matt`;
  fill("ck-about", soft(about));
  fill("ck-chart", points.length ? `${soft(trendSentence(points, write))}${trendChartHTML(points, write, name)}` : soft("Nothing has been recorded for this yet."));
  fill("ck-recent", recentRowsHTML(points, write, base));
  fill("ck-extra", extra);
  const extraSection = document.getElementById("ck-extra-section");
  if (extraSection && !extra) extraSection.remove();
}

export async function mount() {
  const page = document.body && document.body.dataset.ckPage;
  const base = (document.body && document.body.dataset.ckBase) || "/";
  if (page === "day") await mountDay(base);
  else if (page === "trend") await mountTrend(base);
  else return;
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();

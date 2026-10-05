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
// A day also carries what was SAID and SETTLED on it (#4648): the coaches' lines for that
// day, in their words, and any call that was checked that day with its verdict, the rule
// that decided it and a door to its own page. A day with neither prints nothing for them:
// no heading, no empty section, no filler.
//
// The builders are pure and exported for tests/js/ck_depth_4586.test.mjs; mount() is the
// only thing that touches the DOM.
import { tryJSON, esc, fmtShort } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";
import { callHref, callsOf } from "/assets/js/ck_call.js";

const LB_PER_KG = 2.20462;
const isDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
const whole = (v) => (num(v) === null ? "" : Math.round(v).toLocaleString("en-US"));
const lb = (kg) => (num(kg) === null ? null : Math.round(kg * LB_PER_KG));
const soft = (t) => (t ? `<p class="ck-soft">${esc(t)}</p>` : "");
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const byDate = (rows) => Object.fromEntries((rows || []).filter((r) => r && isDay(r.date)).map((r) => [r.date, r]));
const shift = (iso, days) => new Date(Date.parse(`${iso}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);

// ── the measures a trend page can show ─────────────────────────────────────────
// key -> its name, unit, where its daily values come from and how a value is written.
export const MEASURES = {
  weight: { name: "Weight", unit: "lb", write: (v) => `${v.toFixed(1)} lb`, about: "Every weigh-in since the start." },
  steps: { name: "Steps", unit: "steps", write: (v) => whole(v), about: "Steps as my phone and watch counted them. A day they were not carried reads low, so some days here are lower than the training recorded suggests." },
  sleep: { name: "Sleep", unit: "hours", write: (v) => `${trim1(v)} hours`, about: "Hours asleep each night." },
  recovery: { name: "Recovery", unit: "out of 100", write: (v) => `${whole(v)} out of 100`, about: "My wrist strap’s morning score out of 100." },
  protein: { name: "Protein", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of protein logged each day." },
  calories: { name: "Calories", unit: "kcal", write: (v) => `${whole(v)} kcal`, about: "Calories logged each day." },
  carbs: { name: "Carbs", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of carbohydrate logged each day." },
  fat: { name: "Fat", unit: "g", write: (v) => `${whole(v)} g`, about: "Grams of fat logged each day." },
  training: { name: "Training time", unit: "minutes", write: (v) => `${whole(v)} minutes`, about: "Minutes of training recorded each day." },
};

// Own keys only: the measure name arrives from the address bar.
export const isMeasure = (m) => Object.prototype.hasOwnProperty.call(MEASURES, String(m));
export const trendHref = (base, measure, lift = "", from = "") => `${base}trend/?m=${encodeURIComponent(measure)}${lift ? `&x=${encodeURIComponent(lift)}` : ""}${isDay(from) ? `&from=${from}` : ""}`;
export const dayHref = (base, iso) => `${base}day/?d=${encodeURIComponent(iso)}`;

// One {date, value} series for a measure from the served bodies. Null readings are dropped:
// a day with no value is a gap in the line, never a zero.
export function seriesOf(measure, src, today = "") {
  const pick = (rows, field) => (rows || []).filter((r) => r && isDay(r.date) && num(r[field]) !== null).map((r) => ({ date: r.date, value: r[field] }));
  const pulse = src.pulse && src.pulse.pulse_history;
  const food = src.nutrition && src.nutrition.nutrition_trend;
  // A switch on literal names: the measure comes from the address bar, so nothing is ever
  // looked up or called by a name the reader supplied.
  const read = () => {
    switch (measure) {
      case "weight":
        return pick(pulse, "weight_lbs");
      case "steps":
        return pick(pulse, "steps").filter((p) => p.date !== today);
      case "sleep":
        return pick(pulse, "sleep_hours");
      case "recovery":
        return pick(pulse, "recovery_pct");
      case "protein":
        return pick(food, "protein_g");
      case "calories":
        return pick(food, "calories");
      case "carbs":
        return pick(food, "carbs_g");
      case "fat":
        return pick(food, "fat_g");
      case "training":
        return pick(src.training && src.training.daily_modality_minutes_30d, "total_min").filter((p) => p.date !== today || p.value > 0);
      default:
        return [];
    }
  };
  return read().sort((a, b) => a.date.localeCompare(b.date));
}

// ── a lift ─────────────────────────────────────────────────────────────────────
// A session's working sets for one exercise (warm-ups set aside), heaviest load first in
// the summary: "3 sets at 175 lb: 12, 12 and 10 reps".
const isWarm = (s) => s && s.type === "warmup";
const isWork = (s) => s && !isWarm(s) && num(s.reps) !== null;
const MILES_PER_M = 1 / 1609.344;
// Estimated one-rep max (Epley): load x (1 + reps / 30). An ESTIMATE, named as one wherever
// it is shown; it lets a 175 lb set of 12 be compared with a 205 lb set of 5.
export const epley = (loadLb, reps) => (num(loadLb) === null || num(reps) === null || reps < 1 ? null : reps === 1 ? loadLb : loadLb * (1 + reps / 30));
export function liftSummary(exercise) {
  const sets = (exercise.sets || []).filter(isWork);
  const warm = (exercise.sets || []).filter(isWarm).length;
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
// One point per session for one exercise: its best working set. With a load, "best" is the
// highest estimated one-rep max and the point carries the set it came from ("175 lb x 12");
// for a bodyweight exercise it is the most reps in a set.
export function liftSeries(workouts, name) {
  return (workouts || [])
    .map((w) => {
      const ex = (w.exercises || []).find((e) => e && e.name === name);
      const sets = ex ? (ex.sets || []).filter(isWork) : [];
      if (!sets.length || !isDay(w.date)) return null;
      const loaded = sets.filter((s) => lb(s.weight_kg));
      if (!loaded.length) {
        const reps = Math.max(...sets.map((s) => s.reps));
        return { date: w.date, value: reps, set: `${Math.round(reps)} reps`, bodyweight: true };
      }
      const best = loaded.map((s) => ({ load: lb(s.weight_kg), reps: Math.round(s.reps), max: epley(lb(s.weight_kg), s.reps) })).sort((a, b) => b.max - a.max)[0];
      return { date: w.date, value: Math.round(best.max), set: `${best.load} lb × ${best.reps}` };
    })
    .filter(Boolean)
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ── the chart: one line, both ends labelled, and a sentence saying what it shows ─
export function trendChartHTML(points, write, name, { fromZero = false } = {}) {
  const pts = (points || []).filter((p) => p && isDay(p.date) && num(p.value) !== null);
  if (pts.length < 2) return "";
  const t = (iso) => Date.parse(`${iso}T12:00:00Z`);
  const [t0, t1] = [t(pts[0].date), t(pts[pts.length - 1].date)];
  const lo = Math.min(...pts.map((p) => p.value));
  const hi = Math.max(...pts.map((p) => p.value));
  // A count (steps, grams, minutes) is scaled from zero, so a height means an amount. A
  // level is scaled to its own range and drawn as a line alone: filling under it would
  // make its lowest reading look like nothing.
  const floor = fromZero ? 0 : lo;
  const x = (p) => 8 + (624 * (t(p.date) - t0)) / (t1 - t0 || 1);
  const y = (p) => 20 + (122 * (hi - p.value)) / (hi - floor || 1);
  const line = pts.map((p) => `${x(p).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const area = fromZero ? `<polygon class="ck-chart__area" points="8.0,164 ${line} 632.0,164"/>` : "";
  const [first, last] = [pts[0], pts[pts.length - 1]];
  const aria = `${name} from ${write(first.value)} on ${shortDay(first.date)} to ${write(last.value)} on ${shortDay(last.date)}, ${pts.length} readings, lowest ${write(lo)}, highest ${write(hi)}`;
  return `<svg class="ck-chart" viewBox="0 0 640 164" role="img" aria-label="${esc(aria)}">${area}<polyline class="ck-chart__line" points="${line}"/><circle class="ck-chart__now" cx="${x(last).toFixed(1)}" cy="${y(last).toFixed(1)}" r="5"/></svg><div class="ck-ends"><span>${esc(`${shortDay(first.date)} · ${write(first.value)}`)}</span><span>${esc(`${shortDay(last.date)} · ${write(last.value)}`)}</span></div>`;
}
// A daily COUNT as bars from zero. A bar at or above the target is drawn in the accent (the
// kit's colour for progress); the line over the bars is the average of the seven readings
// ending on that day; the dashed rule is the target. No text is set inside the drawing —
// at phone width it would be too small to read — so the caption says what each mark is.
export function barChartHTML(points, write, name, { target = null, targetWords = "" } = {}) {
  const pts = (points || []).filter((p) => p && isDay(p.date) && num(p.value) !== null);
  if (pts.length < 2) return "";
  const hi = Math.max(...pts.map((p) => p.value), target || 0);
  const slot = 624 / pts.length;
  const w = Math.max(2, slot * 0.72);
  const y = (v) => 20 + (136 * (hi - v)) / (hi || 1);
  const bars = pts
    .map((p, i) => `<rect class="${target !== null && p.value >= target ? "ck-chart__now" : "ck-chart__area"}" x="${(8 + i * slot + (slot - w) / 2).toFixed(1)}" y="${y(p.value).toFixed(1)}" width="${w.toFixed(1)}" height="${(156 - y(p.value)).toFixed(1)}"/>`)
    .join("");
  const avg = pts.map((p, i) => {
    const win = pts.slice(Math.max(0, i - 6), i + 1).map((q) => q.value);
    return win.length === 7 ? `${(8 + i * slot + slot / 2).toFixed(1)},${y(win.reduce((a, b) => a + b, 0) / 7).toFixed(1)}` : "";
  }).filter(Boolean);
  const line = avg.length > 1 ? `<polyline class="ck-chart__line" points="${avg.join(" ")}"/>` : "";
  const rule = target !== null ? `<line x1="8" x2="632" y1="${y(target).toFixed(1)}" y2="${y(target).toFixed(1)}" stroke="currentColor" stroke-width="1.5" stroke-dasharray="5 5"/>` : "";
  const [first, last] = [pts[0], pts[pts.length - 1]];
  const aria = `${name}, ${pts.length} days from ${shortDay(first.date)} to ${shortDay(last.date)}, highest ${write(Math.max(...pts.map((p) => p.value)))}${target !== null ? `, target ${write(target)}` : ""}`;
  const key = [target !== null ? `Dashed line: ${targetWords || write(target)}. Dark bars are days at or above it.` : "", line ? "The line is the average of the seven days ending on that day." : ""].filter(Boolean).join(" ");
  return `<svg class="ck-chart" viewBox="0 0 640 164" role="img" aria-label="${esc(aria)}">${bars}${rule}${line}</svg><div class="ck-ends"><span>${esc(shortDay(first.date))}</span><span>${esc(`${shortDay(last.date)} · ${write(last.value)}`)}</span></div>${key ? `<p class="ck-small">${esc(key)}</p>` : ""}`;
}
export function trendSentence(points, write, { average = true, floor = null, floorWords = "" } = {}) {
  const pts = points || [];
  if (!pts.length) return "";
  const values = pts.map((p) => p.value);
  const [lo, hi] = [Math.min(...values), Math.max(...values)];
  if (pts.length === 1) return `One reading so far: ${write(pts[0].value)} on ${shortDay(pts[0].date)}.`;
  const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
  const parts = [`${pts.length} readings from ${shortDay(pts[0].date)} to ${shortDay(pts[pts.length - 1].date)}.`, `Lowest ${write(lo)}, highest ${write(hi)}${average ? `, average ${write(mean(values))}` : ""}.`];
  if (floor !== null) parts.push(`At or above ${floorWords || write(floor)} on ${values.filter((v) => v >= floor).length} of ${values.length} days.`);
  return parts.join(" ");
}
// The last seven readings against the seven before: two averages, said plainly. "" until
// there are fourteen readings to compare.
export function weekOnWeek(points, write) {
  const v = (points || []).map((p) => p.value);
  if (v.length < 14) return "";
  const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
  return `The last seven readings average ${write(mean(v.slice(-7)))}; the seven before, ${write(mean(v.slice(-14, -7)))}.`;
}
// The most recent readings, newest first, each a door to its day.
export function recentRowsHTML(points, write, base, first = 7) {
  const rows = [...(points || [])].reverse();
  if (!rows.length) return "";
  const li = (p) => `<li><a href="${esc(dayHref(base, p.date))}">${esc(`${fmtShort(p.date)} · ${dayInWords(p.date).split(",")[0]} · ${p.set && !p.bodyweight ? `${p.set} · est. max ${write(p.value)}` : write(p.value)}`)} <span aria-hidden="true">→</span></a></li>`;
  const list = (items) => `<ul class="ck-rows ck-rows--more">${items.map(li).join("")}</ul>`;
  const rest = rows.slice(first);
  // The newest week is on the page; the rest is one tap away, never dropped.
  return `${list(rows.slice(0, first))}${rest.length ? `<details><summary>The ${rest.length} earlier ${rest.length === 1 ? "reading" : "readings"}</summary>${list(rest)}</details>` : ""}`;
}

// ── the day page ───────────────────────────────────────────────────────────────
export function latestDay(src) {
  const days = [...Object.keys(byDate(src.pulse && src.pulse.pulse_history)), ...Object.keys(byDate(src.workouts && src.workouts.workouts))].sort();
  return days[days.length - 1] || "";
}
// The day's measured facts, each a door to its trend. A measure with no reading is absent.
export function dayFactsHTML(iso, src, base, today = "") {
  const p = byDate(src.pulse && src.pulse.pulse_history)[iso] || {};
  const row = (measure, value, note = "") => {
    const m = MEASURES[measure];
    return num(value) === null ? "" : `<li><a href="${esc(trendHref(base, measure, "", iso))}">${esc(`${m.name}: ${m.write(value)}${note}`)} <span aria-hidden="true">→</span></a></li>`;
  };
  const rows = [row("weight", p.weight_lbs), row("sleep", p.sleep_hours), row("recovery", p.recovery_pct), row("steps", p.steps, iso === today ? " so far today" : "")].join("");
  return rows ? `<ul class="ck-rows ck-rows--more">${rows}</ul>` : soft("Nothing was measured on this day.");
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
  // Timed or distance work (the bike, stretching, a carry) has no reps: it is named with its
  // distance when one was recorded, not given a row of sets it does not have.
  const timed = named
    .filter((e) => !(e.sets || []).some(isWork))
    .map((e) => {
      const metres = (e.sets || []).reduce((a, x) => a + (num(x && x.distance_m) || 0), 0);
      return metres > 0 ? `${e.name} (${trim1(metres * MILES_PER_M)} miles)` : e.name;
    });
  const warmLine = timed.length ? soft(`Also in the session: ${timed.join(", ")}.`) : "";
  const all = (src.workouts && src.workouts.workouts) || [];
  const before = (name) => {
    const prior = liftSeries(all, name).filter((pt) => pt.date < iso);
    const last = prior[prior.length - 1];
    return last ? `Last time, ${fmtShort(last.date)}: ${last.set}.` : "First time recorded.";
  };
  const rows = worked
    .map((e) => `<li><a class="ck-coach__who" href="${esc(trendHref(base, "lift", e.name, iso))}">${esc(e.name)}</a><span>${esc(liftSummary(e))}</span><span class="ck-small">${esc(before(e.name))}</span></li>`)
    .join("");
  const moved = worked.reduce((sum, e) => sum + (e.sets || []).filter(isWork).reduce((a, x) => a + (lb(x.weight_kg) || 0) * x.reps, 0), 0);
  const head = num(session.duration_min) !== null ? soft(`${whole(session.duration_min)} minutes in the session${moved > 0 ? `, ${whole(moved)} lb moved in working sets` : ""}. Warm-up sets are left out; each lift opens its own trend.`) : "";
  return `${head}${rows ? `<ul class="ck-coach">${rows}</ul>` : ""}${warmLine}${otherLine}`;
}
// What was eaten: the day's totals. The log's individual entries are not public.
export function dayFoodHTML(iso, src, base) {
  const f = byDate(src.nutrition && src.nutrition.nutrition_trend)[iso];
  if (!f) return soft("No food was logged on this day.");
  const floor = num(src.nutrition && src.nutrition.nutrition && src.nutrition.nutrition.protein_floor_g);
  const row = (measure, value, note = "") => {
    const m = MEASURES[measure];
    return num(value) === null ? "" : `<li><a href="${esc(trendHref(base, measure, "", iso))}">${esc(`${m.name}: ${m.write(value)}${note}`)} <span aria-hidden="true">→</span></a></li>`;
  };
  const versus = floor !== null && num(f.protein_g) !== null ? (f.protein_g >= floor ? `, at or above the ${whole(floor)} g floor` : `, under the ${whole(floor)} g floor`) : "";
  return `<ul class="ck-rows ck-rows--more">${row("calories", f.calories)}${row("protein", f.protein_g, versus)}${row("carbs", f.carbs_g)}${row("fat", f.fat_g)}</ul>${soft(macroShare(f))}`;
}
// Where the day's calories came from, from the logged grams (4 kcal a gram for protein and
// carbohydrate, 9 for fat). "" unless all three were logged.
export function macroShare(f) {
  const [p, c, fat] = [num(f && f.protein_g), num(f && f.carbs_g), num(f && f.fat_g)];
  if (p === null || c === null || fat === null) return "";
  const kcal = [p * 4, c * 4, fat * 9];
  const total = kcal[0] + kcal[1] + kcal[2];
  if (!(total > 0)) return "";
  const pct = kcal.map((k) => Math.round((100 * k) / total));
  return `Of the calories from those three: protein ${pct[0]}%, carbs ${pct[1]}%, fat ${pct[2]}%.`;
}
export function dayNavHTML(iso, src, base) {
  const known = new Set([...Object.keys(byDate(src.pulse && src.pulse.pulse_history)), ...Object.keys(byDate(src.workouts && src.workouts.workouts))]);
  const link = (d, text) => (known.has(d) ? `<a class="ck-btn ck-btn--ghost" href="${esc(dayHref(base, d))}">${esc(text)}</a>` : "");
  const [prev, next] = [shift(iso, -1), shift(iso, 1)];
  const html = `${link(prev, `← ${dayInWords(prev).split(",")[0]}`)}${link(next, `${dayInWords(next).split(",")[0]} →`)}`;
  return html ? `<div class="ck-actions">${html}</div>` : "";
}

// ── what was said and settled on the day (#4648) ───────────────────────────────
const SETTLED_FIRST = 2; // calls shown before the rest fold under one disclosure
export const coachHref = (base, id) => `${base}coach/?c=${encodeURIComponent(id)}`;
// The coaches' lines for the day, from GET /api/coach_moves?date=<day>: who, the kind of
// line it is, and the words exactly as served. "" when the day has none, when the body is
// for another day, or when the route is not served.
export function daySaidHTML(iso, movesBody, base) {
  const lines = movesBody && movesBody.state === "ok" && movesBody.date === iso && Array.isArray(movesBody.lines) ? movesBody.lines.filter((l) => l && l.coach && l.text) : [];
  if (!lines.length) return "";
  const rows = lines
    .map((l) => {
      const name = l.coach_id ? `<a class="ck-link" href="${esc(coachHref(base, l.coach_id))}">${esc(l.coach)}</a>` : esc(l.coach);
      const kind = l.move === "reply" && l.replies_to ? `A reply to ${l.replies_to}` : [l.move_label, l.replies_to ? `replying to ${l.replies_to}` : ""].filter(Boolean).join(" · ");
      return `<li><span class="ck-coach__who">${name}${kind ? esc(` · ${kind}`) : ""}</span><span>“${esc(l.text)}”</span></li>`;
    })
    .join("");
  // Two coaches who opened a bet in these lines share its date: it is said once, below.
  const bets = [...new Set(lines.map((l) => l.bet_settles).filter(isDay))].map((d) => soft(`A bet opened in these lines settles ${dayInWords(d)}.`)).join("");
  return `<p class="ck-label">The coaches</p><h2>What the coaches said.</h2><ul class="ck-coach">${rows}</ul>${bets}`;
}
// One settled call on a day: the served `called` sentence (it carries the rule the call
// was checked by), what happened, the verdict, and the door to the call's own page.
// TODO(#4647): switch the verdict and its rule to the shared verdict-tag helper once it lands.
function settledRow(call, base) {
  const word = call.kind === "bet" ? "" : call.verdict === "right" ? "Right" : call.verdict === "wrong" ? "Wrong" : "";
  const verdict = word ? `<span class="ck-verdicts__tag${word === "Right" ? " ck-verdicts__tag--right" : ""}">${word}</span>` : `<span class="ck-verdicts__tag">${esc(call.verdict_text || "Settled")}</span>`;
  return `<li>${verdict}<span>${esc(call.called || call.called_short)}</span><span class="ck-soft">${esc(call.happened_short)}</span><a class="ck-link" href="${esc(callHref(base, call.id))}">The whole call</a></li>`;
}
// Every call settled on the day, from GET /api/calls. "" when none settled that day. Under
// the coaches' lines it takes a label, not a second heading: the two are one part of the day.
export function daySettledHTML(iso, callsBody, base, { under = false } = {}) {
  const calls = callsOf(callsBody).filter((c) => c.settled_date === iso);
  if (!calls.length) return "";
  const list = (items) => `<ul class="ck-coach">${items.map((c) => settledRow(c, base)).join("")}</ul>`;
  const rest = calls.slice(SETTLED_FIRST);
  const more = rest.length ? `<details><summary>${rest.length} more settled this day</summary>${list(rest)}</details>` : "";
  const title = calls.length === 1 ? "A call was checked this day." : `${calls.length} calls were checked this day.`;
  const head = under ? `<p class="ck-label">${esc(title)}</p>` : `<p class="ck-label">Settled</p><h2>${esc(title)}</h2>`;
  return `${head}${list(calls.slice(0, SETTLED_FIRST))}${more}`;
}
// Both, in reading order, as ONE section. "" for a day with neither: the page prints
// nothing extra.
export function dayStoryHTML(iso, movesBody, callsBody, base) {
  const said = daySaidHTML(iso, movesBody, base);
  const settled = daySettledHTML(iso, callsBody, base, { under: Boolean(said) });
  return said || settled ? `<section class="ck-section" id="ck-story">${said}${settled}</section>` : "";
}

// ── the food trend's extra: what is eaten most often ───────────────────────────
export function frequentMealsHTML(body) {
  const meals = ((body && body.meals) || []).filter((m) => m && m.name && num(m.frequency) !== null).slice(0, 8);
  if (!meals.length) return "";
  const days = num(body.period_days);
  return `${soft(`The foods I logged most often${days ? ` over ${whole(days)} days` : ""}, with the protein in one serving.`)}<ul class="ck-rows ck-rows--chapters">${meals
    .map((m) => `<li><span class="ck-rows__key">${whole(m.frequency)} times</span><span>${esc(m.name)}</span><span class="ck-rows__value">${num(m.avg_protein_g) !== null ? `${whole(m.avg_protein_g)} g` : ""}</span></li>`)
    .join("")}</ul>`;
}
// The other trends a reader on this one is most likely to want next.
const RELATED = { protein: ["calories", "carbs", "fat"], calories: ["protein", "carbs", "fat"], carbs: ["calories", "protein", "fat"], fat: ["calories", "protein", "carbs"], weight: ["calories", "steps", "training"], steps: ["training", "weight"], sleep: ["recovery"], recovery: ["sleep", "training"], training: ["steps", "recovery"] };
export function relatedHTML(measure, base, from = "") {
  const keys = measure === "lift" ? ["training", "weight"] : RELATED[measure] || [];
  if (!keys.length) return "";
  return `<ul class="ck-rows ck-rows--more">${keys.map((k) => `<li><a href="${esc(trendHref(base, k, "", from))}">${esc(MEASURES[k].name)} <span aria-hidden="true">→</span></a></li>`).join("")}</ul>`;
}

// ── every trend, in four areas ─────────────────────────────────────────────────
// One index, one template behind every link. It is a table of contents for the depth
// layer, reached from a day or a trend — never a set of sections in the site's menu.
export const TREND_AREAS = [
  { name: "Body", measures: ["weight"] },
  { name: "Food", measures: ["calories", "protein", "carbs", "fat"] },
  { name: "Training", measures: ["training", "steps"] },
  { name: "Sleep", measures: ["sleep", "recovery"] },
];
// A lift's trend is reached from the lift itself on a day page, so the index lists the
// nine measures only: a list of every exercise is a menu, and nothing links to a menu.
export function trendIndexHTML(base) {
  const link = (href, text) => `<li><a href="${esc(href)}">${esc(text)} <span aria-hidden="true">→</span></a></li>`;
  return TREND_AREAS.map((a) => `<p class="ck-label">${esc(a.name)}</p><ul class="ck-rows ck-rows--more">${a.measures.map((m) => link(trendHref(base, m), MEASURES[m].name)).join("")}</ul>`).join("");
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

const todayPT = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });

const movesPath = (iso) => `/api/coach_moves?date=${iso}`;

async function mountDay(base) {
  const asked = isDay(param("d")) ? param("d") : "";
  // The day's lines are asked for alongside everything else when the address names the day.
  const early = asked ? tryJSON(movesPath(asked)) : null;
  const src = await load({ pulse: "/api/pulse_history", workouts: "/api/workouts", training: "/api/training_overview", nutrition: "/api/nutrition_overview", calls: "/api/calls" });
  const iso = asked || latestDay(src);
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
  // Said and settled: whole sections, added only when the day has them (#4648).
  const story = dayStoryHTML(iso, await (early || tryJSON(movesPath(iso))), src.calls, base);
  if (story) document.getElementById("ck-head")?.insertAdjacentHTML("afterend", story);
  fill("ck-facts", dayFactsHTML(iso, src, base, todayPT()));
  fill("ck-lifts", dayLiftsHTML(iso, src, base));
  fill("ck-food", dayFoodHTML(iso, src, base));
}

// How each measure is drawn and described: a COUNT is scaled from zero and has a meaningful
// average; a LEVEL (weight, sleep, recovery, a lift) is a line with no average.
const COUNTS = new Set(["steps", "protein", "calories", "carbs", "fat", "training"]);

async function mountTrend(base) {
  const measure = param("m");
  if (!measure) {
    const src = await load({ workouts: "/api/workouts" });
    fill("ck-label", "The detail");
    fill("ck-title", "Every trend");
    document.title = "Every trend — Average Joe Matt";
    fill("ck-about", soft("Each one is a single measure over the whole experiment. Every reading links back to its day."));
    fill("ck-chart", trendIndexHTML(base));
    for (const id of ["ck-recent-section", "ck-extra-section", "ck-related-section"]) document.getElementById(id)?.remove();
    return;
  }
  const lift = param("x");
  const from = isDay(param("from")) ? param("from") : "";
  const today = todayPT();
  let points = [];
  let name = "";
  let about = "";
  let write = (v) => trim1(v);
  let extra = "";
  let sentenceOpts = { average: false };
  if (measure === "lift" && lift) {
    const src = await load({ workouts: "/api/workouts" });
    points = liftSeries(src.workouts && src.workouts.workouts, lift);
    name = lift;
    const bodyweight = points.length && points.every((p) => p.bodyweight);
    about = bodyweight
      ? "The most reps in one set, each session."
      : "Estimated one-rep max from the best set of each session: the load times one plus reps over thirty. It is an estimate, so a set of 12 at 175 lb can be compared with a set of 5 at 205.";
    write = bodyweight ? (v) => `${whole(v)} reps` : (v) => `${whole(v)} lb`;
  } else if (isMeasure(measure)) {
    const food = ["protein", "calories", "carbs", "fat"].includes(measure);
    const src = await load(food ? { nutrition: "/api/nutrition_overview", meals: "/api/frequent_meals" } : measure === "training" ? { training: "/api/training_overview" } : { pulse: "/api/pulse_history" });
    points = seriesOf(measure, src, today);
    ({ name, about, write } = MEASURES[measure]);
    sentenceOpts = { average: COUNTS.has(measure) };
    if (measure === "protein") {
      const floor = num(src.nutrition && src.nutrition.nutrition && src.nutrition.nutrition.protein_floor_g);
      if (floor !== null) sentenceOpts = { ...sentenceOpts, floor, floorWords: `my ${whole(floor)} g floor` };
    }
    if (measure === "protein" || measure === "calories") extra = frequentMealsHTML(src.meals);
  }
  if (from) {
    const back = document.getElementById("ck-back");
    if (back) {
      back.href = dayHref(base, from);
      back.textContent = `← ${dayInWords(from)}`;
    }
  }
  if (!name) {
    fill("ck-title", "Not a measure");
    fill("ck-about", soft("This address does not name a measure the site records."));
    return;
  }
  fill("ck-label", esc(measure === "training" ? "The last 30 days" : "Over the whole experiment"));
  fill("ck-title", esc(name));
  document.title = `${name} — Average Joe Matt`;
  fill("ck-about", soft(about));
  const chart = COUNTS.has(measure)
    ? barChartHTML(points, write, name, { target: sentenceOpts.floor ?? null, targetWords: sentenceOpts.floorWords ? sentenceOpts.floorWords.replace(/^my /, "the ") : "" })
    : trendChartHTML(points, write, name);
  fill("ck-chart", points.length ? `${soft(trendSentence(points, write, sentenceOpts))}${chart}${COUNTS.has(measure) ? soft(weekOnWeek(points, write)) : ""}` : soft("Nothing has been recorded for this yet."));
  fill("ck-recent", recentRowsHTML(points, write, base));
  fill("ck-extra", extra);
  if (!extra) document.getElementById("ck-extra-section")?.remove();
  const related = relatedHTML(measure, base, from);
  fill("ck-related", related);
  if (!related) document.getElementById("ck-related-section")?.remove();
  const all = document.getElementById("ck-all");
  if (all) all.href = `${base}trend/`;
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

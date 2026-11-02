// The Day object's reading vocabulary (#5585): the tile set, the sentence, the deltas and the
// fourteen-day sparkline. Pure functions, no Astro imports, so `node --test` proves them
// (tests/day.test.mjs). Every normal the page states was computed by the exporter
// (scripts/publish_snapshot_day.py) — this module formats and places, it never averages.
import { dayInWords, num } from "./format.js";

/** The eight reading tiles, in the approved prototype's order. `metric` is the public measure page, when one exists. */
export const READING_TILES = Object.freeze([
  { key: "weight_lbs", label: "Weight · Withings", unit: "lb", decimals: 1, metric: "weight_lbs", name: "pounds" },
  { key: "recovery_pct", label: "Recovery · Whoop", unit: "", decimals: 0, metric: "recovery_score", name: "recovery" },
  { key: "sleep_hours", label: "Sleep · the night before", unit: "h", decimals: 1, metric: "sleep_duration_hours", name: "hours" },
  { key: "hrv_ms", label: "HRV · Whoop", unit: "ms", decimals: 1, metric: "hrv", name: "milliseconds", against: "mean30" },
  { key: "rhr_bpm", label: "Resting heart rate", unit: "bpm", decimals: 0, metric: "resting_hr", name: "beats a minute" },
  { key: "strain", label: "Strain · Whoop", unit: "", decimals: 1, metric: null, name: "strain", scale: "0–21" },
  { key: "steps", label: "Steps", unit: "", decimals: 0, metric: "steps", name: "steps" },
  { key: "active_kcal", label: "Active energy", unit: "kcal", decimals: 0, metric: null, name: "kilocalories" },
]);

const MINUS = "−";

/** A signed figure: "+2.1", "−2.8", "0". */
export function signed(v, decimals = 0) {
  const r = Number(v.toFixed(decimals));
  if (r === 0) return num(0, decimals);
  return `${r > 0 ? "+" : MINUS}${num(Math.abs(r), decimals)}`;
}

/** "7.5" from 7.5, "8" from 8.0 — for prose, where a trailing zero reads as precision nobody measured. */
export function plain(v, decimals = 1) {
  return num(v, decimals).replace(/\.0+$/, "");
}

/** The delta line under a tile: against the 7-day mean (HRV: the 30-day mean, with its n). */
export function deltaLine(day, tile) {
  const v = day.readings[tile.key];
  if (v == null) return "no reading";
  const n = day.normals[tile.key] || {};
  if (tile.against === "mean30") {
    if (n.mean30 == null || n.n30 < 2) return "no other reading in thirty days";
    return `${signed(v - n.mean30, tile.decimals)} vs his 30-day mean of ${num(n.mean30, tile.decimals)} (n=${n.n30})`;
  }
  if (n.mean7 == null || n.n7 < 2) return "no other reading in seven days";
  const tail = tile.scale ? ` · ${tile.scale}` : "";
  return `${signed(v - n.mean7, tile.decimals)}${tile.unit === "h" ? " h" : ""} vs 7-day mean${tail}`;
}

/** The value as the tile prints it. */
export function tileValue(day, tile) {
  const v = day.readings[tile.key];
  return v == null ? "—" : num(v, tile.decimals);
}

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const dayIndex = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000);

/** "Wednesday" within the week before, otherwise "21 October" — never an ambiguous weekday. */
export function sinceWords(fromIso, toIso) {
  const gap = dayIndex(toIso) - dayIndex(fromIso);
  if (gap >= 1 && gap <= 6) return DAYS[new Date(dayIndex(fromIso) * 86400000).getUTCDay()];
  return dayInWords(fromIso, { short: false }).replace(/ \d{4}$/, "");
}

/**
 * The one-sentence dek: "295.7 lb (down 2.2 since Wednesday). slept 7.5 hours. recovery 74."
 * `prevWeighin` is the latest earlier day with a weigh-in (a Day object), or null.
 */
export function dekSentence(day, prevWeighin) {
  const r = day.readings;
  const parts = [];
  if (r.weight_lbs != null) {
    let w = `${num(r.weight_lbs, 1)} lb`;
    if (prevWeighin && prevWeighin.readings.weight_lbs != null) {
      const d = Number((r.weight_lbs - prevWeighin.readings.weight_lbs).toFixed(1));
      const since = sinceWords(prevWeighin.date, day.date);
      w += d === 0 ? ` (unchanged since ${since})` : ` (${d < 0 ? "down" : "up"} ${num(Math.abs(d), 1)} since ${since})`;
    }
    parts.push(w);
  } else {
    parts.push("no weigh-in");
  }
  if (r.sleep_hours != null) parts.push(`slept ${plain(r.sleep_hours, 1)} hours`);
  if (r.recovery_pct != null) parts.push(`recovery ${plain(r.recovery_pct, 0)}`);
  return `${parts.join(". ")}.`;
}

/** The fourteen days ending on index i (fewer at the start; the strip pads before them). */
export function stripWindow(days, i, size = 14) {
  return days.slice(Math.max(0, i - (size - 1)), i + 1);
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/**
 * A tile's sparkline: the fourteen days ending on this one, the day marked, the 7-day mean dashed.
 * No text inside the svg (nothing to shrink below the 11 px floor at phone width). The inspect island
 * mounts on `data-points` (#5578): each point carries its prewritten label.
 */
export function sparkline({ rows, tile, markDate, mean, size = 14 }) {
  const W = 180;
  const H = 36;
  const pad = 4;
  const vals = rows.map((r) => r.readings[tile.key]);
  const live = vals.filter((v) => v != null);
  const aria = `${tile.label}, the fourteen days ending ${dayInWords(markDate, { weekday: true }).replace(/ \d{4}$/, "")}`;
  if (live.length < 2) return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}: too few readings to draw"></svg>`;
  const ext = mean != null ? [...live, mean] : live;
  const lo = Math.min(...ext);
  const hi = Math.max(...ext);
  const offset = size - rows.length; // a short window sits at the right, under its own days
  const X = (i) => pad + ((i + offset) / (size - 1)) * (W - 2 * pad);
  const Y = (v) => pad + (1 - (v - lo) / (hi - lo || 1)) * (H - 2 * pad);
  let d = "";
  let pen = false;
  const points = [];
  rows.forEach((r, i) => {
    const v = r.readings[tile.key];
    if (v == null) {
      pen = false;
      return;
    }
    const x = Number(X(i).toFixed(1));
    const y = Number(Y(v).toFixed(1));
    d += `${pen ? "L" : "M"}${x},${y}`;
    pen = true;
    const unit = tile.unit ? ` ${tile.unit}` : "";
    points.push({ x, y, date: r.date, v, label: `${dayInWords(r.date, { weekday: true }).replace(/ \d{4}$/, "")} · ${num(v, tile.decimals)}${unit}` });
  });
  const mi = rows.findIndex((r) => r.date === markDate);
  const mark = mi >= 0 && vals[mi] != null ? `<circle class="mark" cx="${X(mi).toFixed(1)}" cy="${Y(vals[mi]).toFixed(1)}" r="3.2"/>` : "";
  const meanLine = mean != null ? `<line class="mean" x1="${pad}" x2="${W - pad}" y1="${Y(mean).toFixed(1)}" y2="${Y(mean).toFixed(1)}"/>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}" data-points="${esc(JSON.stringify(points))}">${meanLine}<path d="${d}"/>${mark}</svg>`;
}

// ── M4 (#5586): the day's layers 2–3 — the session, the night, the food, the engine, the coaches,
// the calls. Every figure is the exporter's (scripts/publish_snapshot_day.py); these functions place
// and word them, and say in place why a block the platform could not serve is empty.

/** The session's title without Hevy's program counters: "Foundation - Upper - 13 - 41" → "Foundation · Upper". */
export function sessionTitle(title) {
  return String(title || "")
    .replace(/(\s+-\s+\d+)+\s*$/, "")
    .split(/\s+-\s+/)
    .join(" · ");
}

/**
 * The session table rows. Working sets are every non-warm-up set that carries reps or a load; the top
 * set is the heaviest working set; a block with neither is "no load logged" (treadmill, stretching).
 * `heavy` marks a top set of 100 kg or more (the owner's emphasis).
 */
export function sessionRows(workout) {
  if (!workout) return [];
  return workout.exercises.map((e) => {
    const warm = e.sets.filter((s) => s.type === "warmup").length;
    const work = e.sets.filter((s) => s.type !== "warmup" && (s.reps != null || s.weight_kg != null));
    const top = work.reduce((a, s) => (!a || (s.weight_kg || 0) > (a.weight_kg || 0) ? s : a), null);
    const setWords = work.map((s) => {
      const load = s.weight_kg != null ? `${plain(s.weight_kg, 1)} kg` : "bodyweight";
      const reps = s.reps != null ? `${plain(s.reps, 0)} × ` : "";
      return `${reps}${load}${s.rpe != null ? ` @${plain(s.rpe, 1)}` : ""}`;
    });
    return {
      name: e.name,
      warmups: warm,
      blocks: e.sets.length,
      noLoad: work.length === 0,
      sets: setWords,
      top: top && top.weight_kg != null ? `${plain(top.weight_kg, 1)} kg${top.reps != null ? ` × ${plain(top.reps, 0)}` : ""}` : "—",
      heavy: Boolean(top && top.weight_kg != null && top.weight_kg >= 100),
    };
  });
}

/** "143 minutes · 9 exercises · 7,932 kg moved (17,487 lb)". */
export function sessionLine(workout) {
  const parts = [];
  if (workout.duration_min != null) parts.push(`${num(workout.duration_min, 0)} minutes`);
  parts.push(`${workout.exercises.length} exercise${workout.exercises.length === 1 ? "" : "s"}`);
  if (workout.volume_kg != null) parts.push(`${num(Math.round(workout.volume_kg), 0)} kg moved (${num(Math.round(workout.volume_kg * 2.20462), 0)} lb)`);
  return parts.join(" · ");
}

/** The clock time someone fell asleep, in Pacific: "23:56 Pacific". */
export function fellAsleep(iso) {
  if (!iso) return null;
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return null;
  return `${t.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "America/Los_Angeles" })} Pacific`;
}

/** The stage rows: share of the night, then each device's hours. */
export function stageRows(night) {
  const bed = night.by_device.eightsleep;
  const strap = night.by_device.whoop;
  const h = (dev, k) => (dev && dev[k] != null ? `${num(dev[k], 2).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "")} h` : "—");
  return [
    ["Deep", "deep_pct", "deep_hours"],
    ["REM", "rem_pct", "rem_hours"],
    ["Light", "light_pct", "light_hours"],
  ].map(([label, pk, hk]) => ({
    label,
    value: `${night[pk] != null ? `${plain(night[pk], 1)}% of the night` : "share not served"} · ${h(bed, hk)} bed · ${h(strap, hk)} strap`,
  }));
}

/** The stages bar's label (role=img): what the bar draws, in words. */
export function stagesLabel(night) {
  const p = (v) => (v == null ? "not served" : `${plain(v, 1)} percent`);
  return `The night's stages: deep ${p(night.deep_pct)}, REM ${p(night.rem_pct)}, light ${p(night.light_pct)}`;
}

/**
 * Recovery, decomposed: recovery against its 7-day mean, HRV against its 30-day mean (with n), resting
 * heart rate against its 7-day mean, sleep against the platform's target. Bars are a share of a fixed
 * scale; a missing reading is a dash, never a zero.
 */
export function recoveryRows(day) {
  const r = day.readings;
  const m = day.normals;
  const mean = (k, span, d) => (m[k] && m[k][`mean${span}`] != null ? num(m[k][`mean${span}`], d) : null);
  return [
    { label: "Recovery", v: r.recovery_pct, max: 100, d: 0, text: r.recovery_pct == null ? "no reading" : `${num(r.recovery_pct, 0)} of 100${mean("recovery_pct", 7, 0) ? ` · 7-day mean ${mean("recovery_pct", 7, 0)}` : ""}` },
    {
      label: "HRV",
      v: r.hrv_ms,
      max: 100,
      d: 1,
      text: r.hrv_ms == null ? "no reading" : `${num(r.hrv_ms, 1)} ms${mean("hrv_ms", 30, 1) ? ` · 30-day mean ${mean("hrv_ms", 30, 1)} (n=${m.hrv_ms.n30})` : ""}`,
    },
    { label: "Resting HR", v: r.rhr_bpm, max: 100, d: 0, text: r.rhr_bpm == null ? "no reading" : `${num(r.rhr_bpm, 0)} bpm${mean("rhr_bpm", 7, 0) ? ` · 7-day mean ${mean("rhr_bpm", 7, 0)}` : ""} · lower is better` },
    { label: "Sleep", v: r.sleep_hours, max: 10, d: 1, text: r.sleep_hours == null ? "no reading" : `${num(r.sleep_hours, 1)} h of a ${plain(day.sleep_target_h, 1)} h target` },
  ].map((x) => ({ ...x, width: x.v == null ? 0 : Math.max(0, Math.min(100, (x.v / x.max) * 100)), value: x.v == null ? "—" : num(x.v, x.d) }));
}

/** The food rows, as logged. */
export function foodRows(food) {
  const g = (v) => (v == null ? "not logged" : `${num(v, 0)} g`);
  return [
    ["Calories logged", food.calories == null ? "not logged" : `${num(food.calories, 0)} kcal${food.tdee != null ? ` · maintenance about ${num(food.tdee, 0)}` : ""}`],
    ["Protein", `${g(food.protein_g)}${food.floor_g != null ? ` · floor ${num(food.floor_g, 0)} g` : ""}`],
    ["Carbohydrate", g(food.carbs_g)],
    ["Fat", g(food.fat_g)],
  ];
}

const PILLAR_WORDS = { sleep: "Sleep", movement: "Movement", nutrition: "Nutrition", metabolic: "Metabolic", mind: "Mind", relationships: "Relationships", consistency: "Consistency" };

/** The engine's seven areas: an area with no instrument is "absent", never a number. */
export function engineRows(engine) {
  return engine.pillars.map((p) => ({
    label: PILLAR_WORDS[p.name] || p.name,
    absent: p.not_instrumented || p.score == null,
    value: p.not_instrumented || p.score == null ? "absent" : num(p.score, 0),
    width: p.not_instrumented || p.score == null ? 0 : Math.max(0, Math.min(100, p.score)),
    low: !p.not_instrumented && p.score != null && p.score < 20,
  }));
}

/** "Level 15 · 43.1 of 100 · up 0.6 since the morning before". */
export function engineLine(engine) {
  const parts = [`Level ${num(engine.level, 0)}`];
  if (engine.composite != null) parts.push(`composite ${num(engine.composite, 1)} of 100`);
  if (engine.delta != null) parts.push(engine.delta === 0 ? "unchanged since the morning before" : `${engine.delta > 0 ? "up" : "down"} ${num(Math.abs(engine.delta), 1)} since the morning before`);
  return parts.join(" · ");
}

/** The latest day before index i that graded a call, or null. */
export function nearestGraded(days, i) {
  for (let j = i - 1; j >= 0; j--) if (days[j].calls_settled && days[j].calls_settled.length) return days[j];
  return null;
}

/**
 * The in-place sentence for a block the platform did not serve for this day. `when` is the day in words
 * ("Thursday 29 October"). Never another day's content, never blank.
 */
export function unservedText(block, state, when) {
  const T = {
    workout: {
      "none logged": `No gym session was logged on ${when}.`,
      "older than the served window": `${when} is older than the window the workouts endpoint served for this snapshot; the session, if any, is in the record but not readable here.`,
      "not served": `The workouts endpoint did not answer for this snapshot, so the session is not readable here. Nothing stands in for it.`,
    },
    night: {
      "none recorded": `No night's stages were recorded for the night before ${when}. The hours and recovery in the readings come from the daily record.`,
      "older than the served window": `${when} is older than the window the sleep endpoint served for this snapshot; the stages are not readable here.`,
      "not served": `The sleep endpoint did not answer for this snapshot, so the night's stages are not readable here.`,
    },
    food: {
      "not logged": `Nothing was logged on ${when}. The platform treats a day with no entries as missing, not as eaten: no intake is shown, and none is assumed.`,
      "older than the served window": `${when} is older than the window the nutrition endpoint served for this snapshot; the log is not readable here.`,
      "not served": `The nutrition endpoint did not answer for this snapshot, so the food log is not readable here. No intake is assumed.`,
    },
  };
  return (T[block] && T[block][state]) || `Not readable for ${when}.`;
}

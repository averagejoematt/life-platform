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

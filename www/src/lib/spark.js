// The ONE weekly spark (review 2026-11-14, dataviz-1 and dataviz-2; owner ruling 2026-11-14: "a shared rendering
// contract — bars must use defensible baselines; trends may use appropriately labeled nonzero domains").
//
// What was wrong. The front page and the data room each drew their own eight weekly means. The data room scaled its
// bars from the series' minimum to its maximum with a 4-px floor, so the smallest week always drew as a stub and any
// change at all filled the box — a 12% fall in weight read as a collapse. The front page scaled from zero, so the
// same series read as flat. One series, two verdicts, and neither scale was stated.
//
// The contract, a pure function of the values (so the same series is the same picture on every page):
//   * BARS start at zero, always. A bar's height is its value over the largest value — no floor, no offset. A week of
//     zero draws no bar, only the baseline.
//   * When the weeks differ by less than TREND_BELOW of their level, bars from zero would hide the change and bars
//     from anywhere else would invent one. Then it is a TREND: a line on the series' own range, and the range is
//     printed beside it (scaleWords) — a nonzero scale is never drawn unlabelled.
//   * A missing week is a dashed hollow tick on the baseline in both forms; nothing is interpolated across it.
import { num } from "./format.js";

export const TREND_BELOW = 0.25;
export const SPARK_W = 96;
export const SPARK_H = 32;
const SLOT = 12;
const INK = "#121212";
const GREY = "#C9C9C3";
const MUTED = "#B9B9B3";
const COBALT = "#1B3FD6";

/** Which form a set of weekly values takes, and on what scale: {kind: "empty"|"bars"|"trend", lo, hi}. */
export function sparkPlan(values) {
  const vals = (values || []).filter((v) => typeof v === "number" && Number.isFinite(v));
  if (!vals.length) return { kind: "empty", lo: null, hi: null };
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  if (lo < 0 || hi <= 0) return { kind: "trend", lo, hi }; // a signed series has no zero baseline to stand on
  if (vals.length >= 2 && hi > lo && (hi - lo) / hi < TREND_BELOW) return { kind: "trend", lo, hi };
  return { kind: "bars", lo: 0, hi };
}

/** The scale in words, for the label under the spark: bars say they start at zero; a line names the range it is drawn on. Null when empty. */
export function scaleWords(plan, { decimals = 0, unit = "" } = {}) {
  if (!plan || plan.kind === "empty") return null;
  if (plan.kind === "bars") return "weekly means · bars from zero";
  return `weekly means ${num(plan.lo, decimals)} to ${num(plan.hi, decimals)}${unit ? ` ${unit}` : ""} · line on that range`;
}

const tick = (i, h) => `<rect x="${i * SLOT + 0.5}" y="${h - 4.5}" width="9" height="4" fill="none" stroke="${MUTED}" stroke-dasharray="2 2"/>`;

/**
 * The spark for eight weekly values (null = no reading that week): {svg, plan}. `faint` draws the latest week in grey
 * (a dimension with no public reading). The picture depends on nothing but `values` and `faint`.
 */
export function weeklySpark(values, { faint = false } = {}) {
  const W = SPARK_W;
  const H = SPARK_H;
  const slots = values && values.length ? values : new Array(8).fill(null);
  const plan = sparkPlan(slots);
  const lastIdx = slots.reduce((acc, v, i) => (v != null ? i : acc), -1);
  let g = "";
  if (plan.kind === "bars") {
    g += `<line x1="0" y1="${H - 0.5}" x2="${W}" y2="${H - 0.5}" stroke="${MUTED}" stroke-width="1"/>`;
    slots.forEach((v, i) => {
      if (v == null) return void (g += tick(i, H));
      const h = (v / plan.hi) * (H - 1);
      if (h > 0) g += `<rect x="${i * SLOT}" y="${(H - 1 - h).toFixed(1)}" width="10" height="${h.toFixed(1)}" fill="${i === lastIdx && !faint ? COBALT : GREY}"/>`;
    });
  } else if (plan.kind === "trend") {
    const pad = 4;
    const y = (v) => (plan.hi === plan.lo ? H / 2 : pad + (1 - (v - plan.lo) / (plan.hi - plan.lo)) * (H - 2 * pad));
    const x = (i) => i * SLOT + 5;
    let run = [];
    const flush = () => {
      if (run.length > 1) g += `<polyline fill="none" stroke="${INK}" stroke-width="1.5" points="${run.join(" ")}"/>`;
      run = [];
    };
    slots.forEach((v, i) => {
      if (v == null) {
        flush();
        g += tick(i, H);
        return;
      }
      run.push(`${x(i)},${y(v).toFixed(1)}`);
    });
    flush();
    slots.forEach((v, i) => {
      if (v == null) return;
      const last = i === lastIdx && !faint;
      g += `<circle cx="${x(i)}" cy="${y(v).toFixed(1)}" r="${last ? 3 : 2}" fill="${last ? COBALT : INK}"/>`;
    });
  } else {
    for (let i = 0; i < slots.length; i++) g += tick(i, H);
  }
  return { svg: `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true" data-spark-kind="${plan.kind}">${g}</svg>`, plan };
}

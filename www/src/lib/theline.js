// The Line (2026-11-14, sprint II): the front page's signature figure — every morning on the scale since day one,
// drawn as an editorial figure rather than an instrument. Pure, like journey.js: the build draws it once and the
// island redraws it at the container's own width on a phone (#1210 — labels keep their pixel size).
//
// What it draws, and only that: each published weigh-in (a dot), a line through consecutive readings (a dashed
// line where mornings are missing — the line never pretends to know them), the pounds below the first reading
// shaded only across runs of real readings (a missing morning leaves a visible slot), the ten-pound rungs the
// platform published with their crossing dates, and the published chapters as numbered ticks along the foot.
// No smoothing, no projection, no goal date: the future is not on this figure.
// The same function draws a chapter's window (`from`/`to`, `focus`) so a chapter can show its own week in context.
import { esc } from "./chart.js";
import { dayInWords, num } from "./format.js";

const DAY_MS = 86400000;
const t = (iso) => Date.parse(`${iso}T00:00:00Z`);
const INK = "#121212";
const MUTED = "#5C5C58";
const RULE = "#C9C9C3";
const COBALT = "#1B3FD6";
const PAPER = "#F4F4F0";

/**
 * @param {{
 *   days: Array<{date:string,value:number|null,gap?:boolean}>,
 *   startDate?: string|null, startValue?: number|null,
 *   rungs?: Array<{lb:number,date:string|null}>,
 *   chapters?: Array<{date:string,n:string}>,
 *   from?: string, to?: string, focus?: {from:string,to:string}|null,
 *   width?: number, height?: number, mobile?: boolean, aria?: string, unit?: string, shade?: boolean,
 * }} o
 */
export function theLine(o) {
  const mobile = Boolean(o.mobile);
  const W = o.width || (mobile ? 350 : 1240);
  const H = o.height || (mobile ? 280 : 400);
  const fs = mobile ? 12.5 : 12;
  const unit = o.unit || "lb";
  const all = (o.days || []).filter((d) => d && d.date);
  const days = all.filter((d) => (!o.from || d.date >= o.from) && (!o.to || d.date <= o.to));
  const readings = days.filter((d) => d.value != null && !d.gap);
  if (!readings.length) return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "no weigh-ins")}"></svg>`;
  const pad = { l: mobile ? 8 : 14, r: mobile ? 8 : 14, t: mobile ? 34 : 40, b: (o.chapters || []).length ? (mobile ? 52 : 56) : 30 };
  const x0 = t(days[0].date);
  const x1 = t(days[days.length - 1].date);
  const X = (iso) => pad.l + ((t(iso) - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const startV = o.startValue != null ? o.startValue : readings[0].value;
  const vals = readings.map((d) => d.value);
  const hiV = Math.max(startV, ...vals);
  const loV = Math.min(...vals);
  const m = Math.max(1, (hiV - loV) * 0.08);
  const lo = loV - m;
  const hi = hiV + m * 0.6;
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const baseY = H - pad.b;

  // label collision boxes (IBM Plex Mono: 0.6 em per glyph), the journey chart's rule: a label moves, never shrinks
  const boxes = [];
  const boxOf = (x, y, s, anchor) => {
    const w = s.length * fs * 0.6;
    const l = anchor === "end" ? x - w : anchor === "middle" ? x - w / 2 : x;
    return { l, r: l + w, t: y - fs, b: y + fs * 0.3 };
  };
  const hits = (b) => boxes.some((q) => b.l < q.r + 3 && b.r > q.l - 3 && b.t < q.b && b.b > q.t);
  let labels = "";
  const label = (x, ys, s, anchor = "start", fill = MUTED, weight = 400) => {
    const w = s.length * fs * 0.6;
    if (anchor === "start" && x + w > W - pad.r) [x, anchor] = [W - pad.r, "end"];
    if (anchor === "end" && x - w < pad.l) [x, anchor] = [pad.l, "start"];
    if (anchor === "middle" && x + w / 2 > W - pad.r) [x, anchor] = [W - pad.r, "end"];
    if (anchor === "middle" && x - w / 2 < pad.l) [x, anchor] = [pad.l, "start"];
    const slots = Array.isArray(ys) ? ys : [ys];
    const y = slots.find((yy) => !hits(boxOf(x, yy, s, anchor)));
    if (y == null) return false; // no room: the label is dropped, never stacked on another
    boxes.push(boxOf(x, y, s, anchor));
    labels += `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" font-weight="${weight}" fill="${fill}" stroke="${PAPER}" stroke-width="4" stroke-linejoin="round" paint-order="stroke">${esc(s)}</text>`;
    return true;
  };

  let g = "";
  // the focus window (a chapter's days), a pale band behind everything
  if (o.focus && o.focus.from && o.focus.to) {
    const a = X(o.focus.from < days[0].date ? days[0].date : o.focus.from) - (W - pad.l - pad.r) / Math.max(1, days.length) / 2;
    const b = X(o.focus.to > days[days.length - 1].date ? days[days.length - 1].date : o.focus.to) + (W - pad.l - pad.r) / Math.max(1, days.length) / 2;
    g += `<rect x="${Math.max(pad.l, a).toFixed(1)}" y="${pad.t - 10}" width="${(Math.min(W - pad.r, b) - Math.max(pad.l, a)).toFixed(1)}" height="${(baseY - pad.t + 10).toFixed(1)}" fill="#E3E3DD"/>`;
  }
  // the first reading's level, carried across: everything below it, over real readings, is weight lost
  const sY = Y(startV);
  g += `<line x1="${pad.l}" y1="${sY.toFixed(1)}" x2="${W - pad.r}" y2="${sY.toFixed(1)}" stroke="${INK}" stroke-width="1"/>`;
  // shaded runs: consecutive mornings with a reading; a missing morning breaks the run (a visible slot)
  const runs = [];
  let run = [];
  days.forEach((d) => {
    if (d.value != null && !d.gap) run.push(d);
    else if (run.length) (runs.push(run), (run = []));
  });
  if (run.length) runs.push(run);
  const halfDay = (W - pad.l - pad.r) / Math.max(1, (x1 - x0) / DAY_MS) / 2;
  for (const r of o.shade === false ? [] : runs) {
    const a = Math.max(pad.l, X(r[0].date) - (r.length === 1 ? halfDay * 0.8 : 0));
    const b = Math.min(W - pad.r, X(r[r.length - 1].date) + (r.length === 1 ? halfDay * 0.8 : 0));
    let d = `M${a.toFixed(1)},${sY.toFixed(1)}`;
    if (r.length === 1) d += ` L${a.toFixed(1)},${Y(r[0].value).toFixed(1)} L${b.toFixed(1)},${Y(r[0].value).toFixed(1)}`;
    else r.forEach((p) => (d += ` L${X(p.date).toFixed(1)},${Y(p.value).toFixed(1)}`));
    d += ` L${b.toFixed(1)},${sY.toFixed(1)} Z`;
    g += `<path d="${d}" fill="${COBALT}" opacity="0.1"/>`;
  }
  // the ten-pound rungs, at their published crossing dates
  for (const r of o.rungs || []) {
    if (!r.date || r.date < days[0].date || r.date >= readings[readings.length - 1].date || r.lb < lo || r.lb > hi) continue;
    const ry = Y(r.lb);
    g += `<line x1="${X(r.date).toFixed(1)}" y1="${ry.toFixed(1)}" x2="${(W - pad.r).toFixed(1)}" y2="${ry.toFixed(1)}" stroke="${RULE}" stroke-width="1" stroke-dasharray="2 4"/>`;
  }
  // the line: solid between consecutive mornings, dashed across missing ones
  let solid = "";
  let dashed = "";
  for (let i = 1; i < readings.length; i++) {
    const a = readings[i - 1];
    const b = readings[i];
    const seg = `M${X(a.date).toFixed(1)},${Y(a.value).toFixed(1)} L${X(b.date).toFixed(1)},${Y(b.value).toFixed(1)}`;
    if ((t(b.date) - t(a.date)) / DAY_MS > 1) dashed += seg;
    else solid += seg;
  }
  let marks = "";
  if (dashed) marks += `<path d="${dashed}" fill="none" stroke="${INK}" stroke-width="1.4" stroke-dasharray="2 3" opacity="0.7"/>`;
  if (solid) marks += `<path d="${solid}" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linejoin="round"/>`;
  const r0 = mobile ? 2.2 : 2.8;
  readings.forEach((d) => {
    marks += `<circle cx="${X(d.date).toFixed(1)}" cy="${Y(d.value).toFixed(1)}" r="${r0}" fill="${INK}"/>`;
    boxes.push({ l: X(d.date) - 3, r: X(d.date) + 3, t: Y(d.value) - 3, b: Y(d.value) + 3 });
  });
  // missing mornings: a hollow tick on the baseline, so the gaps are counted, not hidden
  days.forEach((d) => {
    if (d.value == null || d.gap) g += `<rect x="${(X(d.date) - 1.5).toFixed(1)}" y="${(baseY - 7).toFixed(1)}" width="3" height="7" fill="none" stroke="${MUTED}" stroke-width="1"/>`;
  });
  g += `<line x1="${pad.l}" y1="${baseY.toFixed(1)}" x2="${W - pad.r}" y2="${baseY.toFixed(1)}" stroke="${RULE}" stroke-width="1"/>`;
  // the published chapters, numbered along the foot (plain labels: the chapter list is one click away)
  const chs = (o.chapters || []).filter((c) => c.date >= days[0].date && c.date <= days[days.length - 1].date);
  if (chs.length) {
    const cy = baseY + (mobile ? 22 : 24);
    for (const c of chs) {
      const cx = X(c.date);
      g += `<line x1="${cx.toFixed(1)}" y1="${baseY.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(baseY + 8).toFixed(1)}" stroke="${COBALT}" stroke-width="1.5"/>`;
      label(cx, [cy], c.n, "middle", COBALT, 600);
    }
  }
  // the anchors: the first morning and the latest one
  const first = readings[0];
  const last = readings[readings.length - 1];
  marks += `<circle cx="${X(first.date).toFixed(1)}" cy="${Y(first.value).toFixed(1)}" r="${mobile ? 4 : 5}" fill="${PAPER}" stroke="${INK}" stroke-width="2"/>`;
  marks += `<circle cx="${X(last.date).toFixed(1)}" cy="${Y(last.value).toFixed(1)}" r="${mobile ? 5 : 6}" fill="${COBALT}"/>`;
  label(X(first.date), [Y(first.value) - 12, pad.t - 16], `${num(first.value, 1)} ${unit} · ${dayInWords(first.date, { short: true })}`, "start", INK, 600);
  label(X(last.date) - 10, [Y(last.value) + 4, Y(last.value) - 14, Y(last.value) + 20], `${num(last.value, 1)} ${unit} · ${dayInWords(last.date, { short: true })}`, "end", COBALT, 600);
  for (const r of o.rungs || []) {
    if (!r.date || r.date < days[0].date || r.date >= last.date || r.lb < lo || r.lb > hi) continue;
    const s = mobile ? `${r.lb}` : `${r.lb} lb · ${dayInWords(r.date, { short: true })}`;
    label(W - pad.r, [Y(r.lb) - 5, Y(r.lb) + fs + 3], s, "end");
  }

  const points = readings.map((d) => ({
    x: Number(X(d.date).toFixed(1)),
    y: Number(Y(d.value).toFixed(1)),
    date: d.date,
    v: d.value,
    label: `${dayInWords(d.date, { weekday: true })} · ${num(d.value, 1)} ${unit}${o.startDate && d.date !== o.startDate && o.startValue != null ? ` · ${num(d.value - o.startValue, 1)} since day one` : ""}`,
  }));
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(o.aria || "")}" data-chart data-points="${esc(JSON.stringify(points))}">${g}${marks}${labels}</svg>`;
}

/** Counts for the figure's caption, from the same days the figure draws. */
export function lineCounts(days, from, to) {
  const w = (days || []).filter((d) => (!from || d.date >= from) && (!to || d.date <= to));
  const n = w.filter((d) => d.value != null && !d.gap).length;
  return { days: w.length, readings: n, missing: w.length - n };
}

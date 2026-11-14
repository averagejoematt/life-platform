// Evidence in the margin (2026-11-14, sprint II): small figures a chapter carries beside the paragraph that talks about
// them — the reader sees the week's weight, recovery or protein at the moment the prose reaches it, without leaving the
// story. Pure and generic: every published chapter gets the same three figures from the same public series, placed
// after the first paragraph that names the measure. The chapter's words are never touched; a figure goes BETWEEN
// paragraphs or not at all. Nothing is computed beyond placing published daily values on an axis.
import { esc } from "./chart.js";
import { dayInWords, num } from "./format.js";

const DAY_MS = 86400000;
const t = (iso) => Date.parse(`${iso}T00:00:00Z`);
const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
const WEEKDAY = ["S", "M", "T", "W", "T", "F", "S"];

/** The days a chapter covers: its served interval when the snapshot carries one (`covers_start`..`covers_end`),
 * else the seven days ending on its data date, never before day one. A prologue (week 0) has none. */
export function chapterWindow(c, startDate) {
  if (!c || c.status !== "published" || !(c.week >= 1)) return null;
  if (c.covers_start && c.covers_end) return { from: c.covers_start, to: c.covers_end };
  const to = c.data_through || c.date;
  if (!to) return null;
  let from = iso(t(to) - 6 * DAY_MS);
  if (startDate && from < startDate) from = startDate;
  return { from, to };
}

/** The published days of a series inside a window, one entry per calendar day (a day the series lacks is null). */
export function windowValues(series, from, to) {
  const by = new Map(((series && series.days) || []).map((d) => [d.date, d]));
  const out = [];
  for (let ms = t(from); ms <= t(to); ms += DAY_MS) {
    const d = by.get(iso(ms));
    out.push({ date: iso(ms), value: d && d.value != null && !d.gap ? d.value : null });
  }
  return out;
}

/**
 * Daily bars for a chapter's days: the value over each bar, the weekday under it; a day with no reading is an open
 * dashed slot. With `floor`, a dashed line at the stated floor and bars below it drawn hollow (below the floor is a
 * fact about the day, not a judgement — the colour stays the series' own). The viewBox is 320 wide so a phone column
 * renders the 11.5-unit labels at or above their pixel size (#1210 floor 11 px at 320 px).
 */
export function dailyBars(o) {
  const W = 320;
  const H = o.height || 150;
  const fs = 11.5;
  const pad = { l: 4, r: 4, t: 20, b: 22 };
  const vals = o.values.filter((d) => d.value != null).map((d) => d.value);
  if (!vals.length) return null;
  const hi = Math.max(...vals, o.floor || 0) * 1.08;
  const lo = 0;
  const n = o.values.length;
  const slot = (W - pad.l - pad.r) / n;
  const bw = Math.min(30, slot * 0.62);
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const base = H - pad.b;
  const txt = (x, y, s, fill = "#5C5C58", weight = 400) =>
    `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="${fs}" font-weight="${weight}" fill="${fill}" stroke="#F4F4F0" stroke-width="4" stroke-linejoin="round" paint-order="stroke">${esc(s)}</text>`;
  let g = `<line x1="${pad.l}" y1="${base}" x2="${W - pad.r}" y2="${base}" stroke="#C9C9C3" stroke-width="1"/>`;
  const points = [];
  const lowest = o.markLow ? Math.min(...vals) : null;
  o.values.forEach((d, i) => {
    const cx = pad.l + slot * (i + 0.5);
    const wd = WEEKDAY[new Date(t(d.date)).getUTCDay()];
    g += txt(cx, H - 6, wd, "#5C5C58");
    if (d.value == null) {
      g += `<rect x="${(cx - bw / 2).toFixed(1)}" y="${(base - 10).toFixed(1)}" width="${bw.toFixed(1)}" height="10" fill="none" stroke="#B9B9B3" stroke-dasharray="2 2"/>`;
      return;
    }
    const y = Y(d.value);
    const below = o.floor != null && d.value < o.floor;
    const isLow = lowest != null && d.value === lowest;
    g += below
      ? `<rect x="${(cx - bw / 2 + 0.75).toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 1.5).toFixed(1)}" height="${(base - y).toFixed(1)}" fill="#F4F4F0" stroke="#1B3FD6" stroke-width="1.5"/>`
      : `<rect x="${(cx - bw / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${(base - y).toFixed(1)}" fill="#1B3FD6"/>`;
    g += txt(cx, y - 5, num(d.value, o.decimals || 0), isLow ? "#121212" : "#5C5C58", isLow ? 700 : 400);
    points.push({ x: Number(cx.toFixed(1)), y: Number(y.toFixed(1)), date: d.date, v: d.value, label: `${dayInWords(d.date, { weekday: true })} · ${num(d.value, o.decimals || 0)}${o.unit ? ` ${o.unit}` : ""}` });
  });
  if (o.floor != null) {
    const fy = Y(o.floor);
    g += `<line x1="${pad.l}" y1="${fy.toFixed(1)}" x2="${W - pad.r}" y2="${fy.toFixed(1)}" stroke="#121212" stroke-width="1" stroke-dasharray="5 4"/>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(o.aria || "")}" data-chart data-points="${esc(JSON.stringify(points))}">${g}</svg>`;
}

/** Place each figure after the first body paragraph whose text matches it (signature lines excluded), at most once
 * each and never two figures after one paragraph. A figure whose measure the prose never names is not placed. */
export function placeEvidence(html, figures) {
  if (!html || !figures.length) return { html, placed: [] };
  const used = new Set();
  const placed = [];
  let out = "";
  let last = 0;
  const re = /<p(\s[^>]*)?>([\s\S]*?)<\/p>/gi;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1] || "";
    const end = m.index + m[0].length;
    out += html.slice(last, end);
    last = end;
    if (/class="[^"]*signature/.test(attrs)) continue;
    const text = m[2].replace(/<[^>]+>/g, " ");
    const f = figures.find((x) => !used.has(x.key) && x.match.test(text));
    if (f) {
      used.add(f.key);
      placed.push(f.key);
      out += f.html;
    }
  }
  out += html.slice(last);
  return { html: out, placed };
}

// The one line chart — pure functions, no DOM. The same module draws the build-time SVG on a
// metric page and the explorer island's live redraws, so a reader without JavaScript sees the
// same chart the island would draw. Statistics are NOT computed here: the island reads them
// from the precomputed pairs file (owner requirement A). Proven by tests/chart.test.mjs.

/** A 7-day trailing mean over a daily series; windows with fewer than 3 readings are null. */
export function rollingMean(values, window = 7, minReadings = 3) {
  return values.map((_, i) => {
    const win = values.slice(Math.max(0, i - window + 1), i + 1).filter((v) => v != null && Number.isFinite(v));
    if (win.length < Math.min(minReadings, window)) return null;
    return win.reduce((s, v) => s + v, 0) / win.length;
  });
}

/** Round-number axis ticks covering [lo, hi]. */
export function niceTicks(lo, hi, count = 6) {
  const span = hi - lo || 1;
  const raw = span / (count - 1);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const steps = [1, 2, 2.5, 5, 10];
  const step = steps.map((s) => s * p).find((s) => s >= raw) || 10 * p;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const out = [];
  for (let v = start; v <= end + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000);
  return out;
}

/**
 * Build the path segments of a daily series: a new segment starts after every missing reading
 * or logging gap, so a line never bridges a day that has no value (ADR-104: absence is drawn,
 * not interpolated).
 */
export function segments(days, valueOf = (d) => d.value) {
  const out = [];
  let cur = [];
  days.forEach((d, i) => {
    const v = valueOf(d, i);
    if (v == null || d.gap) {
      if (cur.length) out.push(cur);
      cur = [];
      return;
    }
    cur.push({ i, v });
  });
  if (cur.length) out.push(cur);
  return out;
}

/**
 * Render an SVG string for one or two series of the SAME unit over the same day axis.
 * @param {{
 *   series: Array<{days: Array<{date:string,value:number|null,present:boolean,gap:boolean}>, color:string, name:string}>,
 *   unit?: string, decimals?: number, width?: number, height?: number, mobile?: boolean,
 *   smooth?: boolean, floor?: number|null, dashed?: number|null, clip?: number|null,
 *   markers?: Array<{date:string,label:string}>, labelDay?: (iso:string)=>string, aria?: string
 * }} o
 */
export function svgChart(o) {
  const W = o.width || (o.mobile ? 480 : 1000);
  const H = o.height || 220;
  const padL = o.mobile ? 40 : 44;
  const padR = 12;
  const padT = 12;
  const padB = 26;
  const fs = o.mobile ? 12.5 : 11;
  const days = o.series[0].days;
  const n = days.length;
  if (!n) return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "no readings")}"></svg>`;
  const prepared = o.series.map((s) => {
    const raw = s.days.map((d) => (d.gap ? null : d.value));
    const vals = o.smooth ? rollingMean(raw, 7) : raw;
    return { ...s, raw, vals };
  });
  const all = [];
  for (const s of prepared) for (const v of s.vals) if (v != null) all.push(o.clip ? Math.min(o.clip, v) : v);
  if (o.floor != null) all.push(o.floor);
  if (o.dashed != null) all.push(o.dashed);
  let lo = all.length ? Math.min(...all) : 0;
  let hi = all.length ? Math.max(...all) : 1;
  const dataMin = lo;
  const padv = (hi - lo) * 0.08 || 1;
  lo -= padv;
  hi += padv;
  if (dataMin >= 0) lo = Math.max(0, lo);
  const ticks = niceTicks(lo, hi, 6);
  lo = Math.min(lo, ticks[0]);
  hi = Math.max(hi, ticks[ticks.length - 1]);
  const x = (i) => padL + (W - padL - padR) * (n === 1 ? 0.5 : i / (n - 1));
  const y = (v) => padT + (H - padT - padB) * (hi - (o.clip ? Math.min(o.clip, v) : v)) / (hi - lo || 1);
  const labelDay = o.labelDay || ((iso) => iso.slice(5));
  let g = "";
  for (const t of ticks) {
    const yy = y(t).toFixed(1);
    g += `<line x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}" stroke="#C9C9C3" stroke-width="1"/>`;
    g += `<text x="${padL - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#5C5C58">${t}</text>`;
  }
  if (o.floor != null) g += `<line x1="${padL}" y1="${y(o.floor).toFixed(1)}" x2="${W - padR}" y2="${y(o.floor).toFixed(1)}" stroke="#121212" stroke-width="1"/>`;
  if (o.dashed != null) g += `<line x1="${padL}" y1="${y(o.dashed).toFixed(1)}" x2="${W - padR}" y2="${y(o.dashed).toFixed(1)}" stroke="#121212" stroke-width="1" stroke-dasharray="3 5"/>`;
  const lab = (i, anchor) => `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#5C5C58">${esc(labelDay(days[i].date))}</text>`;
  g += lab(0, "start") + (n > 10 && !o.mobile ? lab(Math.round((n - 1) / 2), "middle") : "") + (n > 1 ? lab(n - 1, "end") : "");
  for (let i = 0; i < n; i++) if (i % 7 === 0 && i > 0) g += `<line x1="${x(i).toFixed(1)}" y1="${H - padB}" x2="${x(i).toFixed(1)}" y2="${H - padB + 5}" stroke="#121212" stroke-width="1"/>`;
  // regime markers: a vertical rule with a small label, drawn under the series
  for (const m of o.markers || []) {
    const i = days.findIndex((d) => d.date === m.date);
    if (i < 0) continue;
    g += `<line x1="${x(i).toFixed(1)}" y1="${padT}" x2="${x(i).toFixed(1)}" y2="${H - padB}" stroke="#B97A12" stroke-width="1" stroke-dasharray="4 4"/>`;
    g += `<text x="${(x(i) + 4).toFixed(1)}" y="${padT + 10}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="#B97A12">${esc(m.label)}</text>`;
  }
  let paths = "";
  prepared.forEach((s) => {
    for (const seg of segments(s.days, (d, i) => s.vals[i])) {
      const d = seg.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
      paths += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    if (o.smooth) {
      s.raw.forEach((v, i) => {
        if (v != null) paths += `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5" fill="${s.color}" opacity="0.35"/>`;
      });
    }
    if (o.clip) {
      s.raw.forEach((v, i) => {
        if (v != null && v > o.clip) paths += `<circle cx="${x(i).toFixed(1)}" cy="${y(o.clip).toFixed(1)}" r="4.5" fill="#F4F4F0" stroke="#D9341C" stroke-width="1.5"/>`;
      });
    }
    let lastI = -1;
    for (let i = n - 1; i >= 0; i--) {
      if (s.vals[i] != null && !s.days[i].gap) {
        lastI = i;
        break;
      }
    }
    if (lastI >= 0) paths += `<circle cx="${x(lastI).toFixed(1)}" cy="${y(s.vals[lastI]).toFixed(1)}" r="4" fill="${s.color}"/>`;
    // gaps (a logging gap, vermillion, hollow) and missing readings (a small hollow square on the baseline)
    s.days.forEach((d, i) => {
      if (d.gap) {
        const yy = d.value == null ? H - padB - 10 : y(d.value);
        paths += `<circle cx="${x(i).toFixed(1)}" cy="${yy.toFixed(1)}" r="4.5" fill="#F4F4F0" stroke="#D9341C" stroke-width="1.5"/>`;
      } else if (d.value == null) {
        paths += `<rect x="${(x(i) - 2).toFixed(1)}" y="${H - padB - 6}" width="4" height="4" fill="#F4F4F0" stroke="#5C5C58" stroke-width="1"/>`;
      }
    });
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "")}" data-chart>${g}${paths}<line class="xh" x1="-10" y1="${padT}" x2="-10" y2="${H - padB}" stroke="#121212" stroke-width="1" stroke-dasharray="2 3"/><rect class="hit" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"/></svg>`;
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Count present readings in a window of days. */
export function presentCount(days) {
  return days.filter((d) => d.value != null && !d.gap).length;
}

/** Slice the last `range` days (or all when range is null). */
export function lastDays(days, range) {
  if (!range || range >= days.length) return days;
  return days.slice(days.length - range);
}

/** The compact one-line reading of a series for a tile: last value, change over the window. */
export function headline(days, decimals = 1) {
  const present = days.filter((d) => d.value != null && !d.gap);
  if (!present.length) return { last: null, first: null, delta: null, n: 0 };
  const first = present[0].value;
  const last = present[present.length - 1].value;
  return { last, first, delta: last - first, n: present.length, firstDate: present[0].date, lastDate: present[present.length - 1].date };
}

/** Tiny bar sparkline of weekly means (eight bars max), for the data index tiles. */
export function weeklyBars(days, weeks = 8) {
  const out = [];
  const tail = days.slice(Math.max(0, days.length - weeks * 7));
  for (let w = 0; w < Math.ceil(tail.length / 7); w++) {
    const chunk = tail.slice(w * 7, w * 7 + 7).filter((d) => d.value != null && !d.gap);
    out.push(chunk.length ? chunk.reduce((s, d) => s + d.value, 0) / chunk.length : null);
  }
  return out;
}

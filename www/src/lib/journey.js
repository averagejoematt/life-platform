// The Journey's instrument (#5579, F02 · F12 · A06 · D02): every weigh-in on the whole distance from
// the start to the goal, the 7-day mean read within each device era, the platform's projection drawn
// as a wedge from the last reading to the goal between its earliest and latest dates, the ten-pound
// rungs and the baseline change. Pure: the same function draws the build-time SVG and the island's
// redraws. Nothing is computed here that the platform did not publish: the rate, the interval, the
// projected dates and the rungs come from journey.json; this module only places them on a time axis.
import { eraMean, esc, pointLabel, svgChart } from "./chart.js";
import { dayInWords } from "./format.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86400000;
const t = (iso) => Date.parse(`${iso}T00:00:00Z`);

/** The last `range` days of a series (null = all), by date. */
export function windowDays(days, range) {
  if (!range || !days.length) return days;
  const last = t(days[days.length - 1].date);
  return days.filter((d) => (last - t(d.date)) / DAY_MS < range);
}

/**
 * @param {{
 *   days: Array<{date:string,value:number|null,present:boolean,gap:boolean}>,
 *   journey: object, rungs: Array<{lb:number,date:string|null}>, markers: Array<{date:string,label:string}>,
 *   chapters?: Array<{date:string,label:string}>,
 *   frame: "distance"|"readings", range: number|null,
 *   show: {mean:boolean, projection:boolean, rungs:boolean, chapters:boolean, events:boolean},
 *   mobile?: boolean, width?: number, height?: number, unit?: string, decimals?: number, aria?: string
 * }} o
 */
export function journeyChart(o) {
  const J = o.journey;
  // On a phone the viewBox is the container's own width (the island passes it), so the 12.5-unit labels
  // render at 12.5 px — a 480-unit box scaled into a 350 px column put them at 9.1 px, under the 11 px
  // floor the visual sweep holds (#1210; the root deploy of #5580 rolled back on it).
  const W = o.width || (o.mobile ? 350 : 1100);
  const H = o.height || (o.mobile ? 300 : 420);
  const pad = { l: o.mobile ? 36 : 46, r: 12, t: 22, b: 30 };
  const fs = o.mobile ? 12.5 : 11;
  const days = windowDays(o.days, o.range);
  const readings = days.filter((d) => d.value != null && !d.gap);
  if (!readings.length) return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "no weigh-ins")}"></svg>`;
  const distance = o.frame === "distance";
  const wedge = Boolean(o.show.projection && distance && !o.range && J && J.projected_goal_date_latest);
  const x0 = t(days[0].date);
  const x1 = wedge ? t(J.projected_goal_date_latest) : t(days[days.length - 1].date);
  const X = (iso) => pad.l + ((t(iso) - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  let lo;
  let hi;
  if (distance && J) {
    lo = J.goal_weight_lbs - 6;
    hi = J.start_weight_lbs + 4;
  } else {
    const v = readings.map((d) => d.value);
    const m = (Math.max(...v) - Math.min(...v)) * 0.12 || 1;
    lo = Math.min(...v) - m;
    hi = Math.max(...v) + m;
  }
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const txt = (x, y, s, anchor = "start", fill = "#5C5C58") =>
    `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="${fill}">${esc(s)}</text>`;
  let g = "";
  // y ticks
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const v = lo + ((hi - lo) * i) / ticks;
    g += `<line x1="${pad.l}" y1="${Y(v).toFixed(1)}" x2="${W - pad.r}" y2="${Y(v).toFixed(1)}" stroke="#C9C9C3" stroke-width="1"/>`;
    g += txt(pad.l - 6, Y(v) + 4, String(Math.round(v)), "end");
  }
  // month ticks
  const cur = new Date(x0);
  cur.setUTCDate(1);
  cur.setUTCMonth(cur.getUTCMonth() + 1);
  while (cur.getTime() <= x1) {
    const iso = cur.toISOString().slice(0, 10);
    g += txt(X(iso), H - 9, MONTHS[cur.getUTCMonth()], "middle");
    cur.setUTCMonth(cur.getUTCMonth() + 1);
  }
  if (distance && J) {
    g += `<line x1="${pad.l}" y1="${Y(J.start_weight_lbs).toFixed(1)}" x2="${W - pad.r}" y2="${Y(J.start_weight_lbs).toFixed(1)}" stroke="#121212" stroke-width="1"/>`;
    g += txt(W - pad.r, Y(J.start_weight_lbs) - 5, `start ${J.start_weight_lbs}`, "end", "#121212");
    g += `<line x1="${pad.l}" y1="${Y(J.goal_weight_lbs).toFixed(1)}" x2="${W - pad.r}" y2="${Y(J.goal_weight_lbs).toFixed(1)}" stroke="#121212" stroke-width="1" stroke-dasharray="5 5"/>`;
    g += txt(W - pad.r, Y(J.goal_weight_lbs) - 5, `goal ${Math.round(J.goal_weight_lbs)}`, "end", "#121212");
  }
  if (o.show.rungs) {
    for (const r of o.rungs || []) {
      if (!r.date || t(r.date) < x0 || t(r.date) > x1 || r.lb < lo || r.lb > hi) continue;
      g += `<line x1="${pad.l}" y1="${Y(r.lb).toFixed(1)}" x2="${X(r.date).toFixed(1)}" y2="${Y(r.lb).toFixed(1)}" stroke="#C9C9C3" stroke-width="1" stroke-dasharray="2 4"/>`;
      g += txt(pad.l + 6, Y(r.lb) - 4, `${r.lb} · ${dayInWords(r.date, { short: true })}`);
    }
  }
  if (o.show.chapters) {
    for (const c of o.chapters || []) {
      if (t(c.date) < x0 || t(c.date) > t(days[days.length - 1].date)) continue;
      g += `<line x1="${X(c.date).toFixed(1)}" y1="${pad.t}" x2="${X(c.date).toFixed(1)}" y2="${pad.t + 8}" stroke="#8A8A85" stroke-width="1"/>`;
      g += txt(X(c.date), pad.t - 6, c.label, "middle");
    }
  }
  if (o.show.events) {
    for (const m of o.markers || []) {
      if (t(m.date) < x0 || t(m.date) > x1) continue;
      g += `<line x1="${X(m.date).toFixed(1)}" y1="${pad.t}" x2="${X(m.date).toFixed(1)}" y2="${H - pad.b}" stroke="#B97A12" stroke-width="1" stroke-dasharray="4 4"/>`;
      g += txt(X(m.date) + 4, pad.t + 10, m.label, "start", "#B97A12");
    }
  }
  if (wedge) {
    const lastR = readings[readings.length - 1];
    const lx = X(lastR.date);
    const ly = Y(lastR.value);
    const gy = Y(J.goal_weight_lbs);
    g += `<path d="M${lx.toFixed(1)},${ly.toFixed(1)} L${X(J.projected_goal_date_earliest).toFixed(1)},${gy.toFixed(1)} L${X(J.projected_goal_date_latest).toFixed(1)},${gy.toFixed(1)} Z" fill="#1B3FD6" opacity="0.1"/>`;
    g += `<path d="M${lx.toFixed(1)},${ly.toFixed(1)} L${X(J.projected_goal_date).toFixed(1)},${gy.toFixed(1)}" fill="none" stroke="#1B3FD6" stroke-width="1" stroke-dasharray="4 4"/>`;
    g += txt(X(J.projected_goal_date), gy + 16, dayInWords(J.projected_goal_date), "middle");
  }
  // the series: readings as dots, the mean read within each era
  const breakIdx = new Set((o.markers || []).map((m) => days.findIndex((d) => d.date === m.date)).filter((i) => i > 0));
  const raw = days.map((d) => (d.gap ? null : d.value));
  const mean = o.show.mean ? eraMean(raw, breakIdx) : null;
  let paths = "";
  days.forEach((d, i) => {
    if (raw[i] != null) paths += `<circle cx="${X(d.date).toFixed(1)}" cy="${Y(raw[i]).toFixed(1)}" r="${o.show.mean ? 2.6 : 3.2}" fill="#121212" opacity="${o.show.mean ? 0.35 : 0.8}"/>`;
  });
  if (mean) {
    let d = "";
    let pen = false;
    days.forEach((day, i) => {
      if (mean[i] == null || (breakIdx.has(i) && pen)) pen = false;
      if (mean[i] == null) return;
      d += `${pen ? "L" : "M"}${X(day.date).toFixed(1)},${Y(mean[i]).toFixed(1)}`;
      pen = true;
    });
    if (d) paths += `<path d="${d}" fill="none" stroke="#1B3FD6" stroke-width="2.2" stroke-linejoin="round"/>`;
  }
  const lastR = readings[readings.length - 1];
  paths += `<circle cx="${X(lastR.date).toFixed(1)}" cy="${Y(lastR.value).toFixed(1)}" r="4.5" fill="#1B3FD6"/>`;
  // the inspectable points, labelled: the morning, the weight, since the start, vs the previous weigh-in
  const opts = { unit: o.unit || "lb", decimals: o.decimals == null ? 1 : o.decimals };
  const points = readings.map((d, i) => {
    const prev = readings[i - 1];
    let label = pointLabel(d, d.value, opts, null);
    if (J) label += ` · ${(d.value - J.start_weight_lbs).toFixed(1)} since the start`;
    if (prev) label += ` · ${d.value - prev.value >= 0 ? "+" : ""}${(d.value - prev.value).toFixed(1)} vs ${dayInWords(prev.date, { weekday: true }).split(" ")[0]}`;
    return { x: Number(X(d.date).toFixed(1)), y: Number(Y(d.value).toFixed(1)), date: d.date, v: d.value, label };
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "")}" data-chart data-points="${esc(JSON.stringify(points))}">${g}${paths}</svg>`;
}

/** The caption under the instrument, from the same state. */
export function journeyCaption(o) {
  const days = windowDays(o.days, o.range);
  const n = days.filter((d) => d.value != null && !d.gap).length;
  const wedge = o.show.projection && o.frame === "distance" && !o.range && o.journey;
  const parts = [
    `${n} weigh-ins${o.range ? " in the window" : ` since ${dayInWords(days[0] ? days[0].date : o.journey.start_date)}`}`,
    `the dots are mornings on the scale${o.show.mean ? ", the cobalt line the 7-day mean" : ""}`,
  ];
  if (wedge) parts.push("the wedge is the platform's projection to the goal, its edges the 80% range of the date");
  if (o.show.events && (o.markers || []).length) parts.push(`the ochre line is the baseline change on ${dayInWords(o.markers[0].date)}`);
  return `${parts.join(" · ")}. Hover, tap or use the arrow keys to read a morning.`;
}

// ── layers 2–3 (#5583): the pace, the ladder, the body, the heart beside the weight, the calls ──────
// Still placement only. The one published rate is drawn with its published interval (no other window's
// slope is computed — owner requirement A); the ladder reads the published rungs; the heart captions are
// plain means of the readings the chart shows, said as such on the page.

/** The pace bar: the published weekly rate and its 95% interval as percentages of one shared scale. */
export function paceBar(J) {
  const rate = Number(J.weekly_rate_lbs);
  const a = Math.abs(Number(J.weekly_rate_ci_low));
  const b = Math.abs(Number(J.weekly_rate_ci_high));
  const max = Math.max(Math.abs(rate), a, b) * 1.25 || 1;
  const crossesZero = Number(J.weekly_rate_ci_low) <= 0 && Number(J.weekly_rate_ci_high) >= 0;
  const pct = (v) => Math.round((v / max) * 1000) / 10;
  return {
    bar: pct(Math.abs(rate)),
    ciLeft: crossesZero ? 0 : pct(Math.min(a, b)),
    ciWidth: crossesZero ? pct(Math.max(a, b)) : pct(Math.abs(a - b)),
    excludesZero: !crossesZero,
    losing: rate < 0,
  };
}

/** The milestones ladder: crossed rungs, the next one (with its distance from the last weigh-in), the rest. */
export function ladderRows(rungs, current) {
  const next = (rungs || []).find((r) => !r.date) || null;
  return (rungs || []).map((r, i) => {
    if (r.date) {
      const since = i === 0 ? "from the start" : `after ${rungs[i - 1].lb}`;
      return { lb: r.lb, cls: "hit", right: `crossed ${dayInWords(r.date, { short: true })} · ${r.days} days ${since}` };
    }
    if (r === next) return { lb: r.lb, cls: "next", right: `${(Math.round((current - r.lb) * 10) / 10).toFixed(1)} lb away` };
    return { lb: r.lb, cls: "future", right: "" };
  });
}

/** The published chapter of the week each rung fell: a chapter's date closes its week (the 7 days ending on it). */
export function rungChapters(rungs, chapters) {
  const out = [];
  for (const r of rungs || []) {
    if (!r.date) continue;
    const c = (chapters || []).find((ch) => ch.status === "published" && ch.week >= 1 && t(r.date) <= t(ch.date) && t(ch.date) - t(r.date) < 7 * DAY_MS);
    if (c) out.push({ lb: r.lb, date: r.date, chapter: c });
  }
  return out;
}

/** A plain mean of the readings in a list of days (no weighting, no smoothing), with its count. */
export function plainMean(days) {
  const v = (days || []).filter((d) => d.value != null && !d.gap).map((d) => d.value);
  return { mean: v.length ? v.reduce((s, x) => s + x, 0) / v.length : null, n: v.length };
}

/** The first seven and the latest seven displayed days of a heart series since day one. */
export function heartWeeks(days) {
  return { first: plainMean(days.slice(0, 7)), last: plainMean(days.slice(-7)) };
}

/** The visceral-fat band on the previous site's scale (under 1 lb low · 1 to 2 moderate · over 2 elevated). */
export function visceralBand(lb) {
  if (lb == null) return null;
  return lb < 1 ? "low" : lb <= 2 ? "moderate" : "elevated";
}

/** "99th", "1st", "22nd", "13th". */
export function ordinal(n) {
  const v = Math.round(Number(n));
  const s = v % 100 >= 11 && v % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[v % 10] || "th";
  return `${v}${s}`;
}

/** A heart series since day one, drawn by the one line chart (eras broken at the baseline change, data-points emitted).
 * `width` is the container's own width when the island redraws, so the labels render at their unit size (#1210). */
export function heartChart(o) {
  return svgChart({
    series: [{ days: o.days, color: "#1B3FD6", name: o.name }],
    width: o.width || 500,
    height: o.height || 240,
    mobile: Boolean(o.mobile),
    smooth: true,
    markers: o.markers || [],
    labelDay: (iso) => dayInWords(iso, { short: true }) || "",
    unit: o.unit || "",
    decimals: o.decimals == null ? 0 : o.decimals,
    aria: o.aria || "",
  });
}

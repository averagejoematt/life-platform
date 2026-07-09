/*
  charts.js — tiny inline-SVG charts (zero deps). Shared across the three doors.
  Returns SVG strings; styling is token-driven via CSS classes (chart-line =
  ember, chart-fill = ember wash, chart-goal = dashed muted, chart-down = muted).
  Non-scaling strokes so responsive stretching never thickens lines. Honours the
  design system: ember for the live signal, muted ink for flat/goal, never red.
*/
const escAttr = (s) => String(s == null ? "" : s).replace(/"/g, "&quot;").replace(/</g, "&lt;");

// Dual-unit weight: always show kg AND lb. `unit` is the NATIVE unit of v.
function _w(n) { const r = Math.round(n * 10) / 10; return Number.isInteger(r) ? String(r) : r.toFixed(1); }
export function dualWeight(v, unit = "kg") {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  // Always lb-first for a consistent read across the site (body comp / 1RM / workout
  // weights), regardless of whether the source value is stored in lb or kg.
  const lb = unit === "lb" ? n : n * 2.20462;
  const kg = unit === "kg" ? n : n * 0.453592;
  return `${_w(lb)} lb · ${_w(kg)} kg`;
}

const _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const _shortDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_MON[+m[2] - 1]} ${+m[3]}` : ""; };

function _points(data, valueKey, dateKey) {
  return data
    .map((d) => (typeof d === "number" ? { v: d } : { v: Number(d[valueKey]), d: d[dateKey] }))
    .filter((p) => Number.isFinite(p.v));
}

// A trend line with optional goal line + filled area. data: [{<dateKey>,<valueKey>}] or [numbers].
export function lineChart(data, { valueKey = "value", dateKey = "date", goal = null, height = 130, unit = "", label = "", emptyMsg = "", spine = false } = {}) {
  const pts = _points(data || [], valueKey, dateKey);
  // Fewer than 4 points can't show a real trend — two points draw a straight diagonal that
  // reads as broken/misleading. Show an honest count + latest value instead of a fake line.
  if (pts.length < 4) {
    const n = pts.length;
    const latest = n ? `Latest ${Math.round(pts[n - 1].v * 10) / 10}${unit}` : "";
    const msg = n < 1 ? (emptyMsg || "Fills as readings accrue.")
      : `${latest} · ${n} reading${n === 1 ? "" : "s"} so far — the trend line draws in at 4+.`;
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(msg)}</figcaption></figure>`;
  }
  const W = 600, H = height, P = 8;
  const vals = pts.map((p) => p.v).concat(goal != null ? [Number(goal)] : []);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const x = (i) => P + (i / (pts.length - 1)) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min)) * (H - 2 * P);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const area = `M${x(0).toFixed(1)} ${(H - P).toFixed(1)} ` + pts.map((p, i) => `L${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ") + ` L${x(pts.length - 1).toFixed(1)} ${(H - P).toFixed(1)} Z`;
  const last = pts[pts.length - 1];
  const delta = last.v - pts[0].v;
  const dir = Math.abs(delta) < (max - min) * 0.02 ? "holding flat" : (delta > 0 ? "trending up" : "trending down");
  const _r = (n) => (Math.round(n * 10) / 10);
  // Date range, when the points carry dates — gives the trend a time axis in the
  // caption so a reader can see WHICH days a line covers (the rightmost dot is the
  // latest reading). Silently omitted for dateless numeric series.
  const _short = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); if (!m) return ""; return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+m[2] - 1]} ${+m[3]}`; };
  const _span = (pts[0].d && last.d) ? `${_short(pts[0].d)}–${_short(last.d)}` : "";
  const summary = `${label || "Trend"}: ${pts.length} readings${_span ? `, ${_span}` : ""}, latest ${_r(last.v)}${unit}, ${dir}${goal != null ? `, goal ${_r(Number(goal))}${unit}` : ""}.`;
  const goalLine = goal != null ? `<line class="chart-goal" x1="${P}" y1="${y(Number(goal)).toFixed(1)}" x2="${W - P}" y2="${y(Number(goal)).toFixed(1)}" vector-effect="non-scaling-stroke"/>` : "";
  // SIGNATURE 1 — a measuring-rule tick spine on the y-axis: a ticked rail with the
  // max (top) and min (bottom) value, giving the trend a real scale. Token-driven ticks.
  const spineEl = spine
    ? `<div class="chart-spine" aria-hidden="true"><span class="chart-spine-v mono">${_r(max)}${escAttr(unit)}</span><span class="chart-spine-v mono">${_r(min)}${escAttr(unit)}</span></div>`
    : "";
  // Interactive hover data — normalized (0–1) coords + a label per point. motion.js reads
  // data-cpts and draws a focus dot + tooltip, making every lineChart explorable at once.
  const cpts = pts.map((p, i) => ({ x: +(x(i) / W).toFixed(4), y: +(y(p.v) / H).toFixed(4), l: (p.d ? _short(p.d) + " · " : "") + _r(p.v) + unit }));
  return `<figure class="chart${spine ? " chart--spined" : ""}">${spineEl}<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<path class="chart-fill" d="${area}"/>${goalLine}` +
    `<path class="chart-line" d="${line}" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label)}${goal != null ? ` · goal ${escAttr(goal)}${escAttr(unit)}` : ""}${_span ? ` · ${escAttr(_span)}` : ""} · ${pts.length} pts</figcaption></figure>`;
}

// #421 — arc-trend line for slow-moving, long-horizon metrics (VO2max, walking HR). Unlike
// lineChart (index-positioned — it silently closes gaps), the x here is positioned by REAL DATE,
// so an irregular / sparse cadence renders as honest horizontal GAPS ("gaps shown as gaps").
// Faint raw dots + an optional centered moving-average trend line (edge-clamped, no lag). Refuses
// <4 points → an honest empty caption. readings: [{date, value}]. One ember hue, never red.
export function arcTrend(readings, { valueKey = "value", dateKey = "date", unit = "", label = "", height = 150, decimals = 1, smooth = true } = {}) {
  const pts = (readings || [])
    .map((r) => ({ v: Number(r[valueKey]), d: String(r[dateKey] || "") }))
    .filter((p) => Number.isFinite(p.v) && /^\d{4}-\d{2}-\d{2}/.test(p.d))
    .sort((a, b) => a.d.localeCompare(b.d));
  const _r = (n) => { const q = Math.pow(10, decimals); return Math.round(n * q) / q; };
  if (pts.length < 4) {
    const n = pts.length, latest = n ? `Latest ${_r(pts[n - 1].v)}${unit}` : "";
    const msg = n < 1 ? `${label || "The trend"} draws in as readings accrue.`
      : `${latest} · ${n} reading${n === 1 ? "" : "s"} so far — the trend draws in at 4+.`;
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(msg)}</figcaption></figure>`;
  }
  const W = 600, H = height, P = 10;
  const t0 = Date.parse(pts[0].d), t1 = Date.parse(pts[pts.length - 1].d);
  const span = Math.max(1, t1 - t0);
  let min = Math.min(...pts.map((p) => p.v)), max = Math.max(...pts.map((p) => p.v));
  const pad = Math.max(0.5, (max - min) * 0.12); min -= pad; max += pad;
  const x = (iso) => P + ((Date.parse(iso) - t0) / span) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min)) * (H - 2 * P);
  // Centered moving average — symmetric window, edge-clamped (honest smoothing, no lag).
  const k = smooth ? Math.min(3, Math.floor((pts.length - 1) / 2)) : 0;
  const trend = pts.map((_, i) => {
    if (!k) return { v: pts[i].v, d: pts[i].d };
    let s = 0, c = 0;
    for (let j = Math.max(0, i - k); j <= Math.min(pts.length - 1, i + k); j++) { s += pts[j].v; c++; }
    return { v: s / c, d: pts[i].d };
  });
  const dots = pts.map((p) => `<circle class="wt-raw" cx="${x(p.d).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2.0"/>`).join("");
  const line = trend.map((p, i) => `${i ? "L" : "M"}${x(p.d).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  // A multi-year arc labels its dates WITH the year — "Apr 25–May 19" on a 2022→2026 span
  // reads as a 3-week window, which is exactly the dishonesty this chart exists to avoid.
  const multiYear = pts[0].d.slice(0, 4) !== last.d.slice(0, 4);
  const _sd = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    if (!m) return "";
    return `${_MON[+m[2] - 1]} ${+m[3]}${multiYear ? " ’" + m[1].slice(2) : ""}`;
  };
  const span_lbl = `${_sd(pts[0].d)}–${_sd(last.d)}`;
  const summary = `${label || "Trend"}: ${pts.length} readings ${span_lbl}, latest ${_r(last.v)}${unit} (range ${_r(Math.min(...pts.map((p) => p.v)))}–${_r(Math.max(...pts.map((p) => p.v)))}${unit}).`;
  const cpts = pts.map((p) => ({ x: +(x(p.d) / W).toFixed(4), y: +(y(p.v) / H).toFixed(4), v: p.v, l: `${_sd(p.d)} · ${_r(p.v)}${unit}` }));
  return `<figure class="chart wt-chart" data-wt-min="${min.toFixed(2)}" data-wt-max="${max.toFixed(2)}" data-wt-h="${H}" data-wt-p="${P}">` +
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<path class="wt-trend" d="${line}" fill="none" vector-effect="non-scaling-stroke"/>${dots}` +
    `<circle class="chart-dot" cx="${x(last.d).toFixed(1)}" cy="${y(trend[trend.length - 1].v).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label || "Trend")} · ${escAttr(span_lbl)} · ${pts.length} readings` +
    ` · <span class="wt-key"><i class="wt-swatch wt-swatch-raw"></i>faint dots = each reading</span>` +
    ` <span class="wt-key"><i class="wt-swatch wt-swatch-trend"></i>line = smoothed arc</span>` +
    ` · x positioned by real date, so gaps show as gaps</figcaption></figure>`;
}

// P0.1 — the trend-weight hero. Dual-layer: faint TRUE daily dots (scale noise) + a
// confident ember TREND line (centered moving average, down-weights water/food noise).
// HARD RULE 4: the goal NEVER anchors the y-axis (that flattens the real slope) — the axis
// comes from the weight data alone; the goal is a caption annotation only. Genesis is marked
// as a vertical rule. x is positioned by real DATE so an irregular weigh-in cadence and the
// genesis line both land truthfully. Refuses <4 points. readings: [{date, weight_lbs}].
export function weightTrendChart(readings, { goal = null, genesis = null, valueKey = "weight_lbs", height = 170, label = "" } = {}) {
  const pts = (readings || [])
    .map((r) => ({ v: Number(r[valueKey]), d: String(r.date || "") }))
    .filter((p) => Number.isFinite(p.v) && /^\d{4}-\d{2}-\d{2}/.test(p.d))
    .sort((a, b) => a.d.localeCompare(b.d));
  if (pts.length < 4) {
    const n = pts.length, latest = n ? `Latest ${_w(pts[n - 1].v)} lb` : "";
    const msg = n < 1 ? "The weight trend draws in as weigh-ins accrue."
      : `${latest} · ${n} weigh-in${n === 1 ? "" : "s"} so far — the trend line draws in at 4+.`;
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(msg)}</figcaption></figure>`;
  }
  const W = 600, H = height, P = 10;
  const t0 = Date.parse(pts[0].d), t1 = Date.parse(pts[pts.length - 1].d);
  const span = Math.max(1, t1 - t0);
  // y-domain from the RAW WEIGHTS ONLY — goal deliberately excluded (HARD RULE 4).
  let min = Math.min(...pts.map((p) => p.v)), max = Math.max(...pts.map((p) => p.v));
  const pad = Math.max(1, (max - min) * 0.12); min -= pad; max += pad;
  const x = (iso) => P + ((Date.parse(iso) - t0) / span) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min)) * (H - 2 * P);
  // Centered moving average — symmetric window, edge-clamped (no lag, honest smoothing).
  const k = Math.min(3, Math.floor((pts.length - 1) / 2));
  const trend = pts.map((_, i) => {
    let s = 0, c = 0;
    for (let j = Math.max(0, i - k); j <= Math.min(pts.length - 1, i + k); j++) { s += pts[j].v; c++; }
    return { v: s / c, d: pts[i].d };
  });
  const dots = pts.map((p) => `<circle class="wt-raw" cx="${x(p.d).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2.2"/>`).join("");
  const trendLine = trend.map((p, i) => `${i ? "L" : "M"}${x(p.d).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const last = trend[trend.length - 1], lastRaw = pts[pts.length - 1];
  const gMark = (genesis && Date.parse(genesis) >= t0 && Date.parse(genesis) <= t1)
    ? `<line class="wt-genesis" x1="${x(genesis).toFixed(1)}" y1="${P}" x2="${x(genesis).toFixed(1)}" y2="${(H - P).toFixed(1)}" vector-effect="non-scaling-stroke"/>`
    : "";
  const _r = (n) => Math.round(n * 10) / 10;
  const gap = goal != null ? _r(lastRaw.v - Number(goal)) : null;
  const summary = `Weight trend: ${pts.length} weigh-ins ${_shortDate(pts[0].d)}–${_shortDate(lastRaw.d)}, smoothed trend now ${_r(last.v)} lb${goal != null ? `, goal ${_r(Number(goal))} lb (${gap} lb away)` : ""}.`;
  // P0.2 — a horizontal scrub marker the silhouette drives in lockstep. Hidden until the
  // silhouette scrubber moves it; data-* expose the y-scale so the link math stays in JS.
  const markerY = y(lastRaw.v).toFixed(1);
  // Interactive hover/tap: cpts from the RAW weigh-ins (the dots — what a reader
  // asks "what was that day?" about). x is date-positioned, so motion.js's
  // nearest-by-x hit-testing is what makes this land on the right weigh-in.
  const cpts = pts.map((p) => ({ x: +(x(p.d) / W).toFixed(4), y: +(y(p.v) / H).toFixed(4), v: p.v, l: `${_shortDate(p.d)} · ${_r(p.v)} lb` }));
  return `<figure class="chart wt-chart" data-wt-min="${min.toFixed(2)}" data-wt-max="${max.toFixed(2)}" data-wt-h="${H}" data-wt-p="${P}">` +
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    gMark +
    `<path class="wt-trend" d="${trendLine}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `${dots}` +
    `<line class="wt-marker" data-wt-marker x1="${P}" x2="${W - P}" y1="${markerY}" y2="${markerY}" vector-effect="non-scaling-stroke" style="opacity:0"/>` +
    `<circle class="chart-dot" cx="${x(lastRaw.d).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label || "Weight")}` +
    ` · <span class="wt-key"><i class="wt-swatch wt-swatch-raw"></i>faint dots = daily scale (water/food noise)</span>` +
    ` <span class="wt-key"><i class="wt-swatch wt-swatch-trend"></i>line = smoothed trend</span>` +
    `${genesis ? " · genesis marked" : ""}${goal != null ? ` · goal ${_r(Number(goal))} lb, ${gap} lb away (annotation, not the axis floor)` : ""}</figcaption></figure>`;
}

// P0.6 / #551 — projection FAN. A WIDENING confidence band from the current weigh-in toward
// goal, whose edges are the REAL block-bootstrap CI on the loss slope (weekly_rate_ci_low =
// faster-loss bound, weekly_rate_ci_high = slower). This is the honesty upgrade over the old
// heuristic 0.72/0.5 multipliers: the band width IS a computed interval, never an invented
// spread. The dated "bet" is the backend's OWN goal-date RANGE (projected_goal_date_earliest/
// latest), so the drawn edges and the stated dates land on the same math. When the slow CI
// bound is ≥ 0 the interval is open-ended (goal may not be reached at this trajectory) — the
// slow edge holds flat, honestly. HONEST FALLBACK: no CI (or provisional) ⇒ the mid trajectory
// line ONLY, no band — a point read, never a fabricated cone.
// current: {date, w}. ratePerWeek: negative (lb/wk). rungs: [weights] to date-mark.
// rateCiLow/rateCiHigh: weekly lb/wk CI bounds (REAL). goalDateRange: {earliest, latest} ISO
// (REAL, from the backend). confidence: the CI level, e.g. 0.8.
export function projectionCone(current, goal, ratePerWeek, {
  provisional = false, height = 210, rungs = [], label = "",
  rateCiLow = null, rateCiHigh = null, goalDateRange = null, confidence = null,
} = {}) {
  const cur = Number(current && current.w), g = Number(goal), rWk = Number(ratePerWeek);
  const t0 = current && current.date ? Date.parse(current.date) : NaN;
  if (!Number.isFinite(cur) || !Number.isFinite(g) || !Number.isFinite(rWk) || !Number.isFinite(t0) || rWk >= 0 || cur <= g) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The projection cone draws once there's a sustained downward rate to extend — right now the loss is too new (and too watery) to forecast.</figcaption></figure>`;
  }
  const rDayMid = Math.abs(rWk) / 7;
  // REAL confidence band: edges from the slope CI (ciLow = faster loss, ciHigh = slower).
  const ciLoWk = Number(rateCiLow), ciHiWk = Number(rateCiHigh);
  const hasCI = !provisional && Number.isFinite(ciLoWk) && Number.isFinite(ciHiWk) && Math.min(ciLoWk, ciHiWk) < 0;
  const rDayFast = hasCI ? Math.abs(Math.min(ciLoWk, ciHiWk)) / 7 : rDayMid;   // faster-loss edge
  const slowWk = hasCI ? Math.max(ciLoWk, ciHiWk) : rWk;                        // slower edge (may be ≥ 0)
  const slowOpen = hasCI && slowWk >= 0;                                        // open-ended: goal not guaranteed
  const rDaySlow = slowOpen ? 0 : (hasCI ? Math.abs(slowWk) / 7 : rDayMid);
  // Keep the mid trajectory inside its own band (the recomputed point slope can drift from
  // the slope the CI was measured on).
  const rDayMidC = hasCI ? Math.max(rDaySlow, Math.min(rDayFast, rDayMid)) : rDayMid;
  const reach = (r) => (r > 0 ? (cur - g) / r : Infinity);
  const horizon = Math.min(900, slowOpen ? reach(rDayMidC) * 1.6 : reach(rDaySlow || rDayMidC));
  const W = 600, H = height, P = 10;
  const x = (t) => P + (t / horizon) * (W - 2 * P);
  const ymin = g - 3, ymax = cur + 3;
  const y = (w) => P + (1 - (w - ymin) / (ymax - ymin)) * (H - 2 * P);
  const wAt = (r, t) => Math.max(g, cur - r * t);
  const curvePts = (r) => { const a = []; const step = horizon / 64; for (let t = 0; t <= horizon + 1e-6; t += step) a.push([t, wAt(r, t)]); return a; };
  const toPath = (a) => a.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
  const mid = curvePts(rDayMidC);
  // The fan (real band only). Slow edge holds flat at cur when the CI is open-ended.
  const conf = confLevel({ provisional: !hasCI, confidence, ciWidthFrac: hasCI && rDayMidC > 0 ? (rDayFast - rDaySlow) / rDayMidC : (slowOpen ? 2 : null) });
  let coneEl = "";
  if (hasCI) {
    const fast = curvePts(rDayFast);
    const slow = slowOpen ? [[0, cur], [horizon, cur]] : curvePts(rDaySlow);
    const cone = `${toPath(slow)} ${fast.slice().reverse().map((p) => `L${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ")} Z`;
    coneEl = `<path class="pc-cone ${conf.cls}" d="${cone}"/>`;
  }
  const goalLine = `<line class="pc-goal" x1="${P}" y1="${y(g).toFixed(1)}" x2="${W - P}" y2="${y(g).toFixed(1)}" vector-effect="non-scaling-stroke"/>`;
  // Rung date-markers from the MID path (only rungs strictly between goal and current).
  const marks = (rungs || []).filter((r) => r > g + 0.5 && r < cur - 0.5).map((r) => {
    const t = (cur - r) / rDayMidC;
    return `<line class="pc-rung" x1="${x(t).toFixed(1)}" y1="${y(r).toFixed(1)}" x2="${x(t).toFixed(1)}" y2="${(H - P).toFixed(1)}" vector-effect="non-scaling-stroke"/>`;
  }).join("");
  const _d = (ms) => { const d = new Date(ms); return `${_MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const _dISO = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_MON[+m[2] - 1]} ${m[1]}` : ""; };
  // The dated bet — the backend's OWN goal-date range when present (the same interval the
  // fan is drawn from). No CI ⇒ the point date, honestly caveated.
  const gr = goalDateRange || {};
  const dEarly = _dISO(gr.earliest), dLate = _dISO(gr.latest);
  const betMidMs = t0 + reach(rDayMidC) * 86400000;
  let bet;
  if (hasCI && dEarly) {
    bet = (slowOpen || !dLate)
      ? `The honest read: ${_r1(rWk)} lb/wk now puts ${g} around <strong>${escAttr(dEarly)}</strong> at the earliest — but the slow end of the interval can't rule out holding flat, so no late date is claimed yet. The band's the honest part; it tightens as weigh-ins accrue.`
      : `The honest read: hold ${_r1(rWk)} lb/wk and ${g} lands about <strong>${escAttr(dEarly)}–${escAttr(dLate)}</strong> — that range is the ${confidence != null ? Math.round(Number(confidence) * 100) + "% " : ""}CI on the trend, not a single promised day. The band tightens as weigh-ins accrue.`;
  } else {
    bet = `Current trajectory points at ${g} around <strong>~${escAttr(_d(betMidMs))}</strong> — shown as a single line, not a band: the rate's still too young for an honest interval.${provisional ? " Early loss is mostly water; this will slow." : ""} The confidence band draws in once the slope stabilises.`;
  }
  const summary = (hasCI && dEarly)
    ? `Projection fan from ${Math.round(cur)} lb toward ${g} lb: ${(dLate && !slowOpen) ? `${dEarly}–${dLate} (the CI on the trend)` : `${dEarly} at the earliest, open-ended at the slow bound`}.`
    : `Projection line from ${Math.round(cur)} lb toward ${g} lb at ~${_r1(rWk)} lb/wk — no band drawn (rate too young for an interval).`;
  // Interactive scrub: cpts along the MID path — hover/tap to read "when ≈ what weight".
  const cpts = mid.filter((_, i) => i % 2 === 0).map(([t, w]) => ({
    x: +(x(t) / W).toFixed(4), y: +(y(w) / H).toFixed(4), v: +w.toFixed(1),
    l: `~${_d(t0 + t * 86400000)} · ${Math.round(w)} lb (mid path)`,
  }));
  return `<figure class="chart pc-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `${coneEl}${marks}${goalLine}` +
    `<path class="pc-mid" d="${toPath(mid)}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(0).toFixed(1)}" cy="${y(cur).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label || "Projected weight → goal")} · ${hasCI ? "the band is the real slope CI" : "point trajectory (no band yet)"}; the goal line is ${g} lb` +
    `<span class="pc-bet">${bet} Graded against each new weigh-in as it resolves.</span>` +
    `</figcaption></figure>`;
}
const _r1 = (n) => { const r = Math.round(Number(n) * 10) / 10; return Number.isInteger(r) ? String(r) : r.toFixed(1); };

/* ── Uncertainty-first visual language (#551) ────────────────────────────────
   The site's rigor backend produces real intervals (block-bootstrap CIs), real
   sample sizes (overlapping-day n), and graded forecasts — ADR-105. These three
   helpers are where that lives visually, honestly: the band width IS a computed
   interval, the dots ARE the real n. Nothing invents a spread to look sophisticated.

   THE CONFIDENCE GRAMMAR — one consistent read across every chart:
     • HIGH   → a defined, tight band (or a solid-filled n-dot row): trust it.
     • MEDIUM → a wider, dashed-edge band (or a muted dot row): directional.
     • LOW    → NO band at all — the point is drawn honestly, never a fake spread.
   ONE hue (ember), never red; opacity + edge treatment carry the message. */
export function confLevel({ confidence = null, n = null, provisional = false, ciWidthFrac = null } = {}) {
  if (provisional) return { level: "low", cls: "cf-low" };
  // Relative CI width dominates when supplied — a wider band is a less-certain claim.
  if (Number.isFinite(ciWidthFrac)) {
    if (ciWidthFrac <= 0.5) return { level: "high", cls: "cf-high" };
    if (ciWidthFrac <= 1.2) return { level: "medium", cls: "cf-med" };
    return { level: "low", cls: "cf-low" };
  }
  if (Number.isFinite(n)) {
    if (n >= 21) return { level: "high", cls: "cf-high" };   // ≥3 weeks of overlap
    if (n >= 8) return { level: "medium", cls: "cf-med" };   // enough to be directional
    return { level: "low", cls: "cf-low" };
  }
  // Guard null explicitly — Number(null) is 0 (finite!), which read "no confidence
  // supplied" as cf-low and rendered a caller's ciWhisker band invisible (#421 QA).
  const c = Number(confidence);
  if (confidence != null && Number.isFinite(c)) {
    if (c >= 0.8) return { level: "high", cls: "cf-high" };
    if (c >= 0.5) return { level: "medium", cls: "cf-med" };
    return { level: "low", cls: "cf-low" };
  }
  return { level: "medium", cls: "cf-med" };
}

// Sample-size dots (#551) — n rendered as a row of dots so a reader SEES the evidence
// weight behind a correlation, not just a number. REAL n only, never padded: filled dots
// up to `cap` (then "+extra"), the confidence grammar tinting the row (few dots read faint,
// many read solid ember). Inline HTML, safe in a table cell or a card meta line.
export function nDots(n, { cap = 12, unit = "overlapping days" } = {}) {
  const k = Math.max(0, Math.round(Number(n) || 0));
  if (!k) return `<span class="ndots ndots--none mono" title="no ${escAttr(unit)} yet">n=0</span>`;
  const { cls } = confLevel({ n: k });
  const shown = Math.min(k, cap);
  const dots = Array.from({ length: shown }, () => `<i class="ndot"></i>`).join("");
  const more = k > cap ? `<span class="ndots-more mono">+${k - cap}</span>` : "";
  return `<span class="ndots ${cls}" role="img" aria-label="sample size n equals ${k} ${escAttr(unit)}" title="n = ${k} ${escAttr(unit)}">${dots}${more}<span class="ndots-n mono">n=${k}</span></span>`;
}

// CI band / whisker (#551) — a point estimate with its confidence interval drawn as a
// horizontal band + center marker on a small auto-scaled rail. The band IS the honest part:
// a REAL interval, never a decorative spread. A faint zero reference makes "the interval
// crosses zero" (i.e. the direction isn't established) legible at a glance. Confidence
// grammar tints the band. HONEST FALLBACK: no finite lo/hi ⇒ the point marker alone,
// captioned "no interval yet" — never an invented band. value/lo/hi share one unit.
export function ciWhisker(value, lo, hi, { unit = "", label = "", confidence = null, zeroRef = true, caption = "" } = {}) {
  const v = Number(value);
  if (!Number.isFinite(v)) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(caption || "Fills in once the estimate lands.")}</figcaption></figure>`;
  const loN0 = Number(lo), hiN0 = Number(hi);
  const hasCI = Number.isFinite(loN0) && Number.isFinite(hiN0) && loN0 !== hiN0;
  const _r = (n) => Math.round(n * 100) / 100;
  const loN = hasCI ? Math.min(loN0, hiN0) : v, hiN = hasCI ? Math.max(loN0, hiN0) : v;
  let dmin = Math.min(loN, v, zeroRef ? 0 : loN), dmax = Math.max(hiN, v, zeroRef ? 0 : hiN);
  const padd = Math.max(1e-6, (dmax - dmin) * 0.14); dmin -= padd; dmax += padd;
  const pos = (t) => Math.max(0, Math.min(100, ((t - dmin) / (dmax - dmin)) * 100));
  const crosses = hasCI && loN < 0 && hiN > 0;
  const conf = confLevel({ confidence, provisional: !hasCI });
  const cLbl = confidence != null ? `${Math.round(Number(confidence) * 100)}% ` : "";
  const zeroEl = (zeroRef && dmin < 0 && dmax > 0) ? `<span class="ciw-zero" style="left:${pos(0).toFixed(1)}%"></span>` : "";
  const bandEl = hasCI ? `<span class="ciw-band ${conf.cls}" style="left:${pos(loN).toFixed(1)}%;width:${(pos(hiN) - pos(loN)).toFixed(1)}%"></span>` : "";
  const aria = hasCI
    ? `${label || "estimate"} ${_r(v)}${unit}, ${cLbl}CI ${_r(loN)} to ${_r(hiN)}${unit}${crosses ? " — the interval crosses zero, so the direction isn't established" : ""}.`
    : `${label || "estimate"} ${_r(v)}${unit} — no interval yet.`;
  const cpts = hasCI
    ? [{ x: +(pos(loN) / 100).toFixed(4), y: 0.5, l: `low ${_r(loN)}${unit}` },
       { x: +(pos(v) / 100).toFixed(4), y: 0.5, l: `estimate ${_r(v)}${unit}` },
       { x: +(pos(hiN) / 100).toFixed(4), y: 0.5, l: `high ${_r(hiN)}${unit}` }]
    : [{ x: +(pos(v) / 100).toFixed(4), y: 0.5, l: `estimate ${_r(v)}${unit}` }];
  const cap = caption || (hasCI
    ? `Point estimate with its ${cLbl}interval (the band).${crosses ? " The band crosses zero — the direction isn't nailed down yet." : ""}`
    : "No interval yet — the point alone, honestly (an interval needs more data).");
  return `<figure class="chart ciw-fig"><div class="ciw-wrap" role="img" aria-label="${escAttr(aria)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<div class="ciw-rule"></div>${zeroEl}${bandEl}` +
    `<span class="ciw-dot ${conf.cls}" style="left:${pos(v).toFixed(1)}%"></span>` +
    `</div><figcaption class="chart-cap label">${label ? escAttr(label) + " · " : ""}${escAttr(cap)}</figcaption></figure>`;
}

// Two overlaid trajectories on a shared scale — ember = primary (A), muted = reference (B).
// For the reconciliation view (projected loss vs actual). Refuses if either series < 4 pts.
// No correlation/Pearson — that's gated elsewhere by the ≥2-week rule. seriesA/B: [{date,value}].
export function dualLineChart(seriesA, seriesB, { aLabel = "A", bLabel = "B", unit = "", height = 140, label = "", emptyMsg = "", showGap = true } = {}) {
  const A = _points(seriesA || [], "value", "date"), B = _points(seriesB || [], "value", "date");
  if (A.length < 4 || B.length < 4) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(emptyMsg || "Two trajectories draw in once each has 4+ points.")}</figcaption></figure>`;
  }
  const W = 600, H = height, P = 8;
  const all = A.concat(B).map((p) => p.v);
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const xf = (arr) => (i) => P + (i / (arr.length - 1)) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min)) * (H - 2 * P);
  const path = (arr) => { const x = xf(arr); return arr.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" "); };
  const _r = (n) => Math.round(n * 10) / 10;
  const aLast = A[A.length - 1].v, bLast = B[B.length - 1].v, gap = _r(aLast - bLast);
  const summary = `${aLabel} ${_r(aLast)}${unit} vs ${bLabel} ${_r(bLast)}${unit}, gap ${gap}${unit}.`;
  // Interactive hover/tap: cpts track series A (the ember primary); when B has a
  // point on the same date, the tooltip carries both so the gap is readable.
  const xA = xf(A);
  const bByD = new Map(B.filter((p) => p.d).map((p) => [p.d, p.v]));
  const cpts = A.map((p, i) => ({
    x: +(xA(i) / W).toFixed(4), y: +(y(p.v) / H).toFixed(4),
    l: (p.d ? _shortDate(p.d) + " · " : "") + `${aLabel} ${_r(p.v)}${unit}` + (p.d && bByD.has(p.d) ? ` · ${bLabel} ${_r(bByD.get(p.d))}${unit}` : ""),
  }));
  return `<figure class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<path class="chart-down" d="${path(B)}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `<path class="chart-line" d="${path(A)}" vector-effect="non-scaling-stroke"/></svg>` +
    `<figcaption class="chart-cap label sbar-legend"><span class="sbar-key"><i class="sbar-dot sbar-ember"></i>${escAttr(aLabel)}</span><span class="sbar-key"><i class="sbar-dot sbar-ink"></i>${escAttr(bLabel)}</span>${showGap ? ` · gap ${escAttr(String(gap))}${escAttr(unit)}` : ""}${label ? ` · ${escAttr(label)}` : ""}</figcaption></figure>`;
}

// Tiny inline sparkline (no axes/caption). values: [numbers].
// Vitals component ring (P0.1) — a 0→1 arc with a centred value + label. tone ∈ {ember,
// muted, alert}: ember = good/recovered, muted = neutral/forming, alert = reserved RED STATE
// (run-down / out-of-range) — never used to encode a falling direction. The ring IS a
// component (recovery / HRV / RHR / sleep) so the glance is decomposed, not a black-box grade.
export function ring({ value = "", sub = "", label = "", fill = 0, tone = "ember", thin = false } = {}) {
  const r = 42, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, Number(fill) || 0));
  const dash = `${(f * c).toFixed(1)} ${(c - f * c).toFixed(1)}`;
  const aria = `${label}: ${value}${sub ? " " + sub : ""}`;
  // Interactive readout (#583): a single focus point on the arc so the ring answers to
  // hover/tap/keyboard like every other chart — the arc midpoint, label = the value.
  const mid = (-Math.PI / 2) + f * 2 * Math.PI;
  const cpts = [{ x: +((50 + r * Math.cos(mid)) / 100).toFixed(4), y: +((50 + r * Math.sin(mid)) / 100).toFixed(4), l: aria }];
  return `<div class="vr vr-${escAttr(tone)}${thin ? " vr-thin" : ""}">` +
    `<svg class="vr-svg" viewBox="0 0 100 100" role="img" aria-label="${escAttr(aria)}" data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-hit="xy">` +
    `<circle class="vr-track" cx="50" cy="50" r="${r}" fill="none"/>` +
    `<circle class="vr-arc" cx="50" cy="50" r="${r}" fill="none" stroke-dasharray="${dash}" transform="rotate(-90 50 50)" stroke-linecap="round"/>` +
    `</svg>` +
    `<div class="vr-c"><span class="vr-v num">${escAttr(value)}</span>${sub ? `<span class="vr-sub label">${escAttr(sub)}</span>` : ""}</div>` +
    `<span class="vr-l label">${escAttr(label)}</span></div>`;
}

// P1.2 — autonomic-recovery hero: RHR + HRV on ONE shared time frame. Each is normalised to
// its own range; RHR is INVERTED (low RHR plots high) so that BOTH lines rising = the body
// downshifting into recovery — direction reads ember-positive even though RHR falls. Never red.
// Tick-spine signature. Refuses <4 points. hist items: {date, rhr_bpm, hrv_ms}.
export function autonomicHero(hist, { height = 190, label = "" } = {}) {
  const rhr = (hist || []).map((h) => ({ d: String(h.date || ""), v: Number(h.rhr_bpm) })).filter((p) => Number.isFinite(p.v) && /^\d{4}-\d{2}-\d{2}/.test(p.d)).sort((a, b) => a.d.localeCompare(b.d));
  const hrv = (hist || []).map((h) => ({ d: String(h.date || ""), v: Number(h.hrv_ms) })).filter((p) => Number.isFinite(p.v) && /^\d{4}-\d{2}-\d{2}/.test(p.d)).sort((a, b) => a.d.localeCompare(b.d));
  if (rhr.length < 4 || hrv.length < 4) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The autonomic hero draws once there are 4+ nights of resting-HR and HRV.</figcaption></figure>`;
  }
  const W = 600, H = height, P = 12;
  const allD = [...rhr, ...hrv].map((p) => Date.parse(p.d));
  const t0 = Math.min(...allD), t1 = Math.max(...allD), span = Math.max(1, t1 - t0);
  const x = (d) => P + ((Date.parse(d) - t0) / span) * (W - 2 * P);
  const norm = (arr, invert) => { const vs = arr.map((p) => p.v); const lo = Math.min(...vs), hi = Math.max(...vs); return arr.map((p) => ({ d: p.d, n: hi === lo ? 0.5 : (invert ? 1 - (p.v - lo) / (hi - lo) : (p.v - lo) / (hi - lo)) })); };
  const y = (n) => P + (1 - n) * (H - 2 * P);
  const path = (arr) => arr.map((p, i) => `${i ? "L" : "M"}${x(p.d).toFixed(1)} ${y(p.n).toFixed(1)}`).join(" ");
  const rhrN = norm(rhr, true), hrvN = norm(hrv, false);
  const _r = (n) => Math.round(n * 10) / 10;
  const rhrDir = rhr[rhr.length - 1].v <= rhr[0].v ? "down" : "up";
  const hrvDir = hrv[hrv.length - 1].v >= hrv[0].v ? "up" : "down";
  const summary = `Autonomic hero: resting HR ${rhrDir} (${_r(rhr[0].v)}→${_r(rhr[rhr.length - 1].v)} bpm), HRV ${hrvDir} (${_r(hrv[0].v)}→${_r(hrv[hrv.length - 1].v)} ms). Both toward recovery read ember-positive.`;
  // Interactive hover/tap: cpts on the HRV line (ember primary) with the REAL
  // values — the plot is normalized, so the tooltip is where the truth lives.
  // Same-night RHR joins the label when present. Date-positioned x → nearest-by-x.
  const rhrByD = new Map(rhr.map((p) => [p.d, p.v]));
  const cpts = hrvN.map((p, i) => ({
    x: +(x(p.d) / W).toFixed(4), y: +(y(p.n) / H).toFixed(4),
    l: `${_shortDate(p.d)} · HRV ${_r(hrv[i].v)} ms` + (rhrByD.has(p.d) ? ` · RHR ${_r(rhrByD.get(p.d))} bpm` : ""),
  }));
  return `<figure class="chart ah-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<path class="ah-hrv" d="${path(hrvN)}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `<path class="ah-rhr" d="${path(rhrN)}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(hrvN[hrvN.length - 1].d).toFixed(1)}" cy="${y(hrvN[hrvN.length - 1].n).toFixed(1)}" r="3.2"/>` +
    `<circle class="chart-dot" cx="${x(rhrN[rhrN.length - 1].d).toFixed(1)}" cy="${y(rhrN[rhrN.length - 1].n).toFixed(1)}" r="3.2"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label || "Autonomic recovery")} · <span class="ah-key"><i class="ah-sw ah-sw-hrv"></i>HRV ${escAttr(hrvDir)} (${_r(hrv[hrv.length - 1].v)} ms)</span> <span class="ah-key"><i class="ah-sw ah-sw-rhr"></i>resting HR ${escAttr(rhrDir)} (${_r(rhr[rhr.length - 1].v)} bpm, axis inverted)</span> · both lines rising = the body downshifting into recovery — early moves are partly water & novelty.</figcaption></figure>`;
}

// P2.1 — autonomic-balance 2×2: recovery (y) vs day strain (x), last 7-8 days as dots. Four
// states — FLOW (recovered + working), RECOVERY (recovered + easy), STRESS (depleted + working),
// LOW (depleted + easy). Today's dot is ember; the rest muted ink. A SNAPSHOT — no trajectory
// arrows at n≈8. No red (a low day isn't an alarm). points: [{strain, recovery, date, today}].
export function autonomicQuadrant(points, { size = 300 } = {}) {
  const pts = (points || []).filter((p) => Number.isFinite(p.strain) && Number.isFinite(p.recovery));
  if (pts.length < 3) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The autonomic 2×2 fills once there are a few days of strain + recovery.</figcaption></figure>`;
  }
  const W = 320, H = 320, P = 26, xmax = 21, ymax = 100;
  const x = (s) => P + (Math.max(0, Math.min(xmax, s)) / xmax) * (W - 2 * P);
  const y = (r) => P + (1 - Math.max(0, Math.min(ymax, r)) / ymax) * (H - 2 * P);
  const xMid = x(10), yMid = y(50);
  const labels = [
    { t: "FLOW", x: (xMid + (W - P)) / 2, y: P + 12 },
    { t: "RECOVERY", x: (P + xMid) / 2, y: P + 12 },
    { t: "STRESS", x: (xMid + (W - P)) / 2, y: H - P - 6 },
    { t: "LOW", x: (P + xMid) / 2, y: H - P - 6 },
  ].map((l) => `<text class="aq-lab" x="${l.x.toFixed(0)}" y="${l.y.toFixed(0)}" text-anchor="middle">${l.t}</text>`).join("");
  const dotLabel = (p) => (p.today ? "today · " : (p.date ? p.date + " · " : "")) + "recovery " + Math.round(p.recovery) + "% · strain " + (Math.round(p.strain * 10) / 10);
  const dots = pts.map((p) => `<circle class="aq-dot${p.today ? " aq-today" : ""}" cx="${x(p.strain).toFixed(1)}" cy="${y(p.recovery).toFixed(1)}" r="${p.today ? 5 : 3.5}"></circle>`).join("");
  // Interactive readout (#583): a 2×2 scatter → 2-D nearest (data-cpts-hit="xy"); the
  // shared tooltip replaces the native <title> so it matches every other chart.
  const cpts = pts.map((p) => ({ x: +(x(p.strain) / W).toFixed(4), y: +(y(p.recovery) / H).toFixed(4), l: dotLabel(p) }));
  return `<figure class="chart aq-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Autonomic 2x2: recovery vs strain, last ${pts.length} days, today highlighted." data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-hit="xy">` +
    `<line class="aq-div" x1="${xMid.toFixed(0)}" y1="${P}" x2="${xMid.toFixed(0)}" y2="${H - P}"/>` +
    `<line class="aq-div" x1="${P}" y1="${yMid.toFixed(0)}" x2="${W - P}" y2="${yMid.toFixed(0)}"/>` +
    labels + dots +
    `<text class="aq-ax" x="${W / 2}" y="${H - 4}" text-anchor="middle">day strain →</text>` +
    `<text class="aq-ax" x="8" y="${H / 2}" text-anchor="middle" transform="rotate(-90 8 ${H / 2})">recovery →</text>` +
    `</svg><figcaption class="chart-cap label">Each dot a day; today is ember. A snapshot of where the body's sat lately — no trend arrow drawn at this n. Recovered + working = flow; depleted + working = stress; a low day is just low, not an alarm.</figcaption></figure>`;
}

export function sparkline(values, { height = 34 } = {}) {
  const pts = _points(values || [], "v", "d");
  if (pts.length < 2) return `<span class="spark spark--empty"></span>`;
  const W = 120, H = height, P = 2;
  let min = Math.min(...pts.map((p) => p.v)), max = Math.max(...pts.map((p) => p.v));
  if (min === max) { min -= 1; max += 1; }
  const x = (i) => P + (i / (pts.length - 1)) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min)) * (H - 2 * P);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  // Interactive hover/tap (#582): decorative aria-hidden, but a touch still surfaces
  // the value. motion.js reads data-cpts (normalized coords + label per point).
  const cpts = pts.map((p, i) => ({ x: +(x(i) / W).toFixed(4), y: +(y(p.v) / H).toFixed(4), l: (p.d ? _shortDate(p.d) + " · " : "") + (Math.round(p.v * 10) / 10) }));
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" data-cpts="${escAttr(JSON.stringify(cpts))}"><path class="chart-line" d="${line}" vector-effect="non-scaling-stroke"/></svg>`;
}

// Horizontal 100%-stacked bar — for a composition (e.g. macro split P/C/F). segments:
// [{label, value, tone}] where tone ∈ {ember, ink, faint} (no new hues — ember = the
// tracked/primary segment, muted inks for the rest). Renders the % split + a legend.
export function stackedBar(segments, { label = "", unit = "g" } = {}) {
  const segs = (segments || []).map((s) => ({ l: s.label, v: Number(s.value) || 0, t: s.tone || "ink" })).filter((s) => s.v > 0);
  const total = segs.reduce((a, s) => a + s.v, 0);
  if (!total) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">No data yet.</figcaption></figure>`;
  const bar = segs.map((s) => `<span class="sbar-seg sbar-${escAttr(s.t)}" style="width:${((s.v / total) * 100).toFixed(1)}%"></span>`).join("");
  const legend = segs.map((s) => `<span class="sbar-key"><i class="sbar-dot sbar-${escAttr(s.t)}"></i>${escAttr(s.l)} ${Math.round(s.v)}${escAttr(unit)} · ${Math.round((s.v / total) * 100)}%</span>`).join("");
  // Interactive hover/tap (#582): a point at each segment's centre — nearest-by-x
  // lands on the segment under the finger. Replaces the native title tooltip.
  let _acc = 0;
  const cpts = segs.map((s) => { const cx = _acc + s.v / 2; _acc += s.v; return { x: +(cx / total).toFixed(4), y: 0.5, l: `${s.l} ${Math.round(s.v)}${unit} · ${Math.round((s.v / total) * 100)}%` }; });
  return `<figure class="chart"><div class="sbar" role="img" aria-label="${escAttr(label)}" data-cpts="${escAttr(JSON.stringify(cpts))}">${bar}</div><figcaption class="chart-cap label sbar-legend">${legend}</figcaption></figure>`;
}

// Horizontal sufficiency bars 0→100% (intake vs target). Sorted ascending — worst
// first — each labelled with its %, the track's right edge IS the 100% target rule.
// Ember is reserved for the worst offenders that are short of the floor (a deficiency is
// the thing to LOOK at) — never a "win" colour for an adequate bar (HARD RULE 3); full /
// adequate bars are muted ink. The value sits in its own grid column so nothing clips the
// right edge. items: [{label, pct, actual, target, unit}].
export function sufficiencyBars(items, { label = "", emberWorst = 2, warnBelow = 70, caveat = "" } = {}) {
  const rows = (items || []).map((it) => ({
    l: it.label,
    pct: Math.max(0, Math.min(100, Number(it.pct))),
    actual: it.actual, target: it.target, unit: it.unit || "",
  })).filter((r) => Number.isFinite(r.pct));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Micronutrient sufficiency fills in from logged food.</figcaption></figure>`;
  rows.sort((a, b) => a.pct - b.pct);
  const ember = new Set();
  for (const r of rows) { if (ember.size >= emberWorst) break; if (r.pct < warnBelow) ember.add(r); }
  const row = (r) => {
    const tone = ember.has(r) ? "suf-ember" : "suf-ink";
    const amt = (r.actual != null && r.target != null) ? `<span class="suf-amt">${escAttr(_w(r.actual))}/${escAttr(_w(r.target))}${escAttr(r.unit)}</span>` : "";
    const aria = `${r.l}: ${Math.round(r.pct)} percent of target${ember.has(r) ? " — short of the floor" : ""}`;
    return `<div class="suf-row" role="img" aria-label="${escAttr(aria)}"><span class="suf-l">${escAttr(r.l)}</span>` +
      `<span class="suf-track"><span class="suf-fill ${tone}" style="width:${r.pct.toFixed(1)}%"></span></span>` +
      `<span class="suf-v mono">${Math.round(r.pct)}%${amt}</span></div>`;
  };
  const cap = caveat || "100% = daily target · worst first · intake vs target from logged food, not blood levels.";
  // Interactive hover/tap (#582): rows stack vertically, so hit-test by y (axis="y").
  // Dot centres in the focused row; the tooltip carries its exact %/amount.
  const n = rows.length;
  const cpts = rows.map((r, i) => ({ x: 0.5, y: +((i + 0.5) / n).toFixed(4), l: `${r.l}: ${Math.round(r.pct)}% of target${(r.actual != null && r.target != null) ? ` (${_w(r.actual)}/${_w(r.target)}${r.unit})` : ""}` }));
  return `<figure class="chart suf">${label ? `<p class="suf-head label">${escAttr(label)}</p>` : ""}` +
    `<div class="suf-rows" role="img" aria-label="${escAttr(label || "sufficiency bars")}" data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-axis="y">${rows.map(row).join("")}</div>` +
    `<figcaption class="chart-cap label">${escAttr(cap)}</figcaption></figure>`;
}

// Measuring-rule energy spine (SIGNATURE 1) — a horizontal 0→maintenance rule with
// the intake tick and the maintenance tick, the gap between them shaded = the deficit.
// The page's central claim drawn once. Ember marks intake ("on protocol"); muted ink is
// the maintenance reference. Never red. Honest empty when either figure is missing.
export function intakeSpine(intake, tdee, { label = "" } = {}) {
  const inK = Number(intake), td = Number(tdee);
  if (!Number.isFinite(inK) || !Number.isFinite(td) || td <= 0) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The energy spine fills in once both intake and an expenditure estimate are logged.</figcaption></figure>`;
  }
  const max = Math.max(td, inK) * 1.04;
  const pos = (v) => Math.max(0, Math.min(100, (v / max) * 100));
  const deficit = Math.round(td - inK);
  const lo = Math.min(inK, td), hi = Math.max(inK, td);
  const gapCls = inK <= td ? "hspine-gap-deficit" : "hspine-gap-surplus";
  const aria = `Average intake ${Math.round(inK)} kcal against an estimated maintenance of ${Math.round(td)} kcal — a ${Math.abs(deficit)} kcal ${deficit >= 0 ? "deficit" : "surplus"} a day.`;
  // Edge-aware marks: the tick stays at the true position; the LABEL anchors inward near
  // the edges (right-aligned at the high end, left-aligned at the low end) so a value at
  // the far-right tick never clips off the viewport at 390px.
  const mark = (val, key, emberMark) => {
    const p = pos(val);
    const align = p >= 80 ? "hspine-r" : (p <= 15 ? "hspine-l" : "hspine-c");
    return `<div class="hspine-mark ${align} ${emberMark ? "hspine-intake" : "hspine-tdee"}" style="left:${p.toFixed(1)}%">` +
      `<span class="hspine-lab"><span class="hspine-v mono">${Math.round(val)}</span><span class="hspine-k label">${key}</span></span></div>`;
  };
  // Interactive hover/tap (#582): a point at each tick — nearest-by-x reads intake
  // vs maintenance under the finger. y sits on the rule (top:34px of a 58px box).
  const cpts = [
    { x: +(pos(inK) / 100).toFixed(4), y: 0.64, l: `intake ${Math.round(inK)} kcal` },
    { x: +(pos(td) / 100).toFixed(4), y: 0.64, l: `maintenance ${Math.round(td)} kcal` },
  ];
  return `<figure class="chart spine-fig"><div class="hspine" role="img" aria-label="${escAttr(aria)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<div class="hspine-rule"></div>` +
    `<div class="hspine-gap ${gapCls}" style="left:${pos(lo).toFixed(1)}%;width:${(pos(hi) - pos(lo)).toFixed(1)}%"></div>` +
    mark(inK, "intake", true) + mark(td, "maintenance", false) +
    `</div><figcaption class="chart-cap label">${escAttr(label)}${deficit >= 0 ? ` · ${Math.abs(deficit)} kcal/day deficit (shaded)` : ` · ${Math.abs(deficit)} kcal/day surplus`}</figcaption></figure>`;
}

// Generic measuring-rule gauge 0→target (SIGNATURE 1) — the achieved portion (0→value) is
// shaded ember (work done toward the target), value tick ember, target tick muted ink. For
// "more is the goal" metrics (Zone-2 minutes vs 150/week). Edge-aware labels (no 390px clip).
export function targetSpine(value, target, { valueLabel = "now", targetLabel = "target", unit = "", label = "" } = {}) {
  const v = Number(value), tg = Number(target);
  if (!Number.isFinite(v) || !Number.isFinite(tg) || tg <= 0) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Fills in as the work accrues.</figcaption></figure>`;
  }
  const max = Math.max(tg, v) * 1.06;
  const pos = (x) => Math.max(0, Math.min(100, (x / max) * 100));
  const pct = Math.round((v / tg) * 100);
  // value label rides ABOVE the rule, target label BELOW it — a vertical stagger so the
  // two never collide horizontally when value≈target in position (the "150 min210 min" bug).
  const mark = (val, key, ember, below) => {
    const p = pos(val);
    const align = p >= 80 ? "hspine-r" : (p <= 15 ? "hspine-l" : "hspine-c");
    return `<div class="hspine-mark ${align} ${ember ? "hspine-intake" : "hspine-tdee"}" style="left:${p.toFixed(1)}%">` +
      `<span class="hspine-lab${below ? " hspine-lab-below" : ""}"><span class="hspine-v mono">${Math.round(val)}${escAttr(unit)}</span><span class="hspine-k label">${escAttr(key)}</span></span></div>`;
  };
  // Interactive hover/tap (#582): a point at the value tick and the target tick.
  // y sits on the rule (top:42px of an 88px targets box).
  const cpts = [
    { x: +(pos(v) / 100).toFixed(4), y: 0.52, l: `${valueLabel} ${Math.round(v)}${unit}` },
    { x: +(pos(tg) / 100).toFixed(4), y: 0.52, l: `${targetLabel} ${Math.round(tg)}${unit}` },
  ];
  return `<figure class="chart spine-fig spine-fig--targets"><div class="hspine" role="img" aria-label="${escAttr(`${Math.round(v)} of ${Math.round(tg)} ${unit} — ${pct} percent of target.`)}" data-cpts="${escAttr(JSON.stringify(cpts))}">` +
    `<div class="hspine-rule"></div>` +
    `<div class="hspine-gap hspine-gap-deficit" style="left:0;width:${pos(v).toFixed(1)}%"></div>` +
    mark(v, valueLabel, true, false) + mark(tg, targetLabel, false, true) +
    `</div><figcaption class="chart-cap label">${escAttr(label)} · ${pct}% of ${Math.round(tg)}${escAttr(unit)}</figcaption></figure>`;
}

// Ember-intensity heat strip — saturation = volume (steps/day). Low days render MUTED
// (faint ember), never hidden. "More colorful" = more ember intensity, NOT a second hue.
export function heatStrip(days, { valueKey = "value", label = "", unit = "", divisor = 1000, suffix = "k", max = null, compact = false, cutDate = null, caption = "" } = {}) {
  const rows = (days || []).map((d) => ({ d: d.date, v: Number(d[valueKey]) })).filter((r) => Number.isFinite(r.v));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Fills in as days accrue.</figcaption></figure>`;
  const mx = max != null ? max : (Math.max(...rows.map((r) => r.v)) || 1);
  const cell = (r) => {
    const sat = Math.max(0.08, r.v / mx);  // muted-not-hidden floor
    const dl = _shortDate(r.d);
    const cut = cutDate && r.d === cutDate ? " heat-cut" : "";
    const tip = escAttr(`${dl}: ${Math.round(r.v)}${unit}`);
    if (compact) {
      // Dense GitHub-style calendar: saturation only, no per-cell text — the shared
      // readout (motion.js data-cells) carries the label/value on hover, tap + keyboard.
      return `<div class="heat-cell heat-compact${cut}" style="--heat:${sat.toFixed(3)}" data-l="${tip}"></div>`;
    }
    const dayNum = dl.split(" ")[1] || "";
    return `<div class="heat-cell${cut}" style="--heat:${sat.toFixed(3)}" data-l="${tip}">` +
      `<span class="heat-v mono">${(r.v / divisor).toFixed(1)}${escAttr(suffix)}</span><span class="heat-d label">${escAttr(dayNum)}</span></div>`;
  };
  const cap = caption || `${label} — ember intensity = volume; low days shown muted, not hidden.`;
  return `<figure class="chart heat"><div class="heat-strip${compact ? " heat-strip-compact" : ""}" role="img" aria-label="${escAttr(label)}" data-cells>${rows.map(cell).join("")}</div>` +
    `<figcaption class="chart-cap label">${escAttr(cap)}</figcaption></figure>`;
}

// Dumbbell / paired-marker rows — two devices' estimate per category, connected; the gap
// is the honest spread (sleep stage agreement: Eight Sleep vs Whoop). A = ember, B = muted
// ink. "Agreement, not truth" — wearable stages are estimates, not PSG. items: [{label,a,b}].
export function dumbbell(items, { label = "", aLabel = "A", bLabel = "B", unit = "%" } = {}) {
  const rows = (items || []).filter((r) => Number.isFinite(Number(r.a)) && Number.isFinite(Number(r.b)));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Fills in once both devices report a night.</figcaption></figure>`;
  const max = Math.max(100, ...rows.flatMap((r) => [Number(r.a), Number(r.b)]));
  const pos = (v) => Math.max(0, Math.min(100, (Number(v) / max) * 100));
  const row = (r) => {
    const lo = Math.min(r.a, r.b), hi = Math.max(r.a, r.b), gap = Math.abs(r.a - r.b);
    return `<div class="suf-row"><span class="suf-l">${escAttr(r.label)}</span>` +
      `<span class="db-track"><span class="db-bar" style="left:${pos(lo).toFixed(1)}%;width:${(pos(hi) - pos(lo)).toFixed(1)}%"></span>` +
      `<span class="db-dot db-a" style="left:${pos(r.a).toFixed(1)}%"></span><span class="db-dot db-b" style="left:${pos(r.b).toFixed(1)}%"></span></span>` +
      `<span class="suf-v mono">${Math.round(r.a)}/${Math.round(r.b)}${escAttr(unit)}<span class="suf-amt">±${Math.round(gap)}</span></span></div>`;
  };
  const legend = `<span class="sbar-key"><i class="sbar-dot db-a"></i>${escAttr(aLabel)}</span><span class="sbar-key"><i class="sbar-dot db-b"></i>${escAttr(bLabel)}</span>`;
  // Interactive hover/tap (#582): vertically-stacked rows → hit-test by y (axis="y").
  const n = rows.length;
  const cpts = rows.map((r, i) => ({ x: 0.5, y: +((i + 0.5) / n).toFixed(4), l: `${r.label}: ${Math.round(r.a)}/${Math.round(r.b)}${unit} (±${Math.round(Math.abs(r.a - r.b))})` }));
  return `<figure class="chart"><div class="suf-rows" role="img" aria-label="${escAttr(label || "device agreement")}" data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-axis="y">${rows.map(row).join("")}</div>` +
    `<figcaption class="chart-cap label sbar-legend">${legend}${label ? ` · ${escAttr(label)}` : ""}</figcaption></figure>`;
}

// Per-muscle volume vs MEV/MAV/MRV landmark bars (training §5). Track 0→max; the MEV–MAV
// optimal band shaded; value bar ember when in the optimal band, muted ink otherwise (under/
// over — never red); an MRV tick. items: [{muscle, sets_per_week, MEV, MAV_lo, MAV_hi, MRV, status}].
export function landmarkBars(items, { label = "" } = {}) {
  const rows = (items || []).filter((m) => Number.isFinite(Number(m.sets_per_week)));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Per-muscle volume fills in as sessions accrue.</figcaption></figure>`;
  const max = Math.max(...rows.map((m) => Math.max(Number(m.MRV) || 0, Number(m.sets_per_week)))) || 1;
  const pos = (x) => Math.max(0, Math.min(100, (Number(x) / max) * 100));
  const row = (m) => {
    const tone = m.status === "optimal" ? "suf-ember" : "suf-ink";
    const bandL = pos(m.MEV), bandW = pos(m.MAV_hi) - pos(m.MEV);
    return `<div class="suf-row" role="img" aria-label="${escAttr(`${m.muscle}: ${m.sets_per_week} sets per week — ${m.status}`)}"><span class="suf-l">${escAttr(m.muscle)}</span>` +
      `<span class="lmk-track"><span class="lmk-band" style="left:${bandL.toFixed(1)}%;width:${Math.max(0, bandW).toFixed(1)}%"></span>` +
      `<span class="lmk-fill ${tone}" style="width:${pos(m.sets_per_week).toFixed(1)}%"></span>` +
      `<span class="lmk-mrv" style="left:${pos(m.MRV).toFixed(1)}%"></span></span>` +
      `<span class="suf-v mono">${m.sets_per_week}/wk<span class="suf-amt">${escAttr(m.status)}</span></span></div>`;
  };
  // Interactive hover/tap (#582): vertically-stacked rows → hit-test by y (axis="y").
  const n = rows.length;
  const cpts = rows.map((m, i) => ({ x: 0.5, y: +((i + 0.5) / n).toFixed(4), l: `${m.muscle}: ${m.sets_per_week}/wk — ${m.status}` }));
  return `<figure class="chart"><div class="suf-rows" role="img" aria-label="${escAttr(label || "per-muscle volume")}" data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-axis="y">${rows.map(row).join("")}</div>` +
    `<figcaption class="chart-cap label">Sets/week vs the MEV–MAV optimal band (shaded) · MRV tick. ${escAttr(label)}</figcaption></figure>`;
}

// Generic per-day stacked-category columns — segments are an ember-derived ramp (tone keys
// map to seg-<tone> CSS, e.g. lift=ember / cardio=ember-tint / mob=muted ink). NO second hue.
// days: [{date, [seg.key]: minutes}]; segments: [{key, label, tone}].
export function stackedDayColumns(days, segments, { label = "", legendUnit = "min", emptyMsg = "", minPoints = 1 } = {}) {
  const rows = (days || []).map((d) => {
    const segs = segments.map((s) => ({ ...s, v: Number(d[s.key]) || 0 }));
    return { d: d.date, segs, total: segs.reduce((a, s) => a + s.v, 0) };
  }).filter((r) => r.total > 0);
  if (rows.length < minPoints) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(emptyMsg || `Fills in at ${minPoints}+ points — ${rows.length} so far.`)}</figcaption></figure>`;
  const max = Math.max(...rows.map((r) => r.total));
  const h = (v) => `${((v / max) * 100).toFixed(1)}%`;
  const col = (r) => {
    const segHtml = r.segs.slice().reverse().map((s) => (s.v > 0 ? `<span class="scol-seg seg-${escAttr(s.tone)}" style="height:${h(s.v)}"></span>` : "")).join("");
    return `<div class="scol"><div class="scol-stack">${segHtml}</div>` +
      `<span class="scol-l label">${escAttr(_shortDate(r.d).split(" ")[1] || "")}</span></div>`;
  };
  const legend = segments.map((s) => `<span class="sbar-key"><i class="sbar-dot seg-${escAttr(s.tone)}"></i>${escAttr(s.label)}</span>`).join("");
  // Interactive hover/tap (#582): a point at each column top — nearest-by-x lands on
  // the day under the finger. Replaces the native title tooltip.
  const cpts = rows.map((r, i) => ({
    x: +((i + 0.5) / rows.length).toFixed(4),
    y: +Math.max(0.03, Math.min(0.97, 1 - r.total / max)).toFixed(4),
    l: `${_shortDate(r.d)}: ${r.segs.filter((s) => s.v > 0).map((s) => `${s.label} ${Math.round(s.v)}`).join(" · ")} ${legendUnit}`,
  }));
  return `<figure class="chart"><div class="scols" role="img" aria-label="${escAttr(label)}" data-cpts="${escAttr(JSON.stringify(cpts))}">${rows.map(col).join("")}</div>` +
    `<figcaption class="chart-cap label sbar-legend">${legend}${label ? ` · ${escAttr(label)}` : ""}</figcaption></figure>`;
}

// Eating-window ribbon (nutrition §4) — per-day first→last meal on a 5am→midnight axis,
// ember = the actual window, a faint bar = the 16:8 reference (an 8h window from the first
// meal). Reveals at a glance whether the day runs tighter or wider than 16:8. days:
// [{date, first_min, last_min}] (minutes from midnight).
export function mealWindowRibbon(days, { refHours = 8, label = "" } = {}) {
  const rows = (days || []).filter((d) => Number.isFinite(Number(d.first_min)) && Number.isFinite(Number(d.last_min)));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The eating-window ribbon fills in once meals are logged with times.</figcaption></figure>`;
  const AX_START = 5 * 60, AX_END = 24 * 60, SPAN = AX_END - AX_START;
  const pos = (m) => Math.max(0, Math.min(100, ((m - AX_START) / SPAN) * 100));
  const fmtT = (m) => `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, "0")}`;
  const refW = Math.min(100, (refHours * 60 / SPAN) * 100);
  const row = (d) => {
    const l = pos(d.first_min), w = Math.max(1.5, pos(d.last_min) - pos(d.first_min));
    const hrs = ((d.last_min - d.first_min) / 60).toFixed(1);
    const tip = escAttr(`${_shortDate(d.date)}: ${fmtT(d.first_min)}–${fmtT(d.last_min)} · ${hrs}h`);
    return `<div class="ewin-row" data-l="${tip}"><span class="ewin-day label">${escAttr(_shortDate(d.date))}</span>` +
      `<span class="ewin-track"><span class="ewin-ref" style="left:${l.toFixed(1)}%;width:${refW.toFixed(1)}%"></span>` +
      `<span class="ewin-bar" style="left:${l.toFixed(1)}%;width:${w.toFixed(1)}%"></span></span>` +
      `<span class="ewin-v mono">${fmtT(d.first_min)}–${fmtT(d.last_min)} · ${hrs}h</span></div>`;
  };
  return `<figure class="chart ewin">${label ? `<p class="suf-head label">${escAttr(label)}</p>` : ""}` +
    `<div class="ewin-rows" role="img" aria-label="${escAttr(label || "eating-window ribbon")}" data-cells>${rows.map(row).join("")}</div>` +
    `<figcaption class="chart-cap label">5am → midnight · ember = your window · faint = an ${refHours}h (16:8) reference from the first meal.</figcaption></figure>`;
}

// Per-day stacked composition columns BY ENERGY (protein·4 / carbs·4 / fat·9). Each
// column = one day's calories segmented by macro — reveals whether the cut comes out of
// carbs/fat while protein holds. Refuses < 4 points (honest, like lineChart). Ember =
// protein (the floor to hold); muted inks for carbs/fat. days: [{date, protein_g, carbs_g, fat_g}].
export function stackedColumns(days, { label = "", emptyMsg = "" } = {}) {
  const rows = (days || []).map((d) => {
    const p = Number(d.protein_g) * 4, c = Number(d.carbs_g) * 4, f = Number(d.fat_g) * 9;
    return { d: d.date, p: Number.isFinite(p) ? p : 0, c: Number.isFinite(c) ? c : 0, f: Number.isFinite(f) ? f : 0 };
  }).filter((r) => (r.p + r.c + r.f) > 0);
  if (rows.length < 4) {
    const n = rows.length;
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">${escAttr(emptyMsg || `Per-day macro composition draws in at 4+ logged days — ${n} so far.`)}</figcaption></figure>`;
  }
  const max = Math.max(...rows.map((r) => r.p + r.c + r.f));
  const h = (v) => `${((v / max) * 100).toFixed(1)}%`;
  const col = (r) => {
    const day = _shortDate(r.d);
    return `<div class="scol">` +
      `<div class="scol-stack">` +
      `<span class="scol-seg sbar-faint" style="height:${h(r.f)}"></span>` +
      `<span class="scol-seg sbar-ink" style="height:${h(r.c)}"></span>` +
      `<span class="scol-seg sbar-ember" style="height:${h(r.p)}"></span>` +
      `</div><span class="scol-l label">${escAttr(day)}</span></div>`;
  };
  const legend = `<span class="sbar-key"><i class="sbar-dot sbar-ember"></i>protein</span><span class="sbar-key"><i class="sbar-dot sbar-ink"></i>carbs</span><span class="sbar-key"><i class="sbar-dot sbar-faint"></i>fat</span>`;
  // Interactive hover/tap (#582): a point at each column top — nearest-by-x lands on
  // the day under the finger. Replaces the native title tooltip.
  const cpts = rows.map((r, i) => {
    const total = r.p + r.c + r.f;
    return { x: +((i + 0.5) / rows.length).toFixed(4), y: +Math.max(0.03, Math.min(0.97, 1 - total / max)).toFixed(4), l: `${_shortDate(r.d)}: protein ${Math.round(r.p)} · carbs ${Math.round(r.c)} · fat ${Math.round(r.f)} kcal` };
  });
  return `<figure class="chart"><div class="scols" role="img" aria-label="${escAttr(`Per-day macro composition by energy across ${rows.length} days. ${label}`)}" data-cpts="${escAttr(JSON.stringify(cpts))}">${rows.map(col).join("")}</div>` +
    `<figcaption class="chart-cap label sbar-legend">${legend} · by energy (kcal)${label ? ` · ${escAttr(label)}` : ""}</figcaption></figure>`;
}

// Correlation chips — top habit/factor ↔ outcome Pearson r, correlative-framed (never
// causal, N=1). items: [{label, r, n}]. Strength shown by bar width; sign by direction
// word. Reuses the honesty vocabulary; ember for positive pull, muted ink for inverse.
export function correlationChip(items, { label = "", outcome = "the score" } = {}) {
  const rows = (items || []).map((c) => ({ l: c.label, r: Number(c.r), n: c.n })).filter((c) => Number.isFinite(c.r));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">Correlations fill in as days accrue.</figcaption></figure>`;
  const chips = rows.map((c) => {
    const mag = Math.min(1, Math.abs(c.r));
    const dir = c.r >= 0 ? "moves with" : "moves against";
    const tone = c.r >= 0 ? "ember" : "ink";
    return `<div class="corr-row"><span class="corr-l">${escAttr(c.l)}</span>` +
      `<span class="corr-bar"><span class="corr-fill sbar-${tone}" style="width:${(mag * 100).toFixed(0)}%"></span></span>` +
      `<span class="corr-r mono">r=${c.r.toFixed(2)}${c.n ? ` · n=${c.n}` : ""} · ${dir} ${escAttr(outcome)}</span></div>`;
  }).join("");
  return `<figure class="chart corr"><div class="corr-rows">${chips}</div>` +
    `<figcaption class="chart-cap label">${escAttr(label)} — correlation, not cause (N=1).</figcaption></figure>`;
}

// Vertical bars. items: [{<labelKey>,<valueKey>}]. Down bars (below 0 or flagged) muted.
export function barChart(items, { valueKey = "value", labelKey = "label", height = 130, label = "" } = {}) {
  const rows = (items || []).map((it) => ({ l: it[labelKey], v: Number(it[valueKey]) })).filter((r) => Number.isFinite(r.v));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">No data yet.</figcaption></figure>`;
  const max = Math.max(1, ...rows.map((r) => r.v));
  const bars = rows.map((r) => `<div class="cbar"><span class="cbar-fill" style="height:${Math.max(3, (r.v / max) * 100)}%"></span><span class="cbar-l label">${escAttr(r.l)}</span></div>`).join("");
  // Interactive hover/tap (#582): a point at each bar top — nearest-by-x lands on the
  // bar under the finger. Replaces the native title tooltip.
  const n = rows.length;
  const cpts = rows.map((r, i) => ({ x: +((i + 0.5) / n).toFixed(4), y: +Math.max(0.05, Math.min(0.95, 1 - r.v / max)).toFixed(4), l: `${r.l}: ${Math.round(r.v * 10) / 10}` }));
  return `<figure class="chart"><div class="cbars" role="img" aria-label="${escAttr(label || "bar chart")}" data-cpts="${escAttr(JSON.stringify(cpts))}" style="--cbar-h:${height}px">${bars}</div>${label ? `<figcaption class="chart-cap label">${escAttr(label)}</figcaption>` : ""}</figure>`;
}

/* ── The character sheet (§8.6) ──────────────────────────────────────────────
   pillarRing — the legacy 7-segment donut, ported: each arc segment fills in
   proportion to its pillar's raw_score (0-100), colored by the pillar's §8.6
   identity token. Center content is the caller's (HTML overlay via .pring-c).
   radarChart — the 7-axis spider: the polygon literally reshapes as scores
   move. Both stroke-drawn, token-driven, no gradients. */
export function pillarRing(pillars, { size = 360, rimR = 0.46, width = 10 } = {}) {
  const ps = (pillars || []).filter((p) => p && p.name);
  if (!ps.length) return "";
  const C = size / 2, R = size * rimR, N = ps.length;
  const GAP_DEG = 4, SEG_DEG = (360 - N * GAP_DEG) / N, circ = 2 * Math.PI * R;
  let out = "";
  ps.forEach((p, i) => {
    const color = `var(--pillar-${escAttr(String(p.name).toLowerCase())}, var(--ember))`;
    const segLen = (SEG_DEG / 360) * circ;
    // #747: a not-yet-instrumented pillar has no real raw_score to fill with —
    // an empty arc (just the pale track) rather than the placeholder neutral 50.
    const fillLen = p.not_instrumented ? 0 : (segLen * Math.max(0, Math.min(Number(p.raw_score) || 0, 100)) / 100);
    const off = (-i * (SEG_DEG + GAP_DEG) * circ) / 360;
    const rot = `transform="rotate(-90 ${C} ${C})"`;
    out += `<circle class="pring-seg" cx="${C}" cy="${C}" r="${R}" fill="none" stroke="${color}" stroke-width="${width}" stroke-dasharray="${segLen.toFixed(2)} ${(circ - segLen).toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}" ${rot}/>`;
    out += `<circle class="pring-fill" data-i="${i}" cx="${C}" cy="${C}" r="${R}" fill="none" stroke="${color}" stroke-width="${width}" stroke-dasharray="${fillLen.toFixed(2)} ${(circ - fillLen).toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}" ${rot} style="transition-delay:${(0.2 + i * 0.1).toFixed(1)}s"/>`;
  });
  return out;
}

// Companion to pillarRing: the interaction points for the shared readout (#583). pillarRing
// returns only the arc <circle>s (the caller owns the <svg>), so the caller attaches these
// to that svg as data-cpts + data-cpts-hit="xy". One focus point per segment, placed on the
// arc MIDLINE (angle measured clockwise from 12 o'clock, matching the rotate(-90) dash start);
// geometry stays here beside the arcs so the two never drift. labels: optional name→text map.
export function pillarRingCpts(pillars, { size = 360, rimR = 0.46, labels = null } = {}) {
  const ps = (pillars || []).filter((p) => p && p.name);
  if (!ps.length) return [];
  const C = size / 2, R = size * rimR, N = ps.length;
  const GAP_DEG = 4, SEG_DEG = (360 - N * GAP_DEG) / N;
  return ps.map((p, i) => {
    const theta = ((i * (SEG_DEG + GAP_DEG) + SEG_DEG / 2) * Math.PI) / 180;
    const x = C + R * Math.sin(theta), y = C - R * Math.cos(theta);
    const raw = Math.max(0, Math.min(Number(p.raw_score) || 0, 100));
    const nm = (labels && labels[p.name]) || (String(p.name).charAt(0).toUpperCase() + String(p.name).slice(1));
    // #747: the hover readout shouldn't quote the placeholder neutral score either.
    return { x: +(x / size).toFixed(4), y: +(y / size).toFixed(4), l: p.not_instrumented ? `${nm}: not yet instrumented` : `${nm}: ${Math.round(raw)}` };
  });
}

export function radarChart(axes, { size = 320 } = {}) {
  const ax = (axes || []).filter((a) => a && a.label != null);
  if (ax.length < 3) return "";
  const C = size / 2, R = size * 0.36, N = ax.length;
  const pt = (i, r) => {
    const a = (i / N) * 2 * Math.PI - Math.PI / 2;
    return [C + r * Math.cos(a), C + r * Math.sin(a)];
  };
  let grid = "";
  for (const f of [0.25, 0.5, 0.75, 1]) {
    grid += `<polygon class="radar-grid" points="${ax.map((_, i) => pt(i, R * f).map((n) => n.toFixed(1)).join(",")).join(" ")}" fill="none" vector-effect="non-scaling-stroke"/>`;
  }
  let spokes = "", labels = "", dots = "";
  ax.forEach((a, i) => {
    const [ex, ey] = pt(i, R);
    spokes += `<line class="radar-grid" x1="${C}" y1="${C}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}" vector-effect="non-scaling-stroke"/>`;
    const [lx, ly] = pt(i, R + size * 0.075);
    labels += `<text class="radar-lbl" x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="middle">${escAttr(a.label)}</text>`;
    const v = Math.max(0, Math.min(Number(a.value) || 0, 100));
    const [dx, dy] = pt(i, (R * v) / 100);
    const color = a.key ? `var(--pillar-${escAttr(String(a.key).toLowerCase())}, var(--ember))` : "var(--ember)";
    dots += `<circle class="radar-dot" cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="3.5" fill="${color}"/>`;
  });
  const poly = ax.map((a, i) => pt(i, (R * Math.max(0, Math.min(Number(a.value) || 0, 100))) / 100).map((n) => n.toFixed(1)).join(",")).join(" ");
  // Interactive readout (#583): one focus point per vertex (where the radar-dot sits) →
  // 2-D nearest (data-cpts-hit="xy"); label carries the axis + its 0–100 value.
  const cpts = ax.map((a, i) => {
    const v = Math.max(0, Math.min(Number(a.value) || 0, 100));
    const [dx, dy] = pt(i, (R * v) / 100);
    return { x: +(dx / size).toFixed(4), y: +(dy / size).toFixed(4), l: `${a.label}: ${Math.round(v)}` };
  });
  return `<figure class="chart radar-chart"><svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Pillar radar: ${escAttr(ax.map((a) => `${a.label} ${Math.round(a.value || 0)}`).join(", "))}" data-cpts="${escAttr(JSON.stringify(cpts))}" data-cpts-hit="xy">` +
    grid + spokes +
    `<polygon class="radar-poly" points="${poly}"/>` +
    dots + labels + `</svg></figure>`;
}

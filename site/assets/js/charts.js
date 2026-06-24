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
  return `<figure class="chart${spine ? " chart--spined" : ""}">${spineEl}<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}">` +
    `<path class="chart-fill" d="${area}"/>${goalLine}` +
    `<path class="chart-line" d="${line}" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label)}${goal != null ? ` · goal ${escAttr(goal)}${escAttr(unit)}` : ""}${_span ? ` · ${escAttr(_span)}` : ""} · ${pts.length} pts</figcaption></figure>`;
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
  return `<figure class="chart wt-chart" data-wt-min="${min.toFixed(2)}" data-wt-max="${max.toFixed(2)}" data-wt-h="${H}" data-wt-p="${P}">` +
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}">` +
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

// P0.6 — projection cone. A WIDENING confidence band from the current weigh-in to ~goal,
// modelled as an exponential approach (weight = goal + (cur−goal)·e^(−t/τ)): it starts at the
// measured rate and SLOWS as it nears goal — the honest shape of a cut, not a straight line.
// Three τ (fast = current rate sustained, mid, slow) give the cone; rung date-markers come off
// the mid path. The cone is wide because the early rate is water-inflated and unproven. The
// "bet" (fast goal-date) is stated AND flagged for grading as real weigh-ins resolve it.
// current: {date, w}. ratePerWeek: negative (lb/wk). rungs: [weights] to date-mark.
export function projectionCone(current, goal, ratePerWeek, { provisional = false, height = 210, rungs = [], label = "" } = {}) {
  const cur = Number(current && current.w), g = Number(goal), rWk = Number(ratePerWeek);
  const t0 = current && current.date ? Date.parse(current.date) : NaN;
  if (!Number.isFinite(cur) || !Number.isFinite(g) || !Number.isFinite(rWk) || !Number.isFinite(t0) || rWk >= 0 || cur <= g) {
    return `<figure class="chart chart--empty"><figcaption class="chart-cap label">The projection cone draws once there's a sustained downward rate to extend — right now the loss is too new (and too watery) to forecast.</figcaption></figure>`;
  }
  // Linear bounds from the same apex: fast = current rate (water-inflated), mid ~72%, slow
  // 50%. Their divergence over time IS the uncertainty cone — wide because the rate is young.
  const rDay = Math.abs(rWk) / 7;
  const rFast = rDay, rMid = rDay * 0.72, rSlow = rDay * 0.5;
  const reach = (r) => (cur - g) / r; // days to goal at that rate
  const horizon = Math.min(900, reach(rSlow));
  const W = 600, H = height, P = 10;
  const x = (t) => P + (t / horizon) * (W - 2 * P);
  const ymin = g - 3, ymax = cur + 3;
  const y = (w) => P + (1 - (w - ymin) / (ymax - ymin)) * (H - 2 * P);
  const wAt = (r, t) => Math.max(g, cur - r * t);
  const curvePts = (r) => { const a = []; const step = horizon / 64; for (let t = 0; t <= horizon + 1e-6; t += step) a.push([t, wAt(r, t)]); return a; };
  const toPath = (a) => a.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
  const fast = curvePts(rFast), slow = curvePts(rSlow), mid = curvePts(rMid);
  const cone = `${toPath(slow)} ${fast.slice().reverse().map((p) => `L${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ")} Z`;
  const goalLine = `<line class="pc-goal" x1="${P}" y1="${y(g).toFixed(1)}" x2="${W - P}" y2="${y(g).toFixed(1)}" vector-effect="non-scaling-stroke"/>`;
  const dateAt = (r, w) => t0 + ((cur - w) / r) * 86400000;
  // Rung date-markers from the MID path (only rungs strictly between goal and current).
  const marks = (rungs || []).filter((r) => r > g + 0.5 && r < cur - 0.5).map((r) => {
    const t = (cur - r) / rMid;
    return `<line class="pc-rung" x1="${x(t).toFixed(1)}" y1="${y(r).toFixed(1)}" x2="${x(t).toFixed(1)}" y2="${(H - P).toFixed(1)}" vector-effect="non-scaling-stroke"/>`;
  }).join("");
  const _d = (ms) => { const d = new Date(ms); return `${_MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const betFast = _d(dateAt(rFast, g)), betMid = _d(dateAt(rMid, g)), betSlow = _d(dateAt(rSlow, g));
  const summary = `Projection cone from ${Math.round(cur)} lb toward ${g} lb: at the current rate ~${betFast}, realistically ${betMid}–${betSlow} as the loss slows.`;
  return `<figure class="chart pc-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}">` +
    `<path class="pc-cone" d="${cone}"/>${marks}${goalLine}` +
    `<path class="pc-mid" d="${toPath(mid)}" fill="none" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(0).toFixed(1)}" cy="${y(cur).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label || "Projected weight → goal")} · the band widens with uncertainty; the goal line is ${g} lb` +
    `<span class="pc-bet">The bet: hold ${_r1(rWk)} lb/wk and 185 lands ~${escAttr(betFast)} — but a cut slows as it goes, so realistically <strong>${escAttr(betMid)}–${escAttr(betSlow)}</strong>.${provisional ? " Early rate is mostly water; this will slow." : ""} Graded against each new weigh-in as it resolves.</span>` +
    `</figcaption></figure>`;
}
const _r1 = (n) => { const r = Math.round(Number(n) * 10) / 10; return Number.isInteger(r) ? String(r) : r.toFixed(1); };

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
  return `<figure class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}">` +
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
  return `<div class="vr vr-${escAttr(tone)}${thin ? " vr-thin" : ""}">` +
    `<svg class="vr-svg" viewBox="0 0 100 100" role="img" aria-label="${escAttr(aria)}">` +
    `<circle class="vr-track" cx="50" cy="50" r="${r}" fill="none"/>` +
    `<circle class="vr-arc" cx="50" cy="50" r="${r}" fill="none" stroke-dasharray="${dash}" transform="rotate(-90 50 50)" stroke-linecap="round"/>` +
    `</svg>` +
    `<div class="vr-c"><span class="vr-v num">${escAttr(value)}</span>${sub ? `<span class="vr-sub label">${escAttr(sub)}</span>` : ""}</div>` +
    `<span class="vr-l label">${escAttr(label)}</span></div>`;
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
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path class="chart-line" d="${line}" vector-effect="non-scaling-stroke"/></svg>`;
}

// Horizontal 100%-stacked bar — for a composition (e.g. macro split P/C/F). segments:
// [{label, value, tone}] where tone ∈ {ember, ink, faint} (no new hues — ember = the
// tracked/primary segment, muted inks for the rest). Renders the % split + a legend.
export function stackedBar(segments, { label = "", unit = "g" } = {}) {
  const segs = (segments || []).map((s) => ({ l: s.label, v: Number(s.value) || 0, t: s.tone || "ink" })).filter((s) => s.v > 0);
  const total = segs.reduce((a, s) => a + s.v, 0);
  if (!total) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">No data yet.</figcaption></figure>`;
  const bar = segs.map((s) => `<span class="sbar-seg sbar-${escAttr(s.t)}" style="width:${((s.v / total) * 100).toFixed(1)}%" title="${escAttr(s.l)} ${Math.round(s.v)}${escAttr(unit)}"></span>`).join("");
  const legend = segs.map((s) => `<span class="sbar-key"><i class="sbar-dot sbar-${escAttr(s.t)}"></i>${escAttr(s.l)} ${Math.round(s.v)}${escAttr(unit)} · ${Math.round((s.v / total) * 100)}%</span>`).join("");
  return `<figure class="chart"><div class="sbar" role="img" aria-label="${escAttr(label)}">${bar}</div><figcaption class="chart-cap label sbar-legend">${legend}</figcaption></figure>`;
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
  return `<figure class="chart suf">${label ? `<p class="suf-head label">${escAttr(label)}</p>` : ""}` +
    `<div class="suf-rows">${rows.map(row).join("")}</div>` +
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
  return `<figure class="chart spine-fig"><div class="hspine" role="img" aria-label="${escAttr(aria)}">` +
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
  const mark = (val, key, ember) => {
    const p = pos(val);
    const align = p >= 80 ? "hspine-r" : (p <= 15 ? "hspine-l" : "hspine-c");
    return `<div class="hspine-mark ${align} ${ember ? "hspine-intake" : "hspine-tdee"}" style="left:${p.toFixed(1)}%">` +
      `<span class="hspine-lab"><span class="hspine-v mono">${Math.round(val)}${escAttr(unit)}</span><span class="hspine-k label">${escAttr(key)}</span></span></div>`;
  };
  return `<figure class="chart spine-fig"><div class="hspine" role="img" aria-label="${escAttr(`${Math.round(v)} of ${Math.round(tg)} ${unit} — ${pct} percent of target.`)}">` +
    `<div class="hspine-rule"></div>` +
    `<div class="hspine-gap hspine-gap-deficit" style="left:0;width:${pos(v).toFixed(1)}%"></div>` +
    mark(v, valueLabel, true) + mark(tg, targetLabel, false) +
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
      // Dense GitHub-style calendar: saturation only, no per-cell text (tooltip carries it).
      return `<div class="heat-cell heat-compact${cut}" style="--heat:${sat.toFixed(3)}" title="${tip}"></div>`;
    }
    const dayNum = dl.split(" ")[1] || "";
    return `<div class="heat-cell${cut}" style="--heat:${sat.toFixed(3)}" title="${tip}">` +
      `<span class="heat-v mono">${(r.v / divisor).toFixed(1)}${escAttr(suffix)}</span><span class="heat-d label">${escAttr(dayNum)}</span></div>`;
  };
  const cap = caption || `${label} — ember intensity = volume; low days shown muted, not hidden.`;
  return `<figure class="chart heat"><div class="heat-strip${compact ? " heat-strip-compact" : ""}" role="img" aria-label="${escAttr(label)}">${rows.map(cell).join("")}</div>` +
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
  return `<figure class="chart"><div class="suf-rows">${rows.map(row).join("")}</div>` +
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
  return `<figure class="chart"><div class="suf-rows">${rows.map(row).join("")}</div>` +
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
    const tip = r.segs.filter((s) => s.v > 0).map((s) => `${s.label} ${Math.round(s.v)}`).join(" · ");
    return `<div class="scol" title="${escAttr(`${_shortDate(r.d)}: ${tip} ${legendUnit}`)}"><div class="scol-stack">${segHtml}</div>` +
      `<span class="scol-l label">${escAttr(_shortDate(r.d).split(" ")[1] || "")}</span></div>`;
  };
  const legend = segments.map((s) => `<span class="sbar-key"><i class="sbar-dot seg-${escAttr(s.tone)}"></i>${escAttr(s.label)}</span>`).join("");
  return `<figure class="chart"><div class="scols" role="img" aria-label="${escAttr(label)}">${rows.map(col).join("")}</div>` +
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
    return `<div class="ewin-row"><span class="ewin-day label">${escAttr(_shortDate(d.date))}</span>` +
      `<span class="ewin-track"><span class="ewin-ref" style="left:${l.toFixed(1)}%;width:${refW.toFixed(1)}%"></span>` +
      `<span class="ewin-bar" style="left:${l.toFixed(1)}%;width:${w.toFixed(1)}%"></span></span>` +
      `<span class="ewin-v mono">${fmtT(d.first_min)}–${fmtT(d.last_min)} · ${hrs}h</span></div>`;
  };
  return `<figure class="chart ewin">${label ? `<p class="suf-head label">${escAttr(label)}</p>` : ""}` +
    `<div class="ewin-rows">${rows.map(row).join("")}</div>` +
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
    return `<div class="scol" title="${escAttr(`${day}: protein ${Math.round(r.p)} · carbs ${Math.round(r.c)} · fat ${Math.round(r.f)} kcal`)}">` +
      `<div class="scol-stack">` +
      `<span class="scol-seg sbar-faint" style="height:${h(r.f)}"></span>` +
      `<span class="scol-seg sbar-ink" style="height:${h(r.c)}"></span>` +
      `<span class="scol-seg sbar-ember" style="height:${h(r.p)}"></span>` +
      `</div><span class="scol-l label">${escAttr(day)}</span></div>`;
  };
  const legend = `<span class="sbar-key"><i class="sbar-dot sbar-ember"></i>protein</span><span class="sbar-key"><i class="sbar-dot sbar-ink"></i>carbs</span><span class="sbar-key"><i class="sbar-dot sbar-faint"></i>fat</span>`;
  return `<figure class="chart"><div class="scols" role="img" aria-label="${escAttr(`Per-day macro composition by energy across ${rows.length} days. ${label}`)}">${rows.map(col).join("")}</div>` +
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
  return `<figure class="chart"><div class="cbars" style="--cbar-h:${height}px">${bars}</div>${label ? `<figcaption class="chart-cap label">${escAttr(label)}</figcaption>` : ""}</figure>`;
}

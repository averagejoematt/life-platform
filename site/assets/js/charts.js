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

function _points(data, valueKey, dateKey) {
  return data
    .map((d) => (typeof d === "number" ? { v: d } : { v: Number(d[valueKey]), d: d[dateKey] }))
    .filter((p) => Number.isFinite(p.v));
}

// A trend line with optional goal line + filled area. data: [{<dateKey>,<valueKey>}] or [numbers].
export function lineChart(data, { valueKey = "value", dateKey = "date", goal = null, height = 130, unit = "", label = "", emptyMsg = "" } = {}) {
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
  return `<figure class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escAttr(summary)}">` +
    `<path class="chart-fill" d="${area}"/>${goalLine}` +
    `<path class="chart-line" d="${line}" vector-effect="non-scaling-stroke"/>` +
    `<circle class="chart-dot" cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="3.5"/></svg>` +
    `<figcaption class="chart-cap label">${escAttr(label)}${goal != null ? ` · goal ${escAttr(goal)}${escAttr(unit)}` : ""}${_span ? ` · ${escAttr(_span)}` : ""} · ${pts.length} pts</figcaption></figure>`;
}

// Tiny inline sparkline (no axes/caption). values: [numbers].
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

// Vertical bars. items: [{<labelKey>,<valueKey>}]. Down bars (below 0 or flagged) muted.
export function barChart(items, { valueKey = "value", labelKey = "label", height = 130, label = "" } = {}) {
  const rows = (items || []).map((it) => ({ l: it[labelKey], v: Number(it[valueKey]) })).filter((r) => Number.isFinite(r.v));
  if (!rows.length) return `<figure class="chart chart--empty"><figcaption class="chart-cap label">No data yet.</figcaption></figure>`;
  const max = Math.max(1, ...rows.map((r) => r.v));
  const bars = rows.map((r) => `<div class="cbar"><span class="cbar-fill" style="height:${Math.max(3, (r.v / max) * 100)}%"></span><span class="cbar-l label">${escAttr(r.l)}</span></div>`).join("");
  return `<figure class="chart"><div class="cbars" style="--cbar-h:${height}px">${bars}</div>${label ? `<figcaption class="chart-cap label">${escAttr(label)}</figcaption>` : ""}</figure>`;
}

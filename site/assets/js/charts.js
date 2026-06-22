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

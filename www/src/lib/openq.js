// The open questions, drawn (2026-11-14, sprint III item 7). Each figure carries only a served number and draws the
// gap as plainly as the evidence: the pace with its interval (the rate flag's own line is never published — #5074 —
// so none is drawn), the six dimensions with the three that have no public measure left as empty frames, and each
// pre-registered test's paired days against what a verdict needs. Native-size SVG (never scaled down on a phone):
// every label stays at 12.5px. A figure whose numbers are not served returns null and nothing is drawn.
import { num } from "./format.js";

const MONO = `font-family="IBM Plex Mono,monospace" font-size="12.5"`;
const INK = "#121212";
const MUTED = "#5C5C58";
const COBALT = "#1B3FD6";
const RULE = "#E3E3DD";
export const OQ_WIDTH = 270; // fits an 86% card on a 360px phone without scaling the labels

/** The weekly pace as a dot on a lb-a-week axis, with its served interval as a bar. */
export function paceFigure({ rate, lo, hi, level }, { width = OQ_WIDTH } = {}) {
  if (rate == null) return null;
  const top = Math.max(4, Math.ceil(Math.max(rate, hi ?? 0) + 0.5));
  const pad = 8;
  const x = (v) => pad + (v / top) * (width - 2 * pad);
  let g = `<line x1="${x(0)}" y1="14" x2="${x(top).toFixed(1)}" y2="14" stroke="${RULE}" stroke-width="2"/>`;
  for (let v = 0; v <= top; v++) {
    g += `<text x="${x(v).toFixed(1)}" y="34" text-anchor="middle" ${MONO} fill="${MUTED}">${v}</text>`;
  }
  if (lo != null && hi != null) {
    g += `<rect x="${x(lo).toFixed(1)}" y="9" width="${Math.max(2, x(hi) - x(lo)).toFixed(1)}" height="10" fill="${COBALT}" opacity="0.25"/>`;
  }
  g += `<circle cx="${x(rate).toFixed(1)}" cy="14" r="5" fill="${COBALT}"/>`;
  const ci = lo != null && hi != null && level ? `; ${level}% interval ${num(lo, 1)} to ${num(hi, 1)}` : "";
  return `<svg viewBox="0 0 ${width} 38" width="${width}" height="38" role="img" aria-label="About ${num(rate, 1)} pounds lost a week${ci}.">${g}</svg>`;
}

/** The six dimensions: a measured one is a filled frame, one with no public measure an empty dashed frame. */
export function dimsFigure(dims, { width = OQ_WIDTH } = {}) {
  if (!Array.isArray(dims) || !dims.length) return null;
  const per = 3;
  const gap = 4;
  const w = (width - gap * (per - 1)) / per;
  const h = 22;
  let g = "";
  dims.forEach((d, i) => {
    const cx = (i % per) * (w + gap);
    const cy = Math.floor(i / per) * (h + gap);
    g += d.measured
      ? `<rect x="${cx.toFixed(1)}" y="${cy}" width="${w.toFixed(1)}" height="${h}" fill="${INK}"/>`
      : `<rect x="${(cx + 0.75).toFixed(1)}" y="${cy + 0.75}" width="${(w - 1.5).toFixed(1)}" height="${h - 1.5}" fill="none" stroke="${MUTED}" stroke-width="1.5" stroke-dasharray="3 3"/>`;
    g += `<text x="${(cx + w / 2).toFixed(1)}" y="${cy + 15}" text-anchor="middle" ${MONO} fill="${d.measured ? "#FFFFFF" : MUTED}">${d.label}</text>`;
  });
  const rows = Math.ceil(dims.length / per);
  const H = rows * h + (rows - 1) * gap;
  const yes = dims.filter((d) => d.measured).map((d) => d.label);
  const no = dims.filter((d) => !d.measured).map((d) => d.label);
  const aria = `Measured in public: ${yes.join(", ") || "none"}. No public measure: ${no.join(", ") || "none"}.`;
  return `<svg viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${aria}">${g}</svg>`;
}

/** How far a test is toward a verdict: the weaker side's paired days over the days each side needs (the paired days over
 * both sides' total before the engine splits them). Null when the test has not been checked. */
export function testProgress(t) {
  if (!t || t.min_days_per_arm == null || t.days_observed == null || t.status === "archived") return null;
  const per = t.min_days_per_arm;
  const split = Boolean(t.n_condition || t.n_comparison);
  return split ? Math.min(t.n_condition || 0, t.n_comparison || 0) / per : t.days_observed / (2 * per);
}

/** Every checked test as a dot on a 0 → 'enough for a verdict' line; dots that would overlap stack upward. */
export function testsFigure(tests, { width = OQ_WIDTH } = {}) {
  const ps = (tests || []).map(testProgress).filter((p) => p != null).sort((a, b) => a - b);
  if (!ps.length) return null;
  const pad = 8;
  const end = width - 2 * pad;
  const x = (p) => pad + (Math.min(p, 1.15) / 1.15) * end;
  const dots = [];
  for (const p of ps) {
    const px = x(p);
    dots.push({ p, px, level: dots.filter((d) => Math.abs(d.px - px) < 11).length });
  }
  const lift = Math.max(...dots.map((d) => d.level)) * 11;
  const axis = 18 + lift; // the line the dots sit on
  let g = `<line x1="${pad}" y1="${axis}" x2="${pad + end}" y2="${axis}" stroke="${RULE}" stroke-width="2"/>`;
  g += `<line x1="${x(1).toFixed(1)}" y1="2" x2="${x(1).toFixed(1)}" y2="${axis + 4}" stroke="${INK}" stroke-width="1.5" stroke-dasharray="2 2"/>`;
  for (const d of dots) g += `<circle cx="${d.px.toFixed(1)}" cy="${axis - 7 - d.level * 11}" r="4.5" fill="${d.p >= 1 ? COBALT : INK}"/>`;
  g += `<text x="${pad}" y="${axis + 18}" ${MONO} fill="${MUTED}">no days</text>`;
  g += `<text x="${x(1).toFixed(1)}" y="${axis + 18}" text-anchor="end" ${MONO} fill="${MUTED}">enough for a verdict</text>`;
  const ready = ps.filter((p) => p >= 1).length;
  const aria =
    `${ps.length} checked ${ps.length === 1 ? "test" : "tests"}; ${ready} with enough paired days on both sides for a verdict. ` +
    `Each test's share of the days it needs: ${ps.map((p) => `${Math.round(Math.min(p, 1) * 100)}%`).join(", ")}.`;
  const H = axis + 22;
  return `<svg viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${aria}">${g}</svg>`;
}

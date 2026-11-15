// PhenoAge on the Journey, MARKERS ONLY (owner ruling 2026-11-14). His own phenotypic age is never built into a page:
// Levine's formula is linear in chronological age (0.89 years per year) and its nine inputs are public lab values, so
// the figure at any precision — a rounded year, a five-year band, a younger/older flag — is his age, or a bound on it
// that narrows with every draw (tests/test_age_inversion.py is the measurement). What the snapshot carries instead is
// the reference line: what the same nine markers return for a person of each reference age. Everything here is a pure
// function of that — nothing on this page knows where he sits on the line.
import { num } from "./format.js";

const MONO = `font-family="IBM Plex Mono,monospace" font-size="12.5"`;
const INK = "#121212";
const MUTED = "#5C5C58";
const COBALT = "#1B3FD6";
const RULE = "#E3E3DD";

const yrs = (v) => `${num(Math.abs(v), 1)} ${Math.abs(v) === 1 ? "year" : "years"}`;

/** The offsets across the reference span, in words: "2.1 to 5.4 years younger than the calendar". Null when unusable. */
export function offsetWords(ref) {
  if (!ref || typeof ref.offset_low !== "number" || typeof ref.offset_high !== "number") return null;
  const lo = ref.offset_low;
  const hi = ref.offset_high;
  if (hi <= 0 && lo < 0) return hi === lo ? `${yrs(lo)} younger than the calendar` : `${num(Math.abs(hi), 1)} to ${yrs(lo)} younger than the calendar`;
  if (lo >= 0 && hi > 0) return hi === lo ? `${yrs(hi)} older than the calendar` : `${num(lo, 1)} to ${yrs(hi)} older than the calendar`;
  if (lo === 0 && hi === 0) return "level with the calendar";
  return `between ${yrs(lo)} younger and ${yrs(hi)} older than the calendar`;
}

/** The span the reference points cover, in words: "30 to 60". */
export function spanWords(ref) {
  const pts = (ref && ref.points) || [];
  if (pts.length < 2) return null;
  return `${num(pts[0].at_years, 0)} to ${num(pts[pts.length - 1].at_years, 0)}`;
}

/**
 * The reference line: x = a reference person's age, y = what the formula returns for that person with these nine
 * markers; the dashed diagonal is "same as the calendar". Each point carries its offset. Native-size SVG (labels stay
 * 12.5px on a phone). Null when fewer than two points are served.
 */
export function referenceFigure(ref, { width = 300 } = {}) {
  const pts = ((ref && ref.points) || []).filter((p) => [p.at_years, p.reads_years, p.offset_years].every((v) => typeof v === "number"));
  if (pts.length < 2) return null;
  const x0 = pts[0].at_years;
  const x1 = pts[pts.length - 1].at_years;
  const ys = pts.flatMap((p) => [p.reads_years, p.at_years]);
  const y0 = Math.floor((Math.min(...ys) - 4) / 10) * 10;
  const y1 = Math.ceil((Math.max(...ys) + 4) / 10) * 10;
  const L = 34;
  const R = 14;
  const T = 10;
  const H = 190;
  const B = 30;
  const x = (v) => L + ((v - x0) / (x1 - x0)) * (width - L - R);
  const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  let g = "";
  for (let v = y0; v <= y1; v += 10) {
    g += `<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${width - R}" y2="${y(v).toFixed(1)}" stroke="${RULE}" stroke-width="1"/>`;
    g += `<text x="${L - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" ${MONO} fill="${MUTED}">${v}</text>`;
  }
  for (const p of pts) g += `<text x="${x(p.at_years).toFixed(1)}" y="${H - 10}" text-anchor="middle" ${MONO} fill="${MUTED}">${num(p.at_years, 0)}</text>`;
  // the calendar: a person whose markers read exactly their age
  g += `<line x1="${x(x0).toFixed(1)}" y1="${y(x0).toFixed(1)}" x2="${x(x1).toFixed(1)}" y2="${y(x1).toFixed(1)}" stroke="${INK}" stroke-width="1.5" stroke-dasharray="4 4"/>`;
  g += `<polyline fill="none" stroke="${COBALT}" stroke-width="2.5" points="${pts.map((p) => `${x(p.at_years).toFixed(1)},${y(p.reads_years).toFixed(1)}`).join(" ")}"/>`;
  for (const p of pts) {
    const above = p.offset_years > 0;
    g += `<circle cx="${x(p.at_years).toFixed(1)}" cy="${y(p.reads_years).toFixed(1)}" r="4" fill="${COBALT}"/>`;
    g += `<text x="${x(p.at_years).toFixed(1)}" y="${(y(p.reads_years) + (above ? -9 : 18)).toFixed(1)}" text-anchor="${p === pts[0] ? "start" : p === pts[pts.length - 1] ? "end" : "middle"}" ${MONO} fill="${COBALT}">${p.offset_years > 0 ? "+" : p.offset_years < 0 ? "−" : ""}${num(Math.abs(p.offset_years), 1)}</text>`;
  }
  const aria =
    `What the formula returns for a person of each reference age with these nine markers: ` +
    pts.map((p) => `at ${num(p.at_years, 0)}, ${num(p.reads_years, 1)}`).join("; ") +
    `. The dashed line is the calendar. His own position on the line is not shown.`;
  return `<svg viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${aria}">${g}</svg>`;
}

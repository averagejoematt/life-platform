/*
  evidence_bar.js — the Evidence Bar (#1372): a chess-eval-style micro-widget that
  makes one claim's evidential strength legible at a glance — n / effective n /
  CI width / FDR status, composed into a single 0..1 fill.

  HONESTY CONTRACT (ADR-105 + the confidence grammar, DESIGN_SYSTEM_V5 §7a):
  • The value is SERVED — stats_core.correlation_evidence(), deterministic and
    unit-tested. Nothing is graded or invented client-side; a claim without an
    `evidence` object renders NOTHING (honest absence), never a guessed bar.
  • LOW confidence draws a point marker at the score, never a filled band — the
    same "no fabricated spread" rule the fan/whisker/nDots primitives follow.
  • One hue (ember) via the cf-* classes; opacity/treatment carry the message.
  • The two-line explainer is written for the newcomer who has never opened
    /method/ — hover or tap (the wrapper is focusable; the tip shows on
    hover/focus via CSS alone, no wiring required).
*/
import { esc } from "/assets/js/evidence_shared.js";

const W = 76;
const H = 8;

const _fmtR = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}`;

// One claim's Evidence Bar. `ev` is the served evidence object
// ({score, level, n, n_eff, ci95, fdr_significant}); absent/malformed ⇒ "".
export function evidenceBar(ev) {
  if (!ev || typeof ev !== "object") return "";
  const score = Number(ev.score);
  if (!Number.isFinite(score)) return "";
  const s = Math.max(0, Math.min(1, score));
  const level = ev.level === "high" || ev.level === "medium" ? ev.level : "low";
  const cls = level === "high" ? "cf-high" : level === "medium" ? "cf-med" : "cf-low";
  const n = Math.max(0, Math.round(Number(ev.n) || 0));
  const nEff = Number(ev.n_eff);
  const effDiffers = Number.isFinite(nEff) && Math.round(nEff) !== n;
  const ci = Array.isArray(ev.ci95) && ev.ci95.length === 2 && ev.ci95.every((v) => Number.isFinite(Number(v)))
    ? ev.ci95.map(Number)
    : null;
  const fdr = ev.fdr_significant === true ? true : ev.fdr_significant === false ? false : null;

  // Line 1 — what this claim actually rests on. Served facts only, never authored.
  const facts = [
    `${n} overlapping day${n === 1 ? "" : "s"} of real data${effDiffers ? ` (worth ~${Math.round(nEff)} after day-to-day carry-over)` : ""}`,
    ci
      ? `the 95% range on the effect is ${_fmtR(ci[0])} to ${_fmtR(ci[1])}${ci[0] <= 0 && ci[1] >= 0 ? " — it crosses zero, so even the direction isn't settled" : ""}`
      : "too few days for an honest range yet",
    fdr === true ? "it survived the false-discovery check" : fdr === false ? "it did not survive the false-discovery check" : "the false-discovery check hasn't run on it",
  ].join("; ");
  // Line 2 — how to read the bar, for someone who has never opened /method/.
  const how = level === "low"
    ? "Too little data for a filled bar yet — the mark is the computed score, and it moves as days accrue. Computed from the data, never hand-graded."
    : "Fuller bar = more days behind the claim, a tighter range, and a passed false-discovery check. Computed from the data, never hand-graded.";

  const xs = (s * W).toFixed(1);
  // LOW ⇒ a point marker at the score, never a filled band (the grammar's rule).
  const mark = level === "low"
    ? `<line class="evb-pt" x1="${xs}" x2="${xs}" y1="0" y2="${H}"/>`
    : `<rect class="evb-fill" x="0" y="0" width="${xs}" height="${H}" rx="2"/>`;
  const svg = `<svg class="evb-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false">` +
    `<rect class="evb-rail" x="0" y="0" width="${W}" height="${H}" rx="2"/>${mark}</svg>`;
  const aria = `Evidence strength ${s.toFixed(2)} of 1. This claim rests on ${facts}.`;
  return `<span class="evb ${cls}" tabindex="0" role="img" aria-label="${esc(aria)}">` +
    svg +
    `<span class="evb-score mono">${s.toFixed(2)}</span>` +
    `<span class="evb-tip" role="tooltip"><span class="evb-tip-l">This claim rests on ${esc(facts)}.</span>` +
    `<span class="evb-tip-l">${esc(how)}</span></span></span>`;
}

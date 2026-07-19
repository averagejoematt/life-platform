// tests/js/evidence_bar.test.mjs — unit tests for the Evidence Bar micro-widget
// (#1372, site/assets/js/evidence_bar.js). The widget is the per-claim rigor
// readout on the correlations/discoveries claim cards; its honesty contract is
// load-bearing: it must render NOTHING without a served evidence object (never
// invent a bar client-side), and a LOW-confidence claim must draw a point mark,
// never a filled band (DESIGN_SYSTEM_V5 §7a — no fabricated spread).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
// Dynamic import (not static): evidence_bar.js itself imports "/assets/js/…"
// specifiers, which only resolve AFTER support/loader.mjs has registered the
// site resolver — a static import here would link before registration runs
// (the same reason scripts/import_site_js_graph.mjs uses dynamic import()).
const { evidenceBar } = await import("../../site/assets/js/evidence_bar.js");

const HIGH = { score: 0.71, level: "high", n: 34, n_eff: 28.4, ci95: [0.21, 0.62], ci_width: 0.41, ci_excludes_zero: true, fdr_significant: true };

test("no served evidence ⇒ renders NOTHING — never a client-side invention", () => {
  assert.equal(evidenceBar(null), "");
  assert.equal(evidenceBar(undefined), "");
  assert.equal(evidenceBar({}), "");
  assert.equal(evidenceBar({ score: "not a number" }), "");
  assert.equal(evidenceBar("0.7"), "");
});

test("high level ⇒ a filled band tinted by the confidence grammar", () => {
  const html = evidenceBar(HIGH);
  assert.match(html, /class="evb cf-high"/);
  assert.match(html, /<rect class="evb-fill"/);
  assert.doesNotMatch(html, /evb-pt/); // band, not point
});

test("medium level ⇒ band with the muted cf-med tint", () => {
  const html = evidenceBar({ ...HIGH, level: "medium" });
  assert.match(html, /class="evb cf-med"/);
  assert.match(html, /<rect class="evb-fill"/);
});

test("LOW ⇒ a point mark at the score, never a filled band (the grammar's rule)", () => {
  const html = evidenceBar({ score: 0.18, level: "low", n: 5, n_eff: 5, ci95: null, fdr_significant: null });
  assert.match(html, /class="evb cf-low"/);
  assert.match(html, /<line class="evb-pt"/);
  assert.doesNotMatch(html, /evb-fill/);
});

test("an unknown/garbage level degrades to LOW (the conservative read), not high", () => {
  const html = evidenceBar({ ...HIGH, level: "amazing" });
  assert.match(html, /class="evb cf-low"/);
  assert.match(html, /evb-pt/);
});

test("fill width is proportional to the score and the score is clamped to [0,1]", () => {
  const half = evidenceBar({ ...HIGH, score: 0.5 });
  assert.match(half, /width="38\.0"/); // 0.5 × 76 viewBox units
  const over = evidenceBar({ ...HIGH, score: 7 });
  assert.match(over, /width="76\.0"/); // clamped to full rail
  assert.match(over, /1\.00/); // shown score clamps too
});

test("explainer line 1 carries the real facts — n, effective n, CI range, FDR pass", () => {
  const html = evidenceBar(HIGH);
  assert.match(html, /34 overlapping days of real data/);
  assert.match(html, /worth ~28 after day-to-day carry-over/);
  assert.match(html, /\+0\.21 to \+0\.62/);
  assert.match(html, /survived the false-discovery check/);
});

test("CI crossing zero says so plainly; a missing CI is named, never fabricated", () => {
  const crossing = evidenceBar({ ...HIGH, ci95: [-0.1, 0.4] });
  assert.match(crossing, /crosses zero/);
  const noCi = evidenceBar({ ...HIGH, ci95: null });
  assert.match(noCi, /too few days for an honest range yet/);
  assert.doesNotMatch(noCi, /95% range on the effect/);
});

test("FDR false and FDR not-run read differently — 'failed' is never implied by absence", () => {
  const failed = evidenceBar({ ...HIGH, fdr_significant: false });
  assert.match(failed, /did not survive the false-discovery check/);
  const unchecked = evidenceBar({ ...HIGH, fdr_significant: null });
  assert.match(unchecked, /false-discovery check hasn't run/);
});

test("two explainer lines, and the wrapper is focusable for tap/keyboard", () => {
  const html = evidenceBar(HIGH);
  assert.equal((html.match(/evb-tip-l/g) || []).length, 2);
  assert.match(html, /tabindex="0"/);
  assert.match(html, /role="img"/);
  assert.match(html, /aria-label="Evidence strength 0\.71 of 1\./);
});

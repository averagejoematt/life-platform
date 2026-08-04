// tests/js/evidence_character_provenance.test.mjs — #1982 (ADR-105 target
// provenance). /api/character_config serves `target_provenance` on every
// derivable character component (personal_baselines.derive_component_target)
// but the "What feeds each pillar" component rows filtered it out — it's an
// OBJECT, and the row-builder in evidence_character.js only strings scalar
// fields together. A personal-variance band (n-backed, p75 of the reader's
// own 365-day distribution) rendered identically to an authored commitment.
// chProvenance(cv) lives in evidence_character_provenance.js — split out of
// evidence_character.js so it's DOM-free and importable here directly
// (evidence_character.js's own import graph pulls share.js, which touches
// `window` at import time — the evidence_receipts.js precedent).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
const { chProvenance } = await import("../../site/assets/js/evidence_character_provenance.js");

test("no target_provenance field ⇒ renders nothing (never a fabricated chip)", () => {
  assert.equal(chProvenance({}), "");
  assert.equal(chProvenance({ weight: 0.25, target_hours: 8 }), "");
  assert.equal(chProvenance(null), "");
  assert.equal(chProvenance(undefined), "");
});

test("personal band ⇒ declares source, method, window, and n (the live payload shape)", () => {
  const cv = {
    weight: 0.25,
    target_hours: 8.48,
    target_provenance: { source: "personal", method: "percentile_band_p75", window_days: 365, n: 341, metric: "sleep_duration_hours" },
  };
  const html = chProvenance(cv);
  assert.match(html, /class="ch-comp-prov is-personal"/);
  assert.match(html, /personal/);
  assert.match(html, /p75/); // the percentile method, prefix stripped
  assert.match(html, /365d/); // the window
  assert.match(html, /n=341/); // the sample size — the exact honesty payload the issue names
});

test("clamped personal band ⇒ says so (a guardrail-clamped target is still labeled personal, but flagged)", () => {
  const cv = { target_provenance: { source: "personal", method: "percentile_band_p75", window_days: 365, n: 341, clamped: true, bounds: [0.1, 0.25] } };
  const html = chProvenance(cv);
  assert.match(html, /is-personal/);
  assert.match(html, /clamped/);
});

test("population-prior fallback ⇒ renders the authored-commitment label, distinct styling", () => {
  const cv = { target_provenance: { source: "population_prior", label: "population prior, n<30", n: 4, metric: "rem_sleep_fraction" } };
  const html = chProvenance(cv);
  assert.match(html, /class="ch-comp-prov is-prior"/);
  assert.match(html, /population prior, n&lt;30/);
  assert.doesNotMatch(html, /is-personal/);
});

test("population-prior with no label ⇒ falls back to the honest generic phrase, never blank", () => {
  const html = chProvenance({ target_provenance: { source: "population_prior", n: 0 } });
  assert.match(html, /authored commitment/);
});

test("output is escaped — a hostile/garbled label can't break out of the chip", () => {
  const html = chProvenance({ target_provenance: { source: "population_prior", label: "<script>alert(1)</script>" } });
  assert.doesNotMatch(html, /<script>/);
});

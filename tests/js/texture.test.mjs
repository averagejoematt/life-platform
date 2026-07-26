// tests/js/texture.test.mjs — unit tests for the editorial texture layer
// (site/assets/js/texture.js, #1471). The load-bearing claims: determinism
// (same seed → byte-identical SVG, forever — the same contract the coach
// sigils carry), the data-derived bead count (a season banner's beads ARE the
// real attempt number, capped, never invented), the decorative contract
// (aria-hidden, no <text> so the §10.5 SVG type floor has nothing to police),
// and attribute-escape safety on the cls passthrough.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// Dynamic import, not static: texture.js itself imports "/assets/js/sigils.js"
// (root-relative), and a STATIC import here would resolve the whole graph
// before the loader registration above takes effect (the
// reference_site_js_test_and_build_pairs gotcha). await import() defers graph
// resolution until the loader is registered.
const { ruleBand, seasonBand } = await import("../../site/assets/js/texture.js");

test("ruleBand — deterministic: same seed → byte-identical SVG; different seed → different SVG", () => {
  assert.equal(ruleBand("the-story"), ruleBand("the-story"));
  assert.equal(ruleBand("chronicle:2026-07-19"), ruleBand("chronicle:2026-07-19"));
  assert.notEqual(ruleBand("the-story"), ruleBand("chronicle:2026-07-19"));
});

test("ruleBand — decorative contract: aria-hidden root, no <text> (nothing for the SVG type floor)", () => {
  const svg = ruleBand("x");
  assert.match(svg, /aria-hidden="true"/);
  assert.match(svg, /focusable="false"/);
  assert.ok(!svg.includes("<text"), "texture must carry no SVG text — it is texture, not data labels");
});

test("ruleBand — speaks the sigil stroke grammar (ring/tick/node classes + pathLength draw-in)", () => {
  const svg = ruleBand("x");
  assert.match(svg, /class="sigil-ring"/);
  assert.match(svg, /class="sigil-tick"/);
  assert.match(svg, /class="sigil-node"/);
  assert.match(svg, /pathLength="1"/);
  assert.match(svg, /stroke="currentColor"/);
});

test("ruleBand — no emphasis → no ember beads; emphasis renders exactly that many", () => {
  assert.equal((ruleBand("x").match(/art-count/g) || []).length, 0);
  assert.equal((ruleBand("x", { emphasis: 3 }).match(/art-count/g) || []).length, 3);
});

test("ruleBand — cls is escaped into the attribute, never raw markup", () => {
  const svg = ruleBand("x", { cls: '"><script>alert(1)</script>' });
  assert.ok(!svg.includes("<script"), "cls must not break out of the class attribute");
});

test("seasonBand — the beads ARE the attempt number (cycle 7 → exactly 7 ember beads)", () => {
  assert.equal((seasonBand(7).match(/art-count/g) || []).length, 7);
  assert.equal((seasonBand(1).match(/art-count/g) || []).length, 1);
});

test("seasonBand — the count is capped at 24 (a long record stays texture, not a wall)", () => {
  assert.equal((seasonBand(99).match(/art-count/g) || []).length, 24);
});

test("seasonBand — an invalid/absent cycle renders honestly bead-less, never a fabricated count", () => {
  for (const bad of [null, undefined, 0, -3, "not-a-number", NaN]) {
    assert.equal((seasonBand(bad).match(/art-count/g) || []).length, 0, `cycle=${String(bad)}`);
  }
});

test("seasonBand — deterministic per cycle, and a richer seed changes texture but not the count", () => {
  assert.equal(seasonBand(10), seasonBand(10));
  const a = seasonBand(10, { seed: "attempt:10:2026-07-22" });
  const b = seasonBand(10, { seed: "attempt:10:2026-01-01" });
  assert.equal(a, seasonBand(10, { seed: "attempt:10:2026-07-22" })); // still byte-stable
  assert.notEqual(a, b); // genesis is part of the season's fingerprint
  assert.equal((a.match(/art-count/g) || []).length, 10);
  assert.equal((b.match(/art-count/g) || []).length, 10);
});

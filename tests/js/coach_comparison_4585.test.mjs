// tests/js/coach_comparison_4585.test.mjs — #4585 (epic #4580 rule 3): the one line a page
// prints beside a coach count. It prints the served sentence verbatim (escaped) and says an
// absent block as an absence — it never invents a verdict and never drops the line.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { coachComparison, comparisonText } = await import("../../site/assets/js/coach_comparison.js");

test("prints the served sentence, escaped, with provenance", () => {
  const cmp = { sentence: "Across 96 checked calls, so far they do not beat a simple guess." };
  assert.equal(comparisonText(cmp), cmp.sentence);
  const html = coachComparison(cmp, { cls: "v7c-note", src: "api_calibration.comparison.sentence" });
  assert.match(html, /^<p class="v7c-note" data-coach-comparison data-src="api_calibration\.comparison\.sentence">Across 96 checked calls/);
  assert.match(coachComparison({ sentence: "a <b> & c" }), /a &lt;b&gt; &amp; c/);
});

test("an absent or empty block is said as an absence, never as a verdict", () => {
  for (const cmp of [null, undefined, {}, { sentence: "" }, { sentence: 3 }]) {
    const t = comparisonText(cmp);
    assert.match(t, /not available right now/);
    assert.doesNotMatch(t, /beat|better|worse/);
  }
});

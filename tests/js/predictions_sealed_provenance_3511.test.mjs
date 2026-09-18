// #3511 box 4 — the prediction ledger renders SEALED vs UNSEALED.
//
// `/api/predictions` served `pre_registered_at` but not the `pre_registered` flag, and
// the table printed nothing at all about provenance: a bet frozen before Day 1 and a
// call the coach logged on Day 9 rendered as identical rows. The seal block above the
// table says a pre-registration exists; no row said whether IT was in it.
//
// The flag is the thing rendered, not a guess from the nullable timestamp — that
// distinction is the third test here, and it is the one that matters: `pre_registered_at`
// is absent on any sealed row written before #3480 started stamping it, so a renderer
// keyed on the timestamp would silently mislabel a sealed bet "in-cycle".
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const ei = await import("../../site/assets/js/evidence_intelligence.js");
const base = { overall: { total: 1, pending: 1 } };
const row = (extra) => ({ coach_id: "sleep", coach_name: "Dr. X", text: "sleep will rise", status: "pending", date: "2026-09-06", ...extra });

// Match the BADGE, not the word: the explanatory note under the table also contains
// "sealed" and "in-cycle", so a bare /sealed/ would pass on every render.
const SEALED = /<span class="rd-badge rd-badge-live" title="pre-registered[^"]*">sealed<\/span>/;
const IN_CYCLE = /<span class="rd-badge" title="logged by the coach[^"]*">in-cycle<\/span>/;

test("a pre_registered row is labelled sealed", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({ pre_registered: true, pre_registered_at: "2026-09-06T02:13:38+00:00" })] });
  assert.match(html, SEALED);
  assert.doesNotMatch(html, IN_CYCLE);
});

test("a row without the flag is labelled in-cycle", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({})] });
  assert.match(html, IN_CYCLE);
  assert.doesNotMatch(html, SEALED);
});

test("the label reads the FLAG, not the timestamp: pre_registered_at alone is not a seal", () => {
  // The live shape this protects against: #3480 added the instant, #3511 added the flag.
  // A row carrying only the instant is not evidence of sealing, and a sealed row that
  // predates the instant must still read "sealed".
  const onlyInstant = ei.renderPredictions({ ...base, predictions: [row({ pre_registered_at: "2026-09-06T02:13:38+00:00" })] });
  assert.match(onlyInstant, IN_CYCLE);
  assert.doesNotMatch(onlyInstant, SEALED);
  const onlyFlag = ei.renderPredictions({ ...base, predictions: [row({ pre_registered: true })] });
  assert.match(onlyFlag, SEALED);
});

test("the header row grew the provenance column and the note defines both words", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({ pre_registered: true })] });
  assert.match(html, /<th>verdict<\/th><th>provenance<\/th><th>made<\/th>/);
  assert.match(html, /<strong>sealed<\/strong> = pre-registered before Day 1/);
  assert.match(html, /<strong>in-cycle<\/strong> = logged by the coach during the cycle/);
});

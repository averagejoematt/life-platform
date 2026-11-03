// tests/js/summary_provenance.test.mjs — owner ruling 2026-11-03 + owner review of #5644: a coach summary shows its
// as-of and what it was built from in one concise line; the specific corrections (dates, grades, registered
// explanation, the call on the ledger) are on demand behind "What changed"; a verbatim trail entry keeps its words.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { provenanceLine, correctionLines, summaryProvenanceHTML, trailCorrectionsHTML, dayWords, asOfWords, ledgerHref } = await import(
  "../../site/assets/js/summary_provenance.js"
);

const NOTE = { prediction_id: null, coach_id: null, original_status: "refuted", corrected_status: "expired", corrected_at: "2026-11-03T18:55:07Z", explanation: "A registered explanation." };
const superseded = {
  position_summary: "This coach's earlier assessment is being updated following a prediction correction.",
  summary_state: "superseded_by_correction",
  summary_as_of: "2026-11-03T20:00:00Z",
  derived_from: { built_from: "ledger_records", as_of: "2026-11-03T20:00:00Z", superseded_read_as_of: "2026-11-02T18:03:20Z", predictions: [], predictions_not_public: 1 },
  summary_corrections: [NOTE],
};

test("a superseded read: one concise line, no grades or rule words in it", () => {
  const line = provenanceLine(superseded);
  assert.equal(line, "As of 3 November 2026 · from the ledger's records.");
  assert.ok(!/wrong|could not be checked|re-graded/.test(line));
});

test("the specifics are on demand: dated, in ledger words, the registered explanation verbatim", () => {
  const h = summaryProvenanceHTML(superseded);
  assert.ok(h.includes("<details") && h.includes("<summary>What changed</summary>"));
  const [n] = correctionLines([NOTE]);
  assert.equal(n.text, "3 November 2026, 18:55 UTC: a call graded wrong is now could not be checked. A registered explanation.");
  assert.equal(n.href, null, "a call the public ledger withholds is never linked");
  assert.equal(ledgerHref({ prediction_id: "p1", coach_id: "mind" }), "/system/ledger/mind-p1/");
});

test("a current read names its build day and its calls; an API without the fields renders nothing", () => {
  const cur = { summary_state: "current", summary_as_of: "2026-11-02T18:00:00Z", derived_from: { built_from: "coach_read", predictions: ["a", "b"], predictions_not_public: 1 } };
  assert.equal(provenanceLine(cur), "Written 2 November 2026 · the coach's read, built from 3 calls on the ledger.");
  assert.equal(summaryProvenanceHTML({ position_summary: "x" }), "");
});

test("escaped, and the inline form is one span — no disclosure, no link inside a button", () => {
  const evil = { ...superseded, summary_corrections: [{ ...NOTE, prediction_id: "p1", coach_id: "mind", explanation: "<script>x</script>" }] };
  const h = summaryProvenanceHTML(evil);
  assert.ok(!h.includes("<script>") && h.includes('href="/system/ledger/mind-p1/"'));
  const inline = summaryProvenanceHTML(evil, { inline: true });
  assert.ok(!/<p |<a |<details/.test(inline));
});

test("a trail entry: a concise dated note, the specifics behind What changed; no correction recorded → the ledger's grade", () => {
  const h = trailCorrectionsHTML({ summary: "I was wrong about it.", grade_corrections: [NOTE] });
  assert.ok(h.startsWith('<p class="ce-correction correction" role="note">Corrected 3 November 2026: the prediction this refers to has since been re-graded.</p>'));
  assert.ok(h.includes("What changed"));
  const g = trailCorrectionsHTML({ summary: "x", grade_corrections: [{ ...NOTE, original_status: null, corrected_at: null, corrected_status: "observational" }] });
  assert.ok(g.includes("The ledger grades the prediction this refers to differently.") && g.includes("as not graded"));
  assert.equal(trailCorrectionsHTML({ summary: "x" }), "");
  assert.equal(dayWords("not a date"), "");
  assert.equal(asOfWords("2026-11-01"), "1 November 2026");
});

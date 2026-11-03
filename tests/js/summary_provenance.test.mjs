// tests/js/summary_provenance.test.mjs — owner ruling 2026-11-03: a coach summary shows its as-of, what it was
// built from, and the dated corrections beside it; a verbatim trail entry keeps its words and gains a dated note.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { provenanceLine, correctionLines, summaryProvenanceHTML, trailCorrectionsHTML, dayWords } = await import("../../site/assets/js/summary_provenance.js");

const superseded = {
  position_summary: "My read of 2 November 2026 is withheld until it is rewritten: on 3 November 2026 one of my calls was re-graded from wrong to could not be checked.",
  summary_state: "superseded_by_correction",
  summary_as_of: "2026-11-03T20:00:00+00:00",
  derived_from: { built_from: "ledger_records", as_of: "2026-11-03T20:00:00+00:00", superseded_read_as_of: "2026-11-02T18:03:20+00:00", predictions: [], predictions_not_public: 1 },
  summary_corrections: [
    { prediction_id: null, original_status: "refuted", corrected_status: "expired", corrected_at: "2026-11-03T18:55:07Z", explanation: "A registered explanation." },
  ],
};

test("a superseded read says it is built from the records, as of when, and which read waits", () => {
  assert.equal(provenanceLine(superseded), "Built from the ledger's records, as of 3 November 2026 · the read of 2 November 2026 waits to be rewritten.");
});

test("a correction line is dated, in ledger words, and carries the registered explanation verbatim", () => {
  const [n] = correctionLines(superseded, (id) => `/system/ledger/mind-${id}/`);
  assert.equal(n.text, "Corrected 3 November 2026: a call graded wrong is now could not be checked. A registered explanation.");
  assert.equal(n.href, null, "a call the public ledger withholds is never linked");
});

test("a current read names its build day and its calls; an API without the fields renders nothing", () => {
  const cur = { summary_state: "current", summary_as_of: "2026-11-02T18:00:00Z", derived_from: { built_from: "coach_read", predictions: ["a", "b"], predictions_not_public: 1 } };
  assert.equal(provenanceLine(cur), "Written 2 November 2026 · the coach's read, built from 3 calls on the ledger.");
  assert.equal(summaryProvenanceHTML({ position_summary: "x" }), "");
});

test("the HTML escapes every value, and the inline form is phrasing content only", () => {
  const evil = { ...superseded, summary_corrections: [{ ...superseded.summary_corrections[0], prediction_id: "p1", explanation: "<script>x</script>" }] };
  const h = summaryProvenanceHTML(evil, { ledgerHref: (id) => `/system/ledger/mind-${id}/` });
  assert.ok(!h.includes("<script>"));
  assert.ok(h.includes('href="/system/ledger/mind-p1/"'));
  const inline = summaryProvenanceHTML(evil, { inline: true, ledgerHref: (id) => `/x/${id}` });
  assert.ok(!/<p |<a /.test(inline), "no block or link inside a button");
});

test("a trail entry gains a dated note; with no recorded correction it states the ledger's grade", () => {
  const h = trailCorrectionsHTML({ summary: "I was wrong about it.", grade_corrections: [{ original_status: null, corrected_status: "observational" }] });
  assert.ok(h.includes("The ledger holds the call this names as not graded."));
  assert.equal(trailCorrectionsHTML({ summary: "x" }), "");
  assert.equal(dayWords("not a date"), "");
});

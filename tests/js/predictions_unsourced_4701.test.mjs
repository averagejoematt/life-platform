// #4701 — the prediction ledger never prints a blank quote.
//
// /api/predictions now applies the #4673 sourcing hold: a call whose words rest on a sensor
// that had sent no reading by the day it was made is served with `text: ""` and an
// `unsourced` note. The ledger table printed `esc(p.text)` into the call column, so a held
// row would have rendered an empty cell beside its verdict. It prints the note's sentence.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const ei = await import("../../site/assets/js/evidence_intelligence.js");
const base = { overall: { total: 2, refuted: 2 } };
const SENTENCE = "Not quoted: this was said on September 13 and rests on his glucose sensor, which had sent no reading since August 27.";
const row = (extra) => ({ coach_id: "physical", coach_name: "Dr. Y", text: "Recovery will rise", status: "refuted", date: "2026-09-13", ...extra });
const held = row({ text: "", unsourced: { reason: "no sensor since 2026-08-27", said_on: "2026-09-13", last_seen: "2026-08-27", text: SENTENCE } });

test("a held row prints the unsourced sentence in the call column, never a blank quote", () => {
  const html = ei.renderPredictions({ ...base, predictions: [held] });
  assert.match(html, /<td><span class="rd-unit" data-unsourced>Not quoted: this was said on September 13/);
  assert.doesNotMatch(html, /<td><\/td>/, "an empty call cell is the defect");
  assert.match(html, /rd-range">2026-09-13<\/td>/, "the row keeps its date");
});

test("control: a quoted row prints its words and no unsourced marker", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({})] });
  assert.match(html, /<td>Recovery will rise<\/td>/);
  assert.doesNotMatch(html, /data-unsourced/);
});

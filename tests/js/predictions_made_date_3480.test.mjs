// #3480 — the prediction ledger's "made" column shows when a claim was FROZEN, and
// says which day it grades FROM when that differs (a pre-registered claim's `date`
// is genesis by construction; on 2026-09-04 the page printed "made 2026-09-05").
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const ei = await import("../../site/assets/js/evidence_intelligence.js");
const base = { overall: { total: 1, pending: 1 } };
const row = (extra) => ({ coach_id: "sleep", coach_name: "Dr. X", text: "sleep will rise", status: "pending", date: "2026-09-05", ...extra });

test("pre-registered claim: made = freeze date, effective genesis shown beside it", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({ pre_registered_at: "2026-09-04T16:53:28+00:00" })] });
  assert.match(html, /2026-09-04 <span class="rd-unit">· from 2026-09-05<\/span>/);
  assert.doesNotMatch(html, /rd-range">2026-09-05</);
});

test("in-cycle coach call (no freeze instant): made = date, no 'from' suffix", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({})] });
  assert.match(html, /rd-range">2026-09-05<\/td>/);
  assert.doesNotMatch(html, /· from/);
});

test("freeze on genesis day itself: one date, no suffix (negative control on the differ-check)", () => {
  const html = ei.renderPredictions({ ...base, predictions: [row({ pre_registered_at: "2026-09-05T07:10:00+00:00" })] });
  assert.match(html, /rd-range">2026-09-05<\/td>/);
  assert.doesNotMatch(html, /· from/);
});

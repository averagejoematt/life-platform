// The four parts of the experiment (owner rulings 2026-11-15/16): one producer of the four figures for the front page
// and the strip on the Story, Data and System doors. Every figure is a served one; a missing one is null, never a guess.
import { test } from "node:test";
import assert from "node:assert/strict";
import { AI_STATUS, bodyChange, fourParts, labVerdicts, measuredDimensions } from "../src/lib/standing.js";

const day = (date, value, gap = false) => ({ date, value, gap, present: value != null });
const weight = { days: [day("2026-09-05", 330), day("2026-09-06", 327.3), day("2026-09-07", null), day("2026-09-08", 320), day("2026-09-09", 318.7)] };

test("the body is the weight series' own change since the start, with its days and readings", () => {
  assert.deepEqual(bodyChange(weight, "2026-09-06", 327.3), { lost: 318.7 - 327.3, days: 4, readings: 3 });
  assert.equal(bodyChange({ days: [day("2026-09-06", null)] }, "2026-09-06", 327.3), null);
  assert.equal(bodyChange(null, "2026-09-06", 327.3), null);
});

test("the behaviour counts the Laboratory's live tests and those with a verdict", () => {
  const lab = { state: "ok", lab_tests: [{ status: "open", verdict: { result: "supported" } }, { status: "open", verdict: "inconclusive" }, { status: "open" }, { status: "archived", verdict: "supported" }] };
  assert.deepEqual(labVerdicts(lab), { open: 3, decided: 1 });
  assert.equal(labVerdicts({ state: "absent" }), null);
  assert.equal(labVerdicts(null), null);
});

test("the life counts only dimensions a public series measures", () => {
  const series = { weight_lbs: weight, sleep_duration_hours: { days: [day("2026-09-06", 7.2)] }, hrv: { days: [day("2026-09-06", null)] } };
  assert.equal(measuredDimensions(series), 2);
  assert.equal(measuredDimensions({}), 0);
});

test("the four parts carry served figures, the producer's verdict as a status, and null where nothing is served", () => {
  const lead = { k: 37, n: 72, baseline: { right: 39 }, sign: { verdict: "no_clear_difference" } };
  const parts = fourParts({ body: { lost: -38.6, days: 71, readings: 60 }, lab: { open: 5, decided: 1 }, measured: 3, lead });
  assert.deepEqual(parts.map((p) => [p.id, p.value, p.status]), [
    ["body", "38.6 lb", "measured"],
    ["behaviour", "1 of 5", "being tested"],
    ["life", "3 of 6", "not established"],
    ["ai", "37 v 39", "no advantage shown"],
  ]);
  const none = fourParts({ body: null, lab: null, measured: 0, lead: null });
  assert.deepEqual(none.map((p) => p.value), [null, null, "0 of 6", null]);
  assert.equal(none[3].status, "being checked");
  // the AI's status follows the producer's verdict in both directions — never a fixed word
  for (const [verdict, words] of Object.entries(AI_STATUS)) {
    assert.equal(fourParts({ body: null, lab: null, measured: 3, lead: { ...lead, sign: { verdict } } })[3].status, words);
  }
  assert.equal(fourParts({ body: { lost: 2, days: 3, readings: 3 }, lab: null, measured: 3, lead: null })[0].short, "heavier");
});

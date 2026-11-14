// tests/js/sleep_mind_labels_5953_5956.test.mjs — labels that name the number beside them.
//   #5953 item 3: `recovery_night_of` is a stored WAKE date, so the night is the day before; a still-recording mattress
//                 night is marked provisional, never read as final.
//   #5956 item 1: the Mind page's restraint total is a sum over the served timeline window, not "since Day 1".
// Each assertion fails on the code before the fix.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// evidence_sleep.js imports explain.js, which wires itself to window/document at import time (the v7_numbers stub)
if (typeof globalThis.window === "undefined") {
  const noop = () => {};
  globalThis.document = { readyState: "complete", body: {}, addEventListener: noop, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
  globalThis.window = { document: globalThis.document, addEventListener: noop, removeEventListener: noop, requestAnimationFrame: (cb) => setTimeout(cb, 0) };
}
const { sleepFold, nightBeforeWake, stillRecording, mindRestraint } = await import("../../site/assets/js/evidence_sleep.js");

test("the night of a stored wake date is the day before it (month and year boundaries included)", () => {
  assert.equal(nightBeforeWake("2026-11-13"), "2026-11-12");
  assert.equal(nightBeforeWake("2026-12-01T09:00:00Z"), "2026-11-30");
  assert.equal(nightBeforeWake("2027-01-01"), "2026-12-31");
  assert.equal(nightBeforeWake(null), null);
});

test("a borrowed recovery is dated by its night, not its wake date", () => {
  const fold = sleepFold({ sleep_detail: { night_of: "2026-11-13", whoop_hours: 7.3, recovery_score: 61, recovery_night_of: "2026-11-13" } });
  assert.match(fold.text, /from the night of Thursday, November 12/);
  assert.doesNotMatch(fold.text, /from the night of Friday, November 13/);
});

test("a night the vendor flags as still recording is said to be provisional", () => {
  assert.equal(stillRecording({ vendor_incomplete: true }), true);
  assert.equal(stillRecording({ eightsleep: { vendor_incomplete: true } }), true);
  assert.equal(stillRecording({ vendor_incomplete: false, eightsleep: { vendor_incomplete: false } }), false);
  const fold = sleepFold({ sleep_detail: { night_of: "2026-11-13", total_sleep_hours: 4.1, vendor_incomplete: true, figure_scope: { total_sleep_hours_source: "eightsleep" }, eightsleep: { total_sleep_hours: 4.1 } } });
  assert.match(fold.text, /still recording/);
});

test("the restraint total names the window it sums, never 'since Day 1'", () => {
  const tl = Array.from({ length: 28 }, (_, i) => ({ date: new Date(Date.UTC(2026, 9, 16 + i)).toISOString().slice(0, 10), held: 5, total: 6 }));
  const html = mindRestraint([{ holding: true, current_streak: 68 }, { holding: false, current_streak: 0 }], tl);
  assert.match(html, /mr-cum-v num">140</);
  assert.match(html, /restraint-days held in the 28 days from Friday, October 16 to Thursday, November 12/);
  assert.doesNotMatch(html, /since Day 1/);
});

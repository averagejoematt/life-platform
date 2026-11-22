// heldCallWords (2026-11-14): a withheld call in a compact mention reads as its frozen test, never the coach's words.
import assert from "node:assert/strict";
import { test } from "node:test";
import { heldCallWords, readableTest } from "../src/lib/format.js";

test("a withheld call reads as its test, with dates in words and the singular fixed", () => {
  assert.equal(heldCallWords({ claim_withheld: "no_words", grading: { how: "morning recovery score trend down over 1 days" } }), "the test: morning recovery score trend down over 1 day");
  assert.match(heldCallWords({ grading: { how: "weight below 300 by 2026-10-17" } }), /by 17 Oct/);
});

test("no served test → null, so the caller keeps the ledger's one sentence", () => {
  assert.equal(heldCallWords({ claim_withheld: "no_words", grading: { how: null } }), null);
  assert.equal(heldCallWords(null), null);
});

test("an observation has no test: its line reads as itself", () => {
  assert.equal(heldCallWords({ status: "observation", grading: { how: "morning recovery score: an observation, not graded" } }), "morning recovery score: an observation, not graded");
});

test("#6161: a point test on a 0–100 score reads as points, not 'out of 100' twice", () => {
  const p = { claim_withheld: "no_words", grading: { how: "morning recovery score within ±12.49 out of 100 of 65 out of 100 on 10 November 2026" } };
  assert.equal(heldCallWords(p), "the test: morning recovery score within 12.5 points of 65 (out of 100) on 10 November 2026");
  assert.equal(readableTest("within ±12 out of 100 of 59 out of 100"), "within 12 points of 59 (out of 100)");
  assert.equal(readableTest("weight within ±1.5 lb of 290 lb"), "weight within ±1.5 lb of 290 lb", "any other unit is served as written");
});

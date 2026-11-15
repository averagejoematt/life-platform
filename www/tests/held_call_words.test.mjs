// heldCallWords (2026-11-14): a withheld call in a compact mention reads as its frozen test, never the coach's words.
import assert from "node:assert/strict";
import { test } from "node:test";
import { heldCallWords } from "../src/lib/format.js";

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

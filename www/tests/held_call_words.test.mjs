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

// #6224 (public review 2026-11-23): the Week 5 rail and card printed "an observation, not graded" beside "wrong".
test("#6224: a graded yes-or-no bet never reads 'not graded' beside its grade", async () => {
  const { gradingHow } = await import("../src/lib/format.js");
  const bet = { status: "refuted", kind: "yes_no", claim_withheld: "unsourced", grading: { how: "an observation, not graded" } };
  assert.equal(gradingHow(bet), "a yes-or-no bet, graded right or wrong on its question");
  assert.equal(heldCallWords(bet), "a yes-or-no bet, graded right or wrong on its question");
  assert.doesNotMatch(heldCallWords({ ...bet, status: "confirmed" }), /not graded/);
  // a true observation keeps its line; a real test keeps "the test:"
  assert.equal(gradingHow({ status: "observation", grading: { how: "an observation, not graded" } }), "an observation, not graded");
  assert.equal(heldCallWords({ status: "refuted", grading: { how: "weight trend down over 14 days" } }), "the test: weight trend down over 14 days");
});

test("#6224: a grade that changed after first publication says both grades, each dated", async () => {
  const { gradeHistory, gradeTimeLine } = await import("../src/lib/format.js");
  const p = {
    status: "confirmed",
    corrections: [{ original_status: "refuted", original_outcome_date: "2026-10-04", corrected_status: "confirmed", corrected_at: "2026-10-12T16:52:52Z" }],
  };
  assert.deepEqual(gradeHistory(p), { first: "refuted", firstOn: "2026-10-04", now: "confirmed", changedOn: "2026-10-12" });
  const line = gradeTimeLine(p, "2026-10-09", "2026-11-23");
  assert.match(line, /^First graded wrong on 4 October 2026, the grade that stood when this chapter was first published on 9 October 2026\./);
  assert.match(line, /Graded again on 12 October 2026: right, as it stands today \(23 November 2026\)\.$/);
  // regraded BEFORE the chapter was published: no claim about what stood at publication
  assert.doesNotMatch(gradeTimeLine(p, "2026-10-20", "2026-11-23"), /stood when/);
  // never changed (or a correction that kept the grade): no history, no time line
  assert.equal(gradeHistory({ status: "refuted", corrections: [] }), null);
  assert.equal(gradeTimeLine({ status: "refuted", corrections: [{ original_status: "refuted", corrected_status: "refuted" }] }, "2026-10-09", "2026-11-23"), null);
});

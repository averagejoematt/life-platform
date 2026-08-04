// tests/js/chronicle_order_1988.test.mjs — unit tests for the chronicle "newest
// first" comparator (#1988, site/assets/js/chronicle_order.js), consumed by
// story.js's dxEntries() for the Chronicle/Journal master-detail list.
//
// Root cause this pins: story.js previously rendered posts.json's `posts` array
// in whatever order the server manifest happened to deliver, with NO client-side
// sort at all — so a stale or mis-ordered manifest snapshot (the exact #1988 bug
// on the server side) reached the reader unfiltered. This module gives the
// client its own same-date tie-break, keyed off the explicit `sequence` field
// (never array position), so the two sides can't independently drift.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
const { compareChronicleNewestFirst, sortChronicleNewestFirst } = await import("../../site/assets/js/chronicle_order.js");

const PART_I = { title: "Before the Numbers", date: "2026-07-28", week: 0, sequence: 1 };
const PART_II = { title: "The Night Before Everything", date: "2026-08-02", week: 1, sequence: 2 };
const PART_III = { title: "The Plan, On the Record", date: "2026-08-02", week: 0, sequence: 3 };
const WEEK_2 = { title: "The Second Week", date: "2026-08-09", week: 2, sequence: 4 };

test("newest date sorts first, regardless of input order", () => {
  const out = sortChronicleNewestFirst([PART_I, WEEK_2, PART_III]);
  assert.deepEqual(out.map((p) => p.title), ["The Second Week", "The Plan, On the Record", "Before the Numbers"]);
});

test("#1988 — same-date parts order by sequence (Part III above Part II), not array position", () => {
  // Fed in the "wrong" order (II before III) — the exact scramble the live bug produced.
  const out = sortChronicleNewestFirst([PART_II, PART_III, PART_I]);
  assert.deepEqual(out.map((p) => p.title), ["The Plan, On the Record", "The Night Before Everything", "Before the Numbers"]);
});

test("same-date order is independent of input order (idempotent tie-break)", () => {
  const forward = sortChronicleNewestFirst([PART_III, PART_II, PART_I]);
  const reversed = sortChronicleNewestFirst([PART_II, PART_III, PART_I]);
  assert.deepEqual(forward.map((p) => p.title), reversed.map((p) => p.title));
});

test("falls back to `week` when `sequence` is absent (a stale pre-regen manifest)", () => {
  const legacyII = { title: "Legacy II", date: "2026-08-02", week: 2 };
  const legacyIII = { title: "Legacy III", date: "2026-08-02", week: 3 };
  const out = sortChronicleNewestFirst([legacyII, legacyIII]);
  assert.deepEqual(out.map((p) => p.title), ["Legacy III", "Legacy II"]);
});

test("does not mutate the input array", () => {
  const input = [PART_I, PART_III, PART_II];
  const snapshot = [...input];
  sortChronicleNewestFirst(input);
  assert.deepEqual(input, snapshot);
});

test("compareChronicleNewestFirst is a valid standalone comparator", () => {
  assert.equal(compareChronicleNewestFirst(PART_III, PART_II) < 0, true); // III sorts before II
  assert.equal(compareChronicleNewestFirst(PART_II, PART_III) > 0, true);
  assert.equal(compareChronicleNewestFirst(PART_III, PART_III), 0);
});

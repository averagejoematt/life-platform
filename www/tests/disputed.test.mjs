import assert from "node:assert/strict";
import { test } from "node:test";

import { DISPUTED_NOTE, isDisputed, verified } from "../src/lib/disputed.js";

const rows = [
  { id: "a", status: "refuted", classification_review: true },
  { id: "b", status: "refuted", classification_review: false },
  { id: "c", status: "confirmed", classification_review: false },
  { id: "d", status: "confirmed" },
];

test("a disputed verdict is never counted as verified, whatever its stored status", () => {
  assert.deepEqual(verified(rows, "refuted").map((p) => p.id), ["b"]);
  assert.deepEqual(verified(rows, "confirmed").map((p) => p.id), ["c", "d"]);
});

test("releasing the review (flag false) restores normal counting", () => {
  const released = rows.map((p) => ({ ...p, classification_review: false }));
  assert.deepEqual(verified(released, "refuted").map((p) => p.id), ["a", "b"]);
});

test("only a literal true is a dispute; the note says so in words", () => {
  assert.equal(isDisputed({ classification_review: "yes" }), false);
  assert.equal(isDisputed(null), false);
  assert.equal(isDisputed(rows[0]), true);
  assert.match(DISPUTED_NOTE, /disputed/);
});

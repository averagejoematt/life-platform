// tests/js/ck_record_counted_4617.test.mjs — #4617: the headline record states what it counts.
//
// A count like "56 of 131 checked calls right" counted calls sealed before day one, bets, calls a model read
// out of the coaches' commentary and conditional sentences as one number. The edition now serves
// `counted_text` beside the count; the record line and the big count on Coaches print it, and a
// record served without it (an older edition) prints exactly as before — nothing invented.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const P = await import("../../site/assets/js/ck_pages.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const B = JSON.parse(readFileSync(join(FIX, "edition.json"), "utf8")).blocks;
const COUNTED = "Counted: 10 sealed before day one, 4 sides of bets between two coaches, 111 read out of the coaches' running commentary and 6 conditional or hedged sentences.";
// The wording is this test's own: the capture now serves a counted record of its own, and its figures change.
const WITH = { ...B.record, data: { ...B.record.data, counted_text: COUNTED } };

test("the record line names what the count counts, between the count and the comparison", () => {
  assert.equal(P.recordLine(WITH), `${B.record.data.count_text} ${COUNTED} ${B.record.data.comparison_text}`);
});

test("the big count on Coaches prints what it counts, escaped, above the comparison", () => {
  const html = P.recordBigHTML(WITH);
  assert.match(html, /Counted: 10 sealed before day one/);
  assert.ok(html.indexOf("Counted:") < html.indexOf(B.record.data.comparison_text), "what it counts sits before the comparison");
  assert.doesNotMatch(P.recordBigHTML({ ...WITH, data: { ...WITH.data, counted_text: "<b>x</b>" } }), /<b>x<\/b>/);
});

test("a record served without it prints exactly as before", () => {
  const bare = { ...B.record, data: { ...B.record.data, counted_text: undefined, counted: undefined } };
  assert.equal(P.recordLine(bare), `${B.record.data.count_text} ${B.record.data.comparison_text}`);
  assert.doesNotMatch(P.recordBigHTML(bare), /Counted:/);
  // The capture itself serves the counted record (#4617): its sentence reaches the line, ahead of the comparison.
  assert.ok(B.record.data.counted_text && P.recordLine(B.record).includes(B.record.data.counted_text));
});

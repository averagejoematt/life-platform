// tests/js/ck_record_counted_4617.test.mjs — #4617: the headline record states what it counts.
//
// "56 of 131 checked calls right" counted calls sealed before day one, bets, calls a model read
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
const WITH = { ...B.record, data: { ...B.record.data, counted_text: COUNTED } };

test("the record line names what the count counts, between the count and the comparison", () => {
  assert.equal(P.recordLine(WITH), `56 of 131 checked calls right. ${COUNTED} So far they do not beat a simple guess.`);
});

test("the big count on Coaches prints what it counts, escaped, above the comparison", () => {
  const html = P.recordBigHTML(WITH);
  assert.match(html, /Counted: 10 sealed before day one/);
  assert.ok(html.indexOf("Counted:") < html.indexOf("So far they do not beat"), "what it counts sits before the comparison");
  assert.doesNotMatch(P.recordBigHTML({ ...WITH, data: { ...WITH.data, counted_text: "<b>x</b>" } }), /<b>x<\/b>/);
});

test("a record served without it prints exactly as before", () => {
  assert.equal(P.recordLine(B.record), "56 of 131 checked calls right. So far they do not beat a simple guess.");
  assert.doesNotMatch(P.recordBigHTML(B.record), /Counted:/);
});

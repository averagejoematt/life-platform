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

// Red team 2026-10-17: the front page and Start carry ONE plain sentence (count; comparison); the
// breakdown is the Coaches page's, under one plain sentence that says why there is one.
// Round 2: the comparison names the guess and the gap (P.guessClause), from the served skill fields.
const ONE = (rd) => `${rd.count_text} ${P.guessClause(rd)}`;
test("the record line is one plain sentence: the count and the comparison, with no breakdown", () => {
  assert.equal(P.recordLine(WITH), ONE(B.record.data));
  assert.doesNotMatch(P.recordLine(WITH), /Counted|sealed/);
});

test("the big count on Coaches prints what it counts after one plain sentence, escaped, below the comparison", () => {
  const html = P.recordBigHTML(WITH);
  assert.match(html, /Not all of them are formal predictions\. Of the \d+: 10 sealed before day one/);
  assert.doesNotMatch(html, /Counted:/);
  assert.ok(html.indexOf("formal predictions") > html.indexOf("A guess that every call"), "the comparison stays beside the count");
  assert.doesNotMatch(P.recordBigHTML({ ...WITH, data: { ...WITH.data, counted_text: "<b>x</b>" } }), /<b>x<\/b>/);
});

test("a record served without it prints the count and comparison alone", () => {
  const bare = { ...B.record, data: { ...B.record.data, counted_text: undefined, counted: undefined } };
  assert.equal(P.recordLine(bare), ONE(B.record.data));
  assert.doesNotMatch(P.recordBigHTML(bare), /formal predictions/);
  assert.ok(B.record.data.counted_text && P.recordBigHTML(B.record).includes("formal predictions"));
});

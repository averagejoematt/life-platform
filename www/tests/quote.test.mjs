// #5609 — a coach's words are quoted exactly; the dates they carry are explained in words OUTSIDE the quotation.
import assert from "node:assert/strict";
import { test } from "node:test";

import { clip, glossList, glossText, quoteGlosses, quoteParts } from "../src/lib/format.js";

const CLAIM = "Recovery score will be 52.9% tomorrow based on the night of 2026-09-09 baseline (80% interval 26.7–79.2%).";

test("the parts of a quotation, joined, ARE the quotation (byte for byte)", () => {
  for (const t of [CLAIM, "no date here", "", "2026-09-14 to 2026-09-17", "ends on 2026-09-12", "a non-date 2026-13-40 stays text"]) {
    const joined = quoteParts(t)
      .map((p) => p.date ?? p.text)
      .join("");
    assert.equal(Buffer.compare(Buffer.from(joined, "utf8"), Buffer.from(t, "utf8")), 0, t);
  }
  assert.deepEqual(quoteParts(CLAIM)[1], { date: "2026-09-09" });
});

test("the gloss names each quoted date once, in order, in words — never the ISO form", () => {
  assert.equal(glossList(CLAIM), "Wednesday 9 September 2026");
  assert.equal(glossText(CLAIM), "The date quoted is Wednesday 9 September 2026.");
  const two = "Recovery will sit between 2026-09-14 and 2026-09-17, then 2026-09-14 again.";
  assert.deepEqual(
    quoteGlosses(two).map((g) => g.iso),
    ["2026-09-14", "2026-09-17"],
  );
  assert.equal(glossList(two), "Monday 14 September 2026 and Thursday 17 September 2026");
  assert.equal(glossText(two), "The dates quoted are Monday 14 September 2026 and Thursday 17 September 2026.");
  assert.doesNotMatch(glossText(two), /\d{4}-\d\d-\d\d/);
});

test("no date, a non-calendar date, a date the clip cut off: no gloss", () => {
  assert.equal(glossList("no date here"), "");
  assert.equal(glossText("no date here"), "");
  assert.equal(glossList("a non-date 2026-13-40 stays text"), "");
  const cut = clip("Weight will hold within a pound of 304 for the next three mornings, through 2026-10-17.", 60);
  assert.equal(glossList(cut), "");
});

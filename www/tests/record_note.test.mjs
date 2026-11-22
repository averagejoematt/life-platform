// #6161: a coach record quoted inside a chapter carries one "as published" line beside it; the chapter is never edited.
import assert from "node:assert/strict";
import { test } from "node:test";
import { placeRecordNote, quotesRecord } from "../src/lib/record_note.js";

const NOTE = '<p class="evidence-note" data-record-as-published>as published</p>';

test("the forms a chapter states a record in are recognised; a bare 'record' is not one", () => {
  for (const s of ["Her season record now stands at 5 wins and 6 losses.", "Her season record stands at 11 right and 15 wrong.", "Every coach sits at 0 for 0.", "a coach with the best record on the team", "four wins and three losses"])
    assert.ok(quotesRecord(`<p>${s}</p>`), s);
  for (const s of ["The mechanism produced a different one in the sleep record.", "every number on the record", "the record shows 98 percent recovery"])
    assert.ok(!quotesRecord(`<p>${s}</p>`), s);
});

test("the note goes after the first plain paragraph that quotes a record, and only once", () => {
  const html = '<p class="signature"><em>0 for 0 in a signature line</em></p><p>Opening.</p><p>She is 5 wins and 6 losses.</p><p>Webb has the worst record.</p>';
  const { html: out, placed } = placeRecordNote(html, NOTE);
  assert.ok(placed);
  assert.equal(out, '<p class="signature"><em>0 for 0 in a signature line</em></p><p>Opening.</p><p>She is 5 wins and 6 losses.</p>' + NOTE + "<p>Webb has the worst record.</p>");
  assert.equal(out.replace(NOTE, ""), html, "no word of the chapter changes");
});

test("a chapter that quotes no record, or no note, is returned as is", () => {
  assert.deepEqual(placeRecordNote("<p>Nothing here.</p>", NOTE), { html: "<p>Nothing here.</p>", placed: false });
  assert.deepEqual(placeRecordNote("<p>0 for 0</p>", null), { html: "<p>0 for 0</p>", placed: false });
});

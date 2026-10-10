// tests/js/ck_front_scorecard_4595.test.mjs — #4595: the front page prints the served scorecard.
//
// The rows are decided in lambdas/web/site_api_edition.py; the page only prints them. Driven from
// tests/fixtures/edition_scorecard_4595/scorecard_wire_2026-10-03.json — the block compose() makes
// of the edition wire (tests/test_edition_scorecard_4595.py holds that the file IS that block).
// What is held: every row prints its verdict IN WORDS beside its own sentence, a source that failed
// prints its own not-served sentence, the rules and the day they were set are on the page, the
// "what went right" pair prints, and an unserved scorecard prints a sentence, never a blank.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const F = await import("../../site/assets/js/ck_front.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "edition_scorecard_4595", "scorecard_wire_2026-10-03.json");
const SC = JSON.parse(readFileSync(FIX, "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));
const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

test("every row prints its verdict in words beside its own sentence, in the served order", () => {
  const html = F.scorecardHTML(SC, "/next/v8/");
  const plain = text(html);
  let at = -1;
  for (const key of SC.data.order) {
    const r = SC.data.rows[key].data;
    const line = `${r.name} ${r.verdict_text}. ${r.text}`;
    const i = plain.indexOf(line);
    assert.ok(i > at, `row ${key} missing or out of order: ${line}`);
    at = i;
  }
  assert.match(plain, /How the whole thing is going/);
  // The fixture's verdicts include all three decided kinds: the dot is never the only carrier.
  assert.match(plain, /Faster than planned\./);
  assert.match(plain, /Not enough data\./);
  assert.match(plain, /Going well\./);
  assert.match(plain, /Not yet\./);
});

test("the rules and the day they were set are printed with the rows", () => {
  const plain = text(F.scorecardHTML(SC));
  assert.ok(plain.includes(SC.data.rules_set_text), "the day the rules were set is missing");
  for (const key of SC.data.order) assert.ok(plain.includes(SC.data.rows[key].data.rule), `the ${key} rule is missing`);
  assert.doesNotMatch(F.scorecardHTML(SC), /\b20\d\d-\d\d-\d\d\b/, "an ISO date reached the page");
});

test("what went right prints one line for Matthew and one for the engine", () => {
  const plain = text(F.scorecardHTML(SC));
  assert.ok(plain.includes(`What went right this week Matthew ${SC.data.went_right.matthew.text}`));
  assert.ok(plain.includes("The engine Nothing this week."));
});

test("a row whose source failed prints its not-served sentence, never a verdict", () => {
  const sc = clone(SC);
  sc.data.rows.food = { state: "unavailable", as_of: null, source: "/api/nutrition_overview", absent_text: "The food log is not served right now.", data: null };
  const plain = text(F.scorecardHTML(sc));
  assert.ok(plain.includes("Food The food log is not served right now."));
});

test("an unserved scorecard prints its own sentence, and is not taken as rows", () => {
  const gone = { state: "unavailable", as_of: null, source: [], absent_text: "The scorecard is not served right now.", data: null };
  assert.equal(F.scorecardRows(gone).length, 0);
  assert.equal(F.scorecardHTML(gone), '<p class="ck-soft">The scorecard is not served right now.</p>');
  assert.equal(F.scorecardRows(SC).length, 6);
});

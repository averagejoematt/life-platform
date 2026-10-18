// tests/js/ck_front_scorecard_4595.test.mjs — #4595: the front page prints the served scorecard.
//
// The rows are decided in lambdas/web/site_api_edition.py; the page only prints them. Driven from
// tests/fixtures/edition_scorecard_4595/scorecard_wire.json — the block compose() makes
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
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "edition_scorecard_4595", "scorecard_wire.json");
const SC = JSON.parse(readFileSync(FIX, "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));
const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

test("every row prints its verdict in words beside its own sentence, in the served order", () => {
  const html = F.scorecardHTML(SC, "/next/v8/");
  const plain = text(html);
  let at = -1;
  // Site-to-A round 1 (#4580 W3): the AI row's "to date, not this week's alone" is said once, by
  // the rule under the row, so the row's own copy of the clause is not printed.
  const rowLine = (r) => (/not this week's alone/.test(r.rule || "") && /not this week's alone/.test(r.text || "") ? `${r.name} ${r.verdict_text}.` : `${r.name} ${r.verdict_text}. ${r.text}`);
  for (const key of SC.data.order) {
    const r = SC.data.rows[key].data;
    const line = rowLine(r);
    const i = plain.indexOf(line);
    assert.ok(i > at, `row ${key} missing or out of order: ${line}`);
    at = i;
  }
  assert.match(plain, /How the whole thing is going/);
  // #4809: each verdict's words say what happened against its rule — "No rest day.", never
  // "Not yet." over "Trained on 7 of 7 days recorded." The bare verdict words are never printed.
  for (const key of ["training", "body", "food"]) {
    const r = SC.data.rows[key].data;
    assert.ok(plain.includes(`${r.name} ${r.verdict_text}. ${r.text}`), `${key}: the verdict's words and the sentence it decided`);
  }
  for (const word of ["Not yet.", "Going well.", "Not enough data.", "Faster than planned."]) assert.ok(!plain.includes(` ${word}`), `a bare "${word}"`);
  // The AI row says its count is to date, and its rule says so too.
  const ai = SC.data.rows.ai.data;
  assert.match(ai.text, /^Counted across all \d+ calls checked to date, not this week's alone\.$/);
  assert.ok(plain.includes(`The AI ${ai.verdict_text}.`));
  assert.equal(plain.split("not this week's alone").length - 1, 1, "the clause is said once, under the row");
});

test("the rules and the day they were set are printed with the rows", () => {
  const plain = text(F.scorecardHTML(SC));
  // #4580 W8: the served sentence is given its antecedent on the page ("in grey"), its day unchanged.
  assert.ok(plain.includes(SC.data.rules_set_text.replace(/^The rules were set on/, "The rules in grey were written down on")), "the day the rules were set is missing");
  for (const key of SC.data.order) assert.ok(plain.includes(F.shortRule(SC.data.rows[key].data.rule)), `the ${key} rule is missing`);
  assert.equal(F.shortRule("Days trained in the last seven. Going well at 4 to 6, so at least one rest day. Fewer than 5 days recorded is not enough data."), "Days trained in the last seven. Going well at 4 to 6, so at least one rest day.");
  assert.equal(F.shortRule("Going well at 3. When the 10 newest entries all fall inside the week, the count is not enough data."), "Going well at 3.");
  assert.equal(F.shortRule("A rule with no floor."), "A rule with no floor.");
  assert.doesNotMatch(F.scorecardHTML(SC), /\b20\d\d-\d\d-\d\d\b/, "an ISO date reached the page");
});

test("what went right is the filled dots, never a second list from another source (#4580 W2)", () => {
  // The served went_right is built upstream from GOING_WELL alone while the filled dot also marks
  // "faster than planned", so a list from it disagreed with the dots on the same page; and its
  // "Matthew" row repeated the Sleep row word for word. It is not printed.
  const html = F.scorecardHTML(SC);
  const plain = text(html);
  assert.doesNotMatch(plain, /What went right this week|The engine/);
  assert.ok(!plain.includes(`Matthew ${SC.data.went_right.matthew.text}`), "the party-keyed row is gone");
  const earned = SC.data.order.filter((k) => SC.data.rows[k].data.verdict === "going_well").length;
  assert.equal((html.match(/class="ck-dot"/g) || []).length, earned, "one filled dot per row that earned it");
  assert.match(plain, /A filled dot is an area going well this week\./);
  const both = clone(SC);
  both.data.went_right.engine = { area: "ai", text: "The coaches beat the simple guess on three calls.", source: "/api/calibration" };
  assert.doesNotMatch(text(F.scorecardHTML(both)), /The engine/);
});

test("the mark is filled for a row that earned it — going well, and only that (site-to-A round 2) — and the page can drop the kicker (round 8)", () => {
  const html = F.scorecardHTML(SC, "/next/v8/");
  const row = (name) => html.split("<li>").find((li) => li.includes(`>${name}</a>`) || li.includes(`>${name}</span>`));
  const earned = (key) => SC.data.rows[key].data.verdict === "going_well";
  for (const [name, key] of [["Body", "body"], ["Sleep", "sleep"], ["Training", "training"]]) {
    const dot = earned(key) ? "ck-dot" : "ck-dot ck-dot--off";
    assert.ok(row(name).includes(`<i class="${dot}" aria-hidden="true"></i><b>${SC.data.rows[key].data.verdict_text}.</b>`), `${key}: the mark follows the verdict`);
  }
  assert.match(row("Training"), /<span class="ck-small">Days trained in the last seven/, "the rule sits under the row it decided");
  assert.doesNotMatch(F.scorecardHTML(SC, "/next/v8/", { label: false }), /How the whole thing is going/);
  assert.match(F.scorecardHTML(SC, "/next/v8/"), /How the whole thing is going/);
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

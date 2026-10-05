// tests/js/ck_depth_day_story_4648.test.mjs — #4648: a day page also shows what the coaches
// said that day and any call that settled that day; a day with neither prints nothing extra.
// Driven from the committed kit fixtures: calls.json is GET /api/calls as served, and
// coach_moves_2026-10-02.json is GET /api/coach_moves's own output for the stored-row
// fixture (tests/test_site_api_coach_moves_4648.py pins the two equal).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const D = await import("../../site/assets/js/ck_depth.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const CALLS = load("calls");
const MOVES = load("coach_moves_2026-10-02");
const ABSENT = { state: "absent", date: "2026-10-01", source: "/api/coach_moves", absent_text: "No coach line is recorded for Thursday, October 1.", lines: [] };
const BASE = "/next/v8/";
const text = (html) => html.replace(/<[^>]+>/g, " ");

test("a day with no coach line and no settled call prints nothing extra", () => {
  // October 1 is such a day in the fixtures: no call settled on it, and the route is absent.
  assert.equal(CALLS.calls.filter((c) => c.settled_date === "2026-10-01").length, 0, "the fixture day has no settled call");
  assert.equal(D.daySaidHTML("2026-10-01", ABSENT, BASE), "");
  assert.equal(D.daySettledHTML("2026-10-01", CALLS, BASE), "");
  assert.equal(D.dayStoryHTML("2026-10-01", ABSENT, CALLS, BASE), "", "no heading, no empty section, no filler");
  // The absence sentence is the route's and is never printed on the page.
  assert.doesNotMatch(D.dayStoryHTML("2026-10-01", ABSENT, CALLS, BASE), /No coach line/);
});

test("a route that is not served, or a body that is not this day's, prints nothing", () => {
  for (const body of [null, undefined, {}, { state: "unavailable" }, { state: "ok", date: "2026-10-02", lines: [] }, { state: "ok", date: "2026-10-02", lines: [{ coach: "", text: "x" }, null] }]) {
    assert.equal(D.dayStoryHTML("2026-10-02", body, null, BASE), "");
  }
  assert.equal(D.daySaidHTML("2026-10-01", MOVES, BASE), "", "another day's lines are never shown on this day");
  assert.equal(D.daySettledHTML("2026-10-02", { state: "unavailable", calls: [] }, BASE), "");
});

test("a day with coach lines shows each coach's words as served, under one heading", () => {
  const html = D.daySaidHTML("2026-10-02", MOVES, BASE);
  assert.equal((html.match(/<h2>/g) || []).length, 1);
  assert.match(html, /<h2>What the coaches said\.<\/h2>/);
  assert.equal((html.match(/<li>/g) || []).length, 3);
  for (const l of MOVES.lines) assert.ok(html.includes(`“${l.text}”`), `${l.coach}'s words are printed whole and unchanged`);
  assert.match(html, /<a class="ck-link" href="\/next\/v8\/coach\/\?c=sleep_coach">Lisa Park<\/a> · On a result/);
  assert.match(html, /Marcus Webb<\/a> · A reply to Max Reyes/);
  assert.equal((html.match(/A bet opened in these lines settles Friday, October 9\./g) || []).length, 1, "two lines share one bet: its date is said once");
  assert.doesNotMatch(text(html), /\b20\d\d-\d\d-\d\d\b|\bDr\.|undefined|null/);
});

test("a day with a settled call shows the call, its rule, the verdict and a link to its page", () => {
  const call = CALLS.calls.find((c) => c.settled_date === "2026-10-02");
  const html = D.daySettledHTML("2026-10-02", CALLS, BASE);
  assert.match(html, /<h2>A call was checked this day\.<\/h2>/);
  assert.ok(html.includes(call.called), "the served sentence, which carries the rule it was checked by");
  assert.match(html, /counts as right within 1\.2 hours either way/);
  assert.match(html, /<span class="ck-verdicts__tag ck-verdicts__tag--right">Right<\/span>/);
  assert.match(html, /It came in at 8\.6 hours\./);
  assert.ok(html.includes(`href="/next/v8/call/?id=${call.id}"`));
  assert.doesNotMatch(html, /<details>/);
});

test("a bet settled that day is tagged with the sentence naming both coaches", () => {
  const html = D.daySettledHTML("2026-09-30", CALLS, BASE);
  assert.match(html, /<h2>2 calls were checked this day\.<\/h2>/);
  assert.match(html, /<span class="ck-verdicts__tag">Marcus Webb was right; Amara Patel was wrong\.<\/span>/);
  assert.match(html, /href="\/next\/v8\/call\/\?id=bet-20260930-994b3d89f6"/);
});

test("a day with many settled calls shows two and folds the rest, every one still linked", () => {
  const day = CALLS.calls.filter((c) => c.settled_date === "2026-09-24");
  const html = D.daySettledHTML("2026-09-24", CALLS, BASE);
  assert.equal(day.length, 4);
  assert.match(html, /<h2>4 calls were checked this day\.<\/h2>/);
  assert.match(html, /<details><summary>2 more settled this day<\/summary>/);
  for (const c of day) assert.ok(html.includes(`id=${c.id}"`), c.id);
  assert.match(html, /<span class="ck-verdicts__tag">Wrong<\/span>/);
});

test("both on one day: the coaches first, then what settled", () => {
  const html = D.dayStoryHTML("2026-10-02", MOVES, CALLS, BASE);
  assert.ok(html.indexOf("What the coaches said.") > -1 && html.indexOf("What the coaches said.") < html.indexOf("A call was checked this day."));
  assert.equal((html.match(/<section /g) || []).length, 1, "one section");
  assert.equal((html.match(/<h2>/g) || []).length, 1, "one heading: under the coaches, what settled takes a label");
  assert.match(html, /<p class="ck-label">A call was checked this day\.<\/p>/);
  assert.match(D.dayStoryHTML("2026-10-02", null, CALLS, BASE), /^<section class="ck-section" id="ck-story"><p class="ck-label">Settled<\/p><h2>A call was checked this day\.<\/h2>/);
});

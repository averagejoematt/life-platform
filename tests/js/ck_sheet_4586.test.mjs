// tests/js/ck_sheet_4586.test.mjs — #4586: the character sheet, presented plainly.
//
// Driven from live captures (2026-10-04) in tests/fixtures/kit_pages_4586/. What is held:
// a level is shown with its score and its direction (a level can go down); an area nothing
// measures says so and is never drawn as an average; only earned badges are listed, each
// with its date; no machine name, emoji or game term reaches the page.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const S = await import("../../site/assets/js/ck_sheet.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const character = load("character");
const achievements = load("achievements");
const pillar = (name) => character.pillars.find((p) => p.name === name);

test("an area's line is its level, its score and which way it moved", () => {
  assert.equal(S.areaLine(pillar("sleep")), "Level 16. Score 84 of 100, down 0.6 on the day.");
  assert.equal(S.areaLine(pillar("movement")), "Level 22. Score 66 of 100, up 10.9 on the day.");
  assert.match(S.areaLine(pillar("nutrition")), /level on the day/);
});

test("an area nothing measures says so and shows no level", () => {
  assert.equal(S.areaLine(pillar("relationships")), "Not measured yet: nothing records this area.");
  assert.equal(S.areaDetail(pillar("relationships")), "");
});

test("the detail names what helps, what holds it back and what is missing, in plain words", () => {
  assert.equal(S.areaDetail(pillar("sleep")), "Helping: sleep length and deep sleep.");
  assert.match(S.areaDetail(pillar("movement")), /Holding it back: easy cardio minutes\./);
  assert.match(S.areaDetail(pillar("nutrition")), /Not done or not logged: calories against the plan, protein, protein across meals and logging food every day\./);
  assert.deepEqual(S.driverWords(["some_new_driver"]), ["some new driver"], "an unknown driver prints its own name, never a blank");
});

test("every served driver has plain words", () => {
  const ids = character.pillars.flatMap((p) => Object.values(p.drivers || {}).flat());
  const html = S.areasHTML(character);
  assert.ok(ids.length > 10);
  assert.doesNotMatch(html.replace(/<[^>]+>/g, " "), /_/, "no machine name reaches the page");
  for (const name of Object.values(S.AREAS)) assert.match(html, new RegExp(`>${name}<`));
});

test("the level says how many areas it came from and the day it is for", () => {
  const html = S.levelHTML(character);
  assert.match(html, /<p class="ck-big">10<span>level on Saturday, October 3<\/span><\/p>/);
  assert.match(html, /Worked out from 6 of 7 areas; an area with nothing measuring it is left out, not counted as average\./);
  assert.match(S.levelHTML(null), /not served right now/);
  assert.equal(S.sheetLine(character), "Level 10 across six of seven areas of his life", "the front page states the same count the sheet does");
  assert.equal(S.sheetLine({}), "");
});

test("only earned badges are listed, newest first, each with its date", () => {
  const html = S.badgesHTML(achievements);
  const earned = achievements.achievements.filter((a) => a.earned);
  assert.equal((html.match(/<li>/g) || []).length, earned.length);
  assert.match(html, new RegExp(`${earned.length} of ${achievements.achievements.length} earned so far\\.`));
  assert.ok(html.indexOf("October 3") < html.indexOf("September 12"), "newest first");
  assert.match(S.badgesHTML({ achievements: [{ label: "A", earned: false }] }), /None of the 1 badges has been earned yet\./);
  assert.match(S.badgesHTML(null), /not served right now/);
});

test("the page carries no emoji, honorific, ISO date or count of earlier starts", () => {
  const text = [S.levelHTML(character), S.areasHTML(character), S.badgesHTML(achievements)].join("\n").replace(/<[^>]+>/g, " ");
  assert.doesNotMatch(text, /\p{Extended_Pictographic}/u);
  assert.doesNotMatch(text, /\bDr\.\s|\b20\d\d-\d\d-\d\d\b|\bcycle\b|\battempt\b|\breset\b/i);
});

test("an area held for thin coverage prints no score beside a fully measured one (red team, round 7)", () => {
  assert.equal(S.areaLine({ level: 1, raw_score: 59.4, coverage_hold: true }), "Level 1. Too little of this area is measured to score it yet.");
  assert.match(S.areaLine({ level: 2, raw_score: 1.8, score_delta: 0 }), /^Level 2\. Score 2 of 100/);
});

test("an earned badge with no recorded date is counted and says so, never dated (#4704)", () => {
  const body = {
    achievements: [
      { label: "Lost 5 lbs", earned: true, earned_date: "2026-09-12" },
      { label: "Lost 20 lbs", earned: true, earned_date: null },
      { label: "Lost 30 lbs", earned: false },
    ],
    summary: { earned: 2, total: 3 },
  };
  const html = S.badgesHTML(body);
  assert.match(html, /2 of 3 earned so far\./, "the count matches summary.earned");
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /date not recorded<\/span><span>Lost 20 lbs/);
  assert.ok(html.indexOf("Lost 5 lbs") < html.indexOf("Lost 20 lbs"), "the undated badge is listed last");
});

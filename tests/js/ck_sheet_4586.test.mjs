// tests/js/ck_sheet_4586.test.mjs — #4586: the character sheet, presented plainly.
//
// Driven from one live capture (its time in _capture.json; #4671) in tests/fixtures/kit_pages_4586/;
// every figure is read from the capture it tests, never pinned (#4839). What is held:
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
  for (const name of ["sleep", "movement", "nutrition"]) {
    const p = pillar(name);
    const move = Math.abs(p.score_delta) < 0.05 ? "level on the day" : `${p.score_delta > 0 ? "up" : "down"} ${Math.abs(p.score_delta).toFixed(1)} on the day`;
    assert.equal(S.areaLine(p), `Level ${p.level}. Score ${p.raw_score.toFixed(1)} of 100, ${move}.`, name);
  }
  assert.equal(S.areaLine({ ...pillar("sleep"), score_delta: 3.7 }), `Level ${pillar("sleep").level}. Score ${pillar("sleep").raw_score.toFixed(1)} of 100, up 3.7 on the day.`);
  assert.match(S.areaLine({ ...pillar("sleep"), score_delta: -1.25 }), /, down 1\.[23] on the day\.$/);
  assert.match(S.areaLine({ ...pillar("nutrition"), score_delta: 0.01 }), /, level on the day\.$/, "a move under 0.05 is no move");
});

test("an area nothing measures says so and shows no level", () => {
  assert.equal(S.areaLine(pillar("relationships")), "Not measured yet: nothing records this area.");
  assert.equal(S.areaDetail(pillar("relationships")), "");
});

test("the detail names what helps, what holds it back and what is missing, in plain words", () => {
  const labelled = { top: "Helping", dragging: "Holding it back", absent: "Not done or not logged", no_data: "No data yet" };
  for (const p of character.pillars.filter((x) => !x.not_instrumented)) {
    const detail = S.areaDetail(p);
    for (const [key, label] of Object.entries(labelled)) {
      const ids = p.drivers[key] || [];
      assert.equal(detail.includes(`${label}: `), ids.length > 0, `${p.name}: ${label}`);
      for (const id of ids) assert.ok(detail.includes(S.driverWords([id])[0]), `${p.name}: ${id} in plain words`);
    }
    assert.doesNotMatch(detail, /_/, p.name);
  }
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
  const c = character.character;
  assert.match(html, new RegExp(`<p class="ck-big">${Math.round(c.level)}<span> level on [A-Z][a-z]+day, [A-Z][a-z]+ \\d+</span></p>`));
  assert.ok(html.includes(`Worked out from ${c.composite_pillar_count} of ${c.composite_pillar_total} areas`));
  if (c.composite_pillar_count < c.composite_pillar_total) assert.match(html, /an area with nothing measuring it is left out, not counted as average\./);
  assert.match(S.levelHTML(null), /not served right now/);
  assert.match(S.sheetLine(character), new RegExp(`^Level ${Math.round(c.level)} across \\w+ of \\w+ areas of his life$`), "the front page states the same count the sheet does");
  assert.equal(S.sheetLine({}), "");
});

test("only earned badges are listed, newest first, the undated one last", () => {
  const html = S.badgesHTML(achievements);
  // Every earned badge is listed and counted, so the count matches summary.earned; one with no
  // recorded date says so and comes last (#4704; the synthetic case below holds that when the capture has none).
  const earned = achievements.achievements.filter((a) => a.earned);
  assert.equal(earned.length, achievements.summary.earned);
  assert.equal((html.match(/<li>/g) || []).length, earned.length);
  assert.match(html, new RegExp(`${earned.length} of ${achievements.achievements.length} earned so far\\.`));
  const dated = earned.filter((a) => a.earned_date).sort((x, y) => y.earned_date.localeCompare(x.earned_date));
  for (let i = 1; i < dated.length; i += 1) {
    if (dated[i - 1].earned_date !== dated[i].earned_date) assert.ok(html.indexOf(dated[i - 1].label) < html.indexOf(dated[i].label), `newest first: ${dated[i - 1].label} before ${dated[i].label}`);
  }
  for (const u of earned.filter((a) => !a.earned_date)) assert.ok(dated.every((d) => html.indexOf(d.label) < html.indexOf(u.label)), "the undated one last");
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
  assert.match(S.areaLine({ level: 2, raw_score: 1.8, score_delta: 0 }), /^Level 2\. Score 1\.8 of 100/);
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

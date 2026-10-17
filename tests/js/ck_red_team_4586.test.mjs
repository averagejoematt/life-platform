// tests/js/ck_red_team_4586.test.mjs — the four v8 preview pages against the 2026-10-17 red team
// (#4586). Each test names the finding it holds: an honest held state on Story, the weight rows'
// shape, the teaser that agrees with the page, no empty bet section, the pre-start sensor label.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const P = await import("../../site/assets/js/ck_pages.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const EDITION = load("edition");
const B = EDITION.blocks;
const POSTS = load("posts");
const later = (iso, days) => new Date(Date.parse(`${iso}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
const chapter = { ...B.chapter, state: "stale" };
const latestDate = chapter.data.date;
const n = P.weekNumberOf(chapter.data.week_label);

test("Story: a week that has not published is said in one calm line, never silence", () => {
  assert.ok(n >= 1, "the capture's latest chapter is a numbered week");
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 3) }, POSTS), "", "a current chapter needs no line");
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 11) }, POSTS), `Week ${n + 1} has not published yet: each chapter waits for Matthew to read and approve it.`);
  const marked = { ...POSTS, pending: { week: n + 1, reason: "story_door_hold" } };
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 3) }, marked), `Week ${n + 1} is held before publishing.`, "the chronicle's own marker wins");
  assert.equal(P.heldChapterLine({ state: "unavailable", data: null }, { as_of: later(latestDate, 11) }, POSTS), "");
});

test("Story: the podcast line says held when the episode list marks this week held", () => {
  const episodes = { episodes: [], pending: { week: n, reason: "held_for_review" } };
  assert.equal(P.podcastHeld(episodes, n), true);
  assert.equal(P.podcastHeld({ ...episodes, pending: { week: n, reason: "other" } }, n), false);
  assert.equal(P.podcastHeld(episodes, n + 1), false);
  assert.match(P.playerHTML({ state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null }, { held: true }), /held for review/);
  assert.match(P.playerHTML({ state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null }), /No podcast episode/);
});

test("Story: the lead puts the held line beside the next date, saying the approval once", () => {
  const edition = { ...EDITION, as_of: later(latestDate, 11) };
  const noPod = { ...chapter, data: { ...chapter.data, podcast: { state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null } } };
  const html = P.storyChapterHTML(edition, { ...B, chapter: noPod }, POSTS, { episodes: [], pending: { week: n, reason: "held_for_review" } });
  assert.match(html, new RegExp(`Week ${n + 1} has not published yet`));
  assert.match(html, /held for review/);
  assert.equal((html.match(/approve/g) || []).length, 1, html);
});

test("Story: the teaser says which way the scale crossed, and its pounds gone are the page's own two numbers", () => {
  const dek = "Rest days, while the scale crossed 310 pounds for the first time, suggesting 18.5 pounds gone…";
  const out = P.teaserText(dek, { chapterLb: 308.9, startLb: 327.3 });
  assert.match(out, /went below 310 pounds for the first time/);
  assert.match(out, new RegExp(`suggesting ${P.poundsDown(327.3, 308.9)} pounds gone`));
  assert.equal(P.poundsDown(327.3, 308.9), (327.3 - 308.9).toFixed(1), "one helper, one rounding");
  assert.match(P.teaserText("the scale crossed 310 pounds", { chapterLb: 311 }), /went above 310/);
  assert.equal(P.teaserText(dek, {}), dek, "without the chapter's weight the teaser is printed as served");
});

test("Story: every chapter row is label · value; a prologue is before day one, week 1 is labelled the start", () => {
  const posts = P.postsInOrder(POSTS);
  const start = B.today.data.start_weight_lbs;
  const html = P.chapterRowsHTML(posts, { startLb: start });
  const values = [...html.matchAll(/<span class="ck-rows__value">([^<]*)<\/span>/g)].map((m) => m[1]);
  assert.equal(values.length, posts.length);
  for (const v of values) assert.match(v, /^(Before day one|\d+(\.\d)? lb(, the start)?)$/, v);
  assert.equal(values.filter((v) => /the start/.test(v)).length, 1, "exactly one row is the start");
  assert.doesNotMatch(html, /\blbs\b|September|October/, "no date where a weight belongs, one unit label");
});

test("Coaches: the bet section is not drawn when nothing is waiting to settle; a failed read still says so", () => {
  const none = { state: "ok", data: { bet: { state: "absent", absent_text: "No coach bet is waiting to settle.", data: null } } };
  assert.equal(P.coachesBetHTML(none, { open: [] }), null);
  assert.equal(P.coachesBetHTML(none, null), null);
  assert.match(P.coachesBetHTML(none, { open: [{ resolution_date: "2026-10-21" }] }), /bet settles/);
  assert.match(P.coachesBetHTML({ state: "unavailable", absent_text: "What comes next is not served right now.", data: null }, null), /not served/);
  assert.match(P.coachesBetHTML({ state: "ok", data: { bet: { state: "unavailable", absent_text: "The bets are not served right now.", data: null } } }, null), /not served/);
});

test("Coaches: a coach sitting out since before day one says what its counted calls rest on", () => {
  const body = { coaches: [{ persona_id: "glucose_coach", name: "Amara Patel", absent: true, reason: "no sensor since 2026-08-27", record: { confirmed: 1, refuted: 6, n: 7 } }] };
  const start = B.today.data.start_date;
  assert.ok(start > "2026-08-27");
  assert.match(P.teamHTML(body, "", "", { startDate: start }), /no sensor since August 27, before day one, so the calls counted here were checked on other readings\./);
  assert.doesNotMatch(P.teamHTML(body, "", "", { startDate: "2026-08-01" }), /before day one/, "a sitting-out date inside the run is not called pre-start");
  assert.doesNotMatch(P.teamHTML(body), /before day one/, "no start date served: no claim");
});

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
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 11) }, POSTS), `Week ${n + 1} is waiting for Matthew’s approval.`);
  // Round 3: with the next date served, the line names the week whose draft comes next (same arithmetic).
  const nextB = { state: "ok", data: { chapter: { state: "ok", data: { date: later(latestDate, 15), drafted_not_promised: true } } } };
  assert.match(P.heldChapterLine(chapter, { as_of: later(latestDate, 11) }, POSTS, nextB), new RegExp(`^Week ${n + 1} is waiting for Matthew’s approval; week ${n + 2}’s draft is due [A-Z][a-z]+day, [A-Z][a-z]+ \\d+\\.$`));
  assert.match(P.heldChapterLine(chapter, { as_of: later(latestDate, 15) }, POSTS, nextB), new RegExp(`^Weeks ${n + 1} to ${n + 2} are waiting for Matthew’s approval; week ${n + 3}’s draft`));
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
  assert.match(html, new RegExp(`Week ${n + 1} is waiting for Matthew’s approval; week ${n + 2}’s draft is due`));
  assert.match(html, /held for review/);
  assert.doesNotMatch(html, /The next draft is due/, "the next date is said once");
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

// ── round 2 (2026-10-17, the independent re-grade) ──────────────────────────────
const F = await import("../../site/assets/js/ck_front.js");

test("Start: the week's change is the difference of the two weights the list prints, never the served unrounded one", () => {
  const html = P.recapHTML(P.postsInOrder(POSTS));
  const rows = [...html.matchAll(/· (\d+\.\d) lb(?:, (down|up) (\d+\.\d) this week)?/g)].map((m) => ({ w: Number(m[1]), dir: m[2], d: m[3] }));
  assert.ok(rows.length >= 3);
  for (let i = 1; i < rows.length; i += 1) {
    const want = (rows[i - 1].w - rows[i].w).toFixed(1);
    assert.equal(rows[i].d, Math.abs(Number(want)).toFixed(1), `row ${i}`);
    assert.equal(rows[i].dir, Number(want) > 0 ? "down" : "up");
  }
  assert.equal(P.weekChange("315.0", "312.3"), "down 2.7 this week");
  assert.equal(P.weekChange("", "312.3"), "");
});

test("Front: a line in the statistician's jargon, or one with a reader-gate finding, is never quoted", () => {
  const jargon = "27.6% deep sleep spike (1.8 SD above baseline) is likely regression-to-mean noise without thermal anchor and subjective context";
  assert.equal(F.plainLanguage(jargon), false);
  assert.equal(F.frontQuotable({ coach_id: "sleep_coach", move: "reply", text: jargon }), false);
  assert.equal(F.frontQuotable({ coach_id: "sleep_coach", move: "reply", text: "Bedtime moved earlier this week.", reader: ["hedge"] }), false);
  assert.equal(F.frontQuotable({ coach_id: "sleep_coach", move: "reply", text: "Bedtime moved earlier this week." }), true);
});

test("the record's comparison names the guess and the gap, or says there is none yet", () => {
  const d = B.record.data;
  assert.match(P.recordLine(B.record), /^\d+ of \d+ checked calls right\. A guess that every call has a \d+% chance of coming true does (about as well|better|worse)\.$/);
  assert.equal(P.guessClause({ ...d, brier_skill: null }), "There is no comparison with a guess yet.");
  assert.match(P.guessClause({ ...d, skill_n: d.decided + 1 }), /A guess that every call has the same chance of coming true/);
});

test("Coaches: one rule for every row — the count, no bar; the lead says no checked calls", () => {
  const html = P.teamHTML(load("coaches"));
  assert.doesNotMatch(html, /ck-meter/);
  assert.doesNotMatch(html, /no bets/);
});

test("Story on the capture's own day: the next week has not published, and the next date is ahead of the day", () => {
  const html = P.storyChapterHTML(EDITION, B, POSTS, load("episodes"));
  assert.match(html, new RegExp(`Week ${n + 1} (is waiting for Matthew’s approval|is held before publishing)`));
  assert.match(html, new RegExp(`week ${n + 2}’s draft is due`));
  const due = B.next.data.chapter.data.date;
  assert.ok(due > EDITION.as_of, `${due} is after ${EDITION.as_of}`);
  assert.doesNotMatch(html, /New this week/);
});

// ── round 3 ─────────────────────────────────────────────────────────────────────
const C = await import("../../site/assets/js/ck_call.js");

test("Front: 'this week' for the miss is the week the page prints; outside it the heading says so", () => {
  const calls = { state: "ok", calls: load("calls").calls };
  const days = B.week.data.days;
  const pick = C.lastCallPick(calls, EDITION.as_of, { since: days[0] });
  if (pick.kind === "recent") assert.ok(pick.call.settled_date >= days[0] && pick.call.settled_date <= EDITION.as_of, pick.call.settled_date);
  const slots = P.frontReadSlots(EDITION, B, "/next/v8/");
  const settled = /Settled [A-Z][a-z]+day, ([A-Z][a-z]+ \d+)/.exec(slots["ck-call"]);
  if (/this week/.test(slots["ck-miss-heading"]) && settled) {
    const inWeek = days.some((d) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" }) === settled[1]);
    assert.ok(inWeek, `${settled[1]} is inside the printed week`);
  }
});

test("Coaches: one short job form for every coach", () => {
  for (const job of Object.values(P.COACH_JOBS)) assert.ok(job.split(" ").length <= 4 && !/\./.test(job), job);
});

// ── round 4 ─────────────────────────────────────────────────────────────────────
const V = await import("../../site/assets/js/ck_verdict.js");
test("a call sentence says whose reading it was: Matthew's, never a bare 'his' beside a coach's name", () => {
  assert.equal(V.matthewsCall("Henning Brandt called his weight at about 307.2 lb."), "Henning Brandt called Matthew’s weight at about 307.2 lb.");
  const html = P.callVerdictsHTML(load("calls"), "/next/v8/");
  assert.doesNotMatch(html, /called his\b/);
});
test("Front, no bet and no exchange: the newest quotable line keeps the coaches' voice; else the no-bet line", () => {
  const quietDay = { ...B, moves: { state: "ok", data: { days: [{ state: "ok", date: EDITION.as_of, lines: [{ coach_id: "sleep_coach", coach: "Lisa Park", move: "call", text: "Bedtime moved earlier this week." }] }] } } };
  const out = P.frontReadSlots(EDITION, quietDay, "/next/v8/");
  assert.match(out["ck-argument"], /Bedtime moved earlier this week\./);
  assert.equal(out["ck-argue-heading"], "The latest from the coaches.");
  const silent = { ...B, moves: { state: "ok", data: { days: [] } } };
  assert.equal(P.frontReadSlots(EDITION, silent, "/next/v8/")["ck-argue-heading"], "No open bet between them this week.");
});

// ── site-to-A round 1, lane D (2026-10-18): the sheet, how it's built, the appendix, a call, a coach ──
const S = await import("../../site/assets/js/ck_sheet.js");
const BU = await import("../../site/assets/js/ck_built.js");
const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site");
const page = (name) => readFileSync(join(SITE, "next", "v8", name, "index.html"), "utf8");
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("Sheet: each area is the kit's record row — name, level at the right, one plain sentence — not a four-bucket formula", () => {
  const character = load("character");
  const html = S.areasHTML(character);
  assert.match(html, /^<ul class="ck-coach ck-coach--record">/);
  const rows = [...html.matchAll(/<li>(.*?)<\/li>/g)].map((m) => m[1]);
  assert.equal(rows.length, character.pillars.length);
  for (const row of rows) {
    assert.match(row, /^<span class="ck-coach__name">[^<]+<\/span><span class="ck-coach__job">[^<]+<\/span>(<span class="ck-coach__record">Level \d+<\/span>)?$/, row);
    assert.doesNotMatch(row, /Helping:|Holding it back:|Not done or not logged:|No data yet:/, "the bucket list is not in the row");
  }
  const both = character.pillars.find((p) => (p.drivers?.top || []).length && (p.drivers?.dragging || []).length);
  assert.ok(both, "the capture has an area with a helper and a drag");
  assert.equal(S.areaBrief(both), `Helped most by ${S.driverWords(both.drivers.top)[0]}; held back most by ${S.driverWords(both.drivers.dragging)[0]}.`);
  assert.equal(S.areaBrief({ ...both, drivers: { top: both.drivers.top } }), `Helped most by ${S.driverWords(both.drivers.top)[0]}.`);
  assert.equal(S.areaBrief({ ...both, coverage_hold: true }), "", "a held area's drivers are not named as helping");
  assert.equal(S.areaLevel(character.pillars.find((p) => p.not_instrumented)), "", "an unmeasured area carries no level figure");
});

test("Sheet: the score and its move share one precision, so the move can be read off two days' scores", () => {
  assert.equal(S.areaSentence({ level: 22, raw_score: 80.5, score_delta: -0.5 }), "Score 80.5 of 100, down 0.5 on the day.");
  assert.equal(S.areaLine({ level: 22, raw_score: 80.5, score_delta: -0.5 }), "Level 22. Score 80.5 of 100, down 0.5 on the day.");
  assert.doesNotMatch(S.areasHTML(load("character")), /Score \d+ of 100/, "no whole score beside a tenth-of-a-point move");
});

test("Sheet: an area on hold for thin data that still counts toward the level is said so beside the level", () => {
  const character = load("character");
  const held = character.pillars.filter((p) => p.coverage_hold && !p.not_instrumented);
  assert.ok(held.length >= 1, "the capture has a held area (metabolic)");
  assert.equal(S.compositeNote(character), "Metabolic health is on hold for thin data, yet its score still counts toward the level.");
  assert.equal(S.compositeNote({ pillars: character.pillars.filter((p) => !p.coverage_hold) }), "", "no held area, no note");
  assert.match(S.compositeNote({ pillars: [{ name: "metabolic", coverage_hold: true }, { name: "mind", coverage_hold: true }] }), /^Metabolic health and Mind are on hold for thin data, yet their scores still count toward the level\.$/);
});

test("Sheet: one sentence before the areas; the rule a level moves by sits one tap deeper", () => {
  const html = page("sheet");
  const areas = html.slice(html.indexOf("The seven areas"), html.indexOf('id="ck-areas"'));
  const intro = [...areas.matchAll(/<p class="ck-soft">([^<]*)<\/p>/g)].map((m) => m[1]);
  assert.equal(intro.length, 1);
  assert.equal((intro[0].match(/\./g) || []).length, 1, "one sentence");
  assert.match(html, /<details>\s*<summary>How a level moves<\/summary>/);
  assert.match(html, /<h1>The whole of it, so far\.<\/h1>/);
  assert.ok(html.includes('id="ck-sheet-late"') && html.indexOf('id="ck-sheet-late"') > html.indexOf('id="ck-areas"'), "the late-sources caveat sits under the areas, not stacked under the level");
});

test("Built: one dated fold fact at the top; a section carries at most one 'as of'", () => {
  const src = { stats: load("platform_stats"), receipts: load("receipts"), predictions: load("predictions"), coaches: load("coaches") };
  assert.match(BU.foldDay(src), /^[A-Z][a-z]+day, [A-Z][a-z]+ \d+$/);
  assert.equal(BU.foldDay({}), "");
  const numbers = textOf(BU.numbersHTML(src));
  assert.equal((numbers.match(/As of /g) || []).length, 0, numbers);
  assert.match(numbers, /Counted [A-Z][a-z]+ \d+, from the code\./);
  assert.match(numbers, /Checked to [A-Z][a-z]+ \d+\. Code does the grading/);
  assert.equal((textOf(BU.costHTML(src.receipts)).match(/As of /g) || []).length, 1);
  assert.match(page("built"), /<span class="ck-header__day" id="ck-day"><\/span>/);
});

test("Built: the tier is defined in plain words where it is first named, with spend and forecast side by side and dated", () => {
  const rc = load("receipts");
  const open = BU.costHTML(rc).split("<details>")[0];
  assert.match(open, new RegExp(`As of [A-Z][a-z]+ \\d+, \\$${rc.month_to_date_usd.toFixed(2)} is spent this month, and the forecast for [A-Z][a-z]+ \\d+ is \\$${rc.projected_month_end_usd.toFixed(2)}, (under|above) the ceiling\\. The system is at tier ${rc.tier}: ${BU.TIER_WORDS[rc.tier]}\\.`));
  assert.doesNotMatch(open, /at their pace/, "the forecast's arithmetic stays one tap deeper");
  for (const [tier, words] of Object.entries(BU.TIER_WORDS)) assert.match(BU.costHTML({ ...rc, tier: Number(tier) }), new RegExp(`The system is at tier ${tier}: ${words.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.`));
  assert.match(BU.costHTML({ ...rc, tier: 0 }), /Nothing is paused\./);
  const text = textOf(page("built"));
  assert.ok(text.indexOf("sets a tier from the forecast’s share of the ceiling") < text.indexOf("Tier 1 From about 73%"));
});

test("Built: what runs is the kit's numbered row list in pipeline order, not a hand-drawn picture; prose is full width; incidents closed", () => {
  const html = page("built");
  assert.doesNotMatch(html, /<svg/);
  const steps = /<ul class="ck-rows ck-rows--steps">(.*?)<\/ul>/s.exec(html);
  assert.ok(steps, "the numbered steps");
  const rows = [...steps[1].matchAll(/<li><span>([^<]*)<\/span><\/li>/g)].map((m) => m[1]);
  assert.equal(rows.length, 5);
  assert.match(rows[0], /^Devices and apps/);
  assert.match(rows[1], /^One store/);
  assert.match(rows[2], /^AI coaches/);
  assert.match(rows[3], /checker/);
  assert.match(rows[4], /^The site/);
  for (const r of rows) assert.ok(r.split(" ").length <= 10, r);
  const who = /Who decides<\/p>(.*?)<\/section>/s.exec(html)[1];
  assert.doesNotMatch(who, /ck-rows/, "the four paragraphs are full width, not a narrow value column");
  assert.equal((who.match(/<p>/g) || []).length, 4);
  assert.doesNotMatch(html, /<details open>/);
  const broke = /What broke<\/p>(.*?)<\/section>/s.exec(html)[1];
  assert.doesNotMatch(broke, /ck-rows__key/, "an incident's body is full width under its summary");
  assert.equal((broke.match(/<details>/g) || []).length, 4);
  assert.equal((broke.match(/before day one/g) || []).length, 3, "the three failures before 2026-09-06 are labelled");
  assert.doesNotMatch(broke, /\b(Sept|Oct|Aug)\b/, "full month names, the one date rule");
});

test("Built: the first-person draft sits under the fold with one draft mark, and the approval rule is said twice, not three times", () => {
  const html = page("built");
  const text = textOf(html);
  assert.ok(html.indexOf('id="ck-draft"') < html.indexOf("The numbers</p>"), "the draft is above the numbers");
  assert.equal((text.match(/Draft wording\. Matthew has not rewritten this yet\./g) || []).length, 1);
  assert.match(html, /<p class="ck-small">Preview\.<\/p>\s*<\/div>/, "the footer is the short preview mark");
  assert.equal((text.match(/permitted to do/g) || []).length, 2, text.match(/[^.]*permitted to do[^.]*\./g));
  const draft = /<section class="ck-section" id="ck-draft">(.*?)<\/section>/s.exec(html)[1];
  const body = /<p>([^<]+)<\/p>/.exec(draft)[1];
  assert.equal((body.match(/[.!?](\s|$)/g) || []).length, 2, "the draft is two sentences, not three paragraphs");
});

test("Appendix: a jump list of plain links reaches each kind, Tools first, with the replaced-layouts group's empty sentence", () => {
  const html = page("appendix");
  const jump = /<p class="ck-soft">((?:<a class="ck-link" href="#kind-[a-z]+">[^<]+<\/a>(?: · )?)+)<\/p>/.exec(html);
  assert.ok(jump, "the jump list is one paragraph of kit links");
  const targets = [...jump[1].matchAll(/href="#(kind-[a-z]+)"/g)].map((m) => m[1]);
  assert.equal(targets[0], "kind-tools");
  for (const id of targets) assert.ok(html.includes(`<section class="ck-section" id="${id}">`), id);
  const sections = [...html.matchAll(/<section class="ck-section" id="(kind-[a-z]+)">/g)].map((m) => m[1]);
  assert.deepEqual(sections, targets, "the links are in the sections' order");
  assert.match(html, /id="kind-replaced">\s*<p class="ck-label">Replaced layouts<\/p>\s*<p class="ck-soft">The home page’s earlier layout will be listed here once the cut-over copies it\. Nothing is here yet\.<\/p>/);
  assert.doesNotMatch(html, /<a class="ck-link" href="\/next\/v8\/">Back<\/a>/, "no second back link under the list");
});

test("Appendix: an earlier version of a v8 page says so, and a codename is small print under a plain title", () => {
  const html = page("appendix");
  const rows = [...html.matchAll(/<li><a class="ck-coach__name ck-link" href="([^"]+)">([^<]+)<\/a><span class="ck-coach__job">([^<]+)<\/span><\/li>/g)].map((m) => ({ url: m[1], title: m[2], line: m[3] }));
  const row = (url) => rows.find((r) => r.url === url);
  assert.match(row("/data/character/").line, /Earlier version of “The whole of it”, superseded\.$/);
  assert.match(row("/method/build/").line, /Earlier version of “How it’s built”, superseded\.$/);
  assert.match(row("/coaching/team/").line, /Earlier version of “The AI coaches”, superseded\.$/);
  for (const [url, title, codename] of [["/story/membrane/", "Posts and replies", "Membrane"], ["/method/wrong/", "Every time the AI was wrong", "Wrong page"], ["/story/theme-river/", "Journal themes, charted", "Theme river"], ["/data/horizons/", "A weekly pick to read or watch", "Horizons"], ["/method/explorer/", "The raw record, as a table", "Explorer"]]) {
    assert.equal(row(url).title, title, url);
    assert.ok(row(url).line.endsWith(`Called “${codename}” on the page.`), row(url).line);
  }
  for (const r of rows) assert.doesNotMatch(r.title, /^(Membrane|Theme river|Horizons|Wrong page|Explorer|Mirror|Broadcast)$/, "no codename as a title");
});

test("Call: a bet's short sentence carries the unit its long sentence names; a short sentence with no unit in the long one is left alone", () => {
  const bet = load("calls").calls.find((c) => c.id.startsWith("bet-20261016"));
  assert.ok(bet && /as a percentage/.test(bet.called) && /at or above 26 on/.test(bet.called_short), "the capture's bet drops the unit on the short form");
  assert.equal(C.calledShortWithUnit(bet), bet.called_short.replace("at or above 26 on", "at or above 26% on"));
  assert.equal(C.calledShortWithUnit({ called_short: "X bet on whether it would be at or above 26 on October 16.", called: "X bet on whether the share would be at or above 26 on October 16." }), "X bet on whether it would be at or above 26 on October 16.", "no unit named, none invented");
  assert.equal(C.calledShortWithUnit({ called_short: "at or above 190 g on October 16.", called: "(in grams) at or above 190 g" }), "at or above 190 g on October 16.", "a unit already there is not doubled");
  assert.equal(C.calledShortWithUnit({ called_short: "below 305 by October 20.", called: "his weight (in pounds) below 305" }), "below 305 lb by October 20.");
  assert.equal(C.calledShortWithUnit(null), "");
  assert.match(page("call"), /<h1 id="ck-title">[^<]+<\/h1>\s*<p class="ck-soft">Average Joe Matt is one man’s public health experiment/, "the frame sentence under the h1 stays");
});

test("Coach: the footer is the short preview mark, and the page says what a coach page is in both states", () => {
  const html = page("coach");
  assert.match(html, /<p class="ck-small">Preview\.<\/p>\s*<\/div>/);
  assert.doesNotMatch(html, /first-person line/);
  assert.match(html, /<h1 id="ck-title">An AI coach<\/h1>\s*<p class="ck-soft">One of the AI coaches reading Matthew’s numbers in public: who it is, its checked calls and what it is watching\.<\/p>\s*<div class="ck-section ck-section--tight" id="ck-who">/, "static, so the not-found state keeps it");
});

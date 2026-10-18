// tests/js/ck_red_team_4586.test.mjs — the four v8 preview pages against the 2026-10-17 red team
// (#4586). Each test names the finding it holds: an honest held state on Story, the weight rows'
// shape, the teaser that agrees with the page, no empty bet section, the pre-start sensor label.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// SITE is read by a test registered above the lane-D block that first declared it (item 8 / round 2 reads
// clean.css). A test can start while this module is suspended at a later top-level `await import`, so a
// `const` declared below that await is in its temporal dead zone for any earlier-registered test — the
// CI runner hit exactly that ("Cannot access 'SITE' before initialization"). Declared before the first await.
const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site");

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

test("Story: a held week is a served fact or the chronicle's own marker, never calendar arithmetic", () => {
  assert.ok(n >= 1, "the capture's latest chapter is a numbered week");
  // Site-to-A round 1: the line said "Week 6 is waiting for Matthew’s approval" from the date gap, on the
  // night week 6 published. With nothing served about a held week the page says nothing of one.
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 3) }, POSTS), "");
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 11) }, POSTS), "", "eleven days on is not a held week");
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 40) }, POSTS), "");
  // The served status (`chronicle.latest.status`, lane E), on whichever document carries it.
  const nextB = { state: "ok", data: { chapter: { state: "ok", data: { date: later(latestDate, 15), drafted_not_promised: true } } } };
  const held = (status, week) => ({ as_of: later(latestDate, 11), chronicle: { latest: { status, week } } });
  assert.equal(P.heldChapterLine(chapter, held("held", n + 1), POSTS), `Week ${n + 1} is written and held before publishing.`);
  assert.match(P.heldChapterLine(chapter, held("awaiting_approval", n + 1), POSTS, nextB), new RegExp(`^Week ${n + 1} is written and held before publishing; its draft was due [A-Z][a-z]+day, [A-Z][a-z]+ \\d+\\.$`));
  assert.equal(P.heldChapterLine(chapter, held("pending"), POSTS), "The next chapter is written and held before publishing.", "no week named: no week invented");
  assert.equal(P.heldChapterLine(chapter, held("published", n), POSTS), "", "published: nothing is held");
  assert.equal(P.heldChapterLine(chapter, held("something_else", n + 1), POSTS), "", "an unrecognised status claims nothing");
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 11) }, { ...POSTS, chronicle: { latest: { status: { state: "held" } } } }), "The next chapter is written and held before publishing.", "the journal may carry it, as an object");
  assert.deepEqual(P.chronicleStatus({ chronicle: { latest: { status: "Held", week: 6 } } }, null, null), { status: "held", week: 6 });
  assert.equal(P.chronicleStatus({}, POSTS, chapter), null);
  // The chronicle's own marker still wins over silence.
  const marked = { ...POSTS, pending: { week: n + 1, reason: "story_door_hold" } };
  assert.equal(P.heldChapterLine(chapter, { as_of: later(latestDate, 3) }, marked), `Week ${n + 1} is held before publishing.`);
  assert.equal(P.heldChapterLine({ state: "unavailable", data: null }, held("held", n + 1), POSTS), "");
});

test("Story: the podcast line says held when the episode list marks this week held", () => {
  const episodes = { episodes: [], pending: { week: n, reason: "held_for_review" } };
  assert.equal(P.podcastHeld(episodes, n), true);
  assert.equal(P.podcastHeld({ ...episodes, pending: { week: n, reason: "other" } }, n), false);
  assert.equal(P.podcastHeld(episodes, n + 1), false);
  assert.match(P.playerHTML({ state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null }, { held: true }), /held for review/);
  assert.match(P.playerHTML({ state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null }), /No podcast episode/);
});

test("Story: a served held line sits beside the next date, said once", () => {
  const edition = { ...EDITION, as_of: later(latestDate, 11), chronicle: { latest: { status: "held", week: n + 1 } } };
  const noPod = { ...chapter, data: { ...chapter.data, podcast: { state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null } } };
  const html = P.storyChapterHTML(edition, { ...B, chapter: noPod }, POSTS, { episodes: [], pending: { week: n, reason: "held_for_review" } });
  assert.match(html, new RegExp(`Week ${n + 1} is written and held before publishing; its draft was due`));
  assert.match(html, /held for review/);
  assert.doesNotMatch(html, /The next draft is due/, "the next date is said once");
});

test("Story: the chapter's dek is printed as served, never recomputed", () => {
  // Site-to-A round 1: the teaser rewrote "crossed 310 pounds … 18.5 pounds gone" to "went below 310 … 18.4"
  // from rounded values — an edit to a quoted sentence of the chapter. The dek is the chapter's own words.
  const dek = "Rest days, while the scale crossed 310 pounds for the first time, suggesting 18.5 pounds gone…";
  assert.equal(P.teaserText(dek), dek);
  assert.equal(P.teaserText(dek, { chapterLb: 308.9, startLb: 327.3 }), dek, "a caller's numbers change nothing");
  const html = P.storyChapterHTML(EDITION, B, POSTS, load("episodes"));
  assert.ok(html.includes(`<p class="ck-premise ck-soft">${B.chapter.data.dek}</p>`), "the served dek, whole");
  assert.doesNotMatch(html, /went below|went above|18\.4 pounds/);
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

test("Start: a chapter row prints the chapter's own change, the window named, no second computation (round 2, G9/G10)", () => {
  const html = P.recapHTML(P.postsInOrder(POSTS));
  assert.doesNotMatch(html, /\blbs\b/, "lb everywhere");
  assert.doesNotMatch(html, /this week/, "a historical row never says 'this week'");
  // Every week's row carries exactly the change its served stats line carries — "(-3.5 this week)"
  // becomes "down 3.5 that week" — so a reader subtracting the printed weights row to row lands on it.
  for (const p of P.postsInOrder(POSTS)) {
    const m = /\(([-−+]?)(\d+(?:\.\d+)?) this week\)/.exec(p.stats_line || "");
    if (!m) continue;
    const want = `${m[1] === "-" || m[1] === "−" ? "down" : "up"} ${Number(m[2]).toFixed(1)} that week`;
    assert.equal(P.servedChange(p.stats_line), want, p.label);
    assert.ok(html.includes(`${/([\d.]+)\s*lbs/.exec(p.stats_line)[1]} lb, ${want}`), `${p.label}: ${want}`);
    assert.match(html, new RegExp(`<span class="ck-small">${/Day \d+ to Day \d+/.exec(p.stats_line)[0]} · `), `${p.label}: the window is named`);
  }
  // The specimen rows: week 2's served 8.4 is the fall from the first weigh-in (327.3 → 318.9), which
  // round 1's inside-the-window arithmetic printed as 0.8.
  assert.match(html, /318\.9 lb, down 8\.4 that week/);
  assert.match(html, /315\.0 lb, down 3\.9 that week/);
  assert.doesNotMatch(html, /down 0\.8|down 2\.3|down 3\.1|down 2\.5/, "none of round 1's recomputed deltas");
  assert.equal(P.servedChange("Day 4 to Day 10 · 318.9 lbs (+0.0 this week)"), "the same as the week before");
  assert.equal(P.servedChange("Day 4 to Day 10 · 318.9 lbs (+1.2 this week)"), "up 1.2 that week");
  assert.equal(P.servedChange("Day 1 to Day 3 · 327.3 lbs at the first weigh-in"), "", "no served change: none invented");
  assert.equal(P.chapterStatLine({ label: "Week 1", stats_line: "Day 1 to Day 3 · 327.3 lbs at the first weigh-in · 2 training sessions" }), "Day 1 to Day 3 · 327.3 lb at the first weigh-in · 2 training sessions.");
  assert.equal(typeof P.windowChange, "undefined", "the second computation is gone");
  // Each row is a kit chapter row whose title is a door; each prologue says what it is.
  assert.match(html, /<ul class="ck-rows ck-rows--chapters">/);
  assert.match(html, /<a href="\/journal\/posts\/week-05\/">Nine Days and No Rest<\/a>/);
  assert.match(html, /Who he was before the record\./);
  assert.match(html, /The plan, written before day one\./);
  assert.doesNotMatch(html, /Before day one\./, "no prologue falls back to the shared line on the capture");
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

test("Story on the capture's own day: the latest chapter and its date, the next date ahead, and no inferred held week", () => {
  const html = P.storyChapterHTML(EDITION, B, POSTS, load("episodes"));
  assert.match(html, new RegExp(`Latest chapter · Week ${n} \\(written [A-Z][a-z]+ \\d+\\)`), "the dated fact the served data supports");
  assert.doesNotMatch(html, new RegExp(`Week ${n + 1}|waiting for Matthew’s approval|held before publishing`), "no held week is inferred (week 6 published 2026-10-18T04:29Z)");
  assert.match(html, /The next draft is due [A-Z][a-z]+day, [A-Z][a-z]+ \d+; it publishes once Matthew approves it\./);
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
  // Site-to-A round 1 (front:F2, item 2): the heading is the section's name; the null bet is one soft line under the voice.
  assert.equal(out["ck-argue-heading"], "The coaches.");
  assert.match(out["ck-argument"], /<p class="ck-soft">No open bet between them this week\.<\/p>$/);
  const silent = { ...B, moves: { state: "ok", data: { days: [] } } };
  const quiet = P.frontReadSlots(EDITION, silent, "/next/v8/");
  assert.equal(quiet["ck-argue-heading"], "The coaches.");
  assert.equal(quiet["ck-argument"], '<p class="ck-soft">No open bet between them this week.</p>');
  // The capture itself: every line in the window is 36-51 words against the 28-word cap and today's is the mind
  // coach's, so the front has no quotable line — the section still never opens on the null state.
  const wire = P.frontReadSlots(EDITION, B, "/next/v8/");
  assert.doesNotMatch(wire["ck-argue-heading"], /^No open bet/);
  assert.match(wire["ck-argument"], /No open bet between them this week\./);
  // With a bet open, no null-bet sentence appears anywhere.
  const bet = { ...B, next: { state: "ok", data: { ...B.next.data, bet: { state: "ok", data: { question: "Will he sleep more?", settle_date: "2026-10-25", sides: [{ coach: "Lisa Park", side: "yes" }, { coach: "Max Reyes", side: "no" }] } } } } };
  assert.doesNotMatch(P.frontReadSlots(EDITION, bet, "/next/v8/")["ck-argument"] || "", /No open bet/);
});

// ── site-to-A round 1, lane A: the front page and Start here (#4580, #4590) ──────────────────
const V8 = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "next", "v8");
const shell = (page) => readFileSync(join(V8, page, "index.html"), "utf8");

test("item 1: the two premise sentences are the drafts posted on #4590, marked as drafts until his word", () => {
  const front = shell("");
  const start = shell("start");
  assert.match(front, /<p class="ck-premise" data-ck-draft="premise">I’m Matthew\. I’m trying to get from 327 pounds to 185 and to get my life back with it, in public, because I do better when someone is watching\. A team of AI coaches I built predicts how it will go, and code checks every call\.<\/p>/);
  assert.match(start, /<p class="ck-premise" data-ck-draft="premise">I’m Matthew\. The weight was never really about food, so this is me measuring the whole thing out loud: what my scale, wrist strap, bed sensor and food log record each day, what the AI coaches I built with Claude make of it, and whether they were right\.<\/p>/);
  for (const html of [front, start]) {
    const note = /<p class="ck-small">(Preview\. [^<]*)<\/p>\s*<\/div>/.exec(html);
    assert.ok(note, "the footer keeps its draft note");
    assert.equal((note[1].match(/[.!?](\s|$)/g) || []).length, 2, `one short sentence after "Preview.": ${note[1]}`);
    assert.match(note[1], /draft/i);
  }
  assert.doesNotMatch(front, /a program grades/, "front:F8 — the grader is code");
  assert.match(front, /<p class="ck-label">Graded by code<\/p>/);
});

test("item 3: one sayable guess sentence on the front and Start, the exact rate one tap deeper; a served baseline is printed", () => {
  const html = P.recordHTML(B.record, { href: "/next/v8/coaches/" });
  assert.match(html, /^<a class="ck-link" href="\/next\/v8\/coaches\/">76 of 183 checked calls right\.<\/a> The coaches do not beat a simple guess yet\.<details class="ck-small"><summary>The exact rate<\/summary><p>A guess that every call has a 42% chance of coming true does about as well\.<\/p><\/details>$/);
  assert.equal(P.frontSlots(EDITION, B, "/next/v8/")["ck-record"], html);
  assert.equal(P.recordHTML(B.record).startsWith("76 of 183 checked calls right. The coaches"), true, "Start: no door on the count, the page has its own");
  assert.equal(P.guessSentence({ ...B.record.data, beats_simple_guess: true }), "The coaches beat a simple guess.");
  assert.equal(P.guessSentence({ ...B.record.data, brier_skill: null }), "There is no comparison with a guess yet.");
  // Lane E's served shapes (lambdas/web/record_words.py): comparison_text is the one sentence, baseline.text the exact rate.
  assert.equal(P.guessSentence({ ...B.record.data, comparison_text: "Too few checked calls yet to compare the coaches with a simple guess." }), "Too few checked calls yet to compare the coaches with a simple guess.", "lane E's served sentence wins");
  assert.equal(P.guessSentence(B.record.data), "The coaches do not beat a simple guess yet.", "the capture's older 'So far they…' form is re-said");
  const served = { ...B.record.data, comparison_text: "The coaches do not beat a simple guess yet.", baseline: { rule: "base_rate", rate: 0.415, rate_pct: 42, text: "A guess that every call has a 42% chance of coming true does about as well." } };
  assert.match(P.recordHTML({ ...B.record, data: served }), /<details class="ck-small"><summary>The exact rate<\/summary><p>A guess that every call has a 42% chance of coming true does about as well\.<\/p><\/details>$/);
  assert.equal(P.exactRateText({ ...B.record.data, baseline: { rate: 0.42 } }), P.guessClause(B.record.data), "a baseline with no text: the clause computed here");
  const failed = { state: "unavailable", absent_text: "The record is not here.", data: null };
  assert.equal(P.recordHTML(failed, { href: "/x/" }), "The record is not here.");
});

test("item 4: Go deeper leads with the latest chapter — chronicle.latest when served, else the chapter block; no held claim anywhere", () => {
  const front = shell("");
  const deeper = /<ul class="ck-rows ck-rows--deeper">\s*<li id="ck-chapter-row">/.test(front);
  assert.ok(deeper, "the chapter row is the first row");
  assert.equal(P.latestChapterBlock(B), B.chapter, "no served latest: the chapter block as today");
  // Lane E: chapter.data.latest {week, label, date, status} over the block's own label and date.
  const latest = { week: 6, label: "Week 6", date: "2026-10-13", status: "published" };
  const served = { ...B, chapter: { ...B.chapter, data: { ...B.chapter.data, title: "The Quiet Accumulation", url: "/journal/posts/week-09/", read_minutes: 7, latest, held: null, next_due: "2026-10-21" } } };
  const row = P.frontSlots(EDITION, served, "/next/v8/")["ck-chapter-row"];
  assert.match(row, /Week 6 · “The Quiet Accumulation”/);
  assert.match(row, /The latest chapter · October 13 · 7 min/);
  assert.equal(P.latestChapterBlock({ ...B, chapter: { ...B.chapter, data: { ...B.chapter.data, latest: { status: "published" } } } }).data.date, B.chapter.data.date, "a latest with no date or label changes nothing");
  assert.doesNotMatch(row, /held|waiting/);
  for (const page of ["", "start"]) assert.doesNotMatch(shell(page), /waiting for approval|held before publishing/);
  assert.doesNotMatch(shell("start"), /Open now/, "start:S3 — the date is the chapter list's tail, not a section");
  assert.match(shell("start"), /<div id="ck-recap"><\/div>\s*<p class="ck-small" id="ck-open"><\/p>/);
});

test("item 5: a settled miss is headed by the week it was checked in; the words row has no door to a page that says nothing new", () => {
  const slots = P.frontReadSlots(EDITION, B, "/next/v8/");
  if (/this week/.test(slots["ck-miss-heading"])) assert.equal(slots["ck-miss-heading"], "The clearest miss checked this week.");
  assert.match(slots["ck-call"], /Settled [A-Z][a-z]+day, [A-Z][a-z]+ \d+/, "the card carries its own date");
  const front = P.frontSlots(EDITION, B, "/next/v8/");
  assert.equal(B.his_words.state, "stale", "the capture's words are stale");
  assert.equal(front["ck-words-row"], '<span class="ck-rows__key">In his own words</span><span id="ck-words-absent"></span>', "the row keeps its key and loses its door");
  assert.ok(Object.keys(front).indexOf("ck-words-row") < Object.keys(front).indexOf("ck-words-absent"), "the row is filled before its sentence slot");
  assert.match(front["ck-words-absent"], /^Nothing new since [A-Z][a-z]+day, [A-Z][a-z]+ \d+\.$/, "the sentence keeps its own date");
  const fresh = { ...B, his_words: { state: "ok", data: { text: "Right now I still feel good.", date: "2026-10-17" } } };
  assert.equal(P.frontSlots(EDITION, fresh, "/next/v8/")["ck-words-row"], null, "fresh words lead the page; the row goes whole");
});

test("item 6: Start carries the Follow block, the same markup as the front page, with the feeds beside the button", () => {
  const block = (html) => /<section class="ck-section ck-follow" id="follow">[\s\S]*?<\/section>/.exec(html)[0];
  const front = block(shell(""));
  const start = block(shell("start"));
  assert.equal(start, front);
  assert.match(start, /<a class="ck-btn" href="\/subscribe\/">Follow by email<\/a>/);
  assert.match(start, /href="\/rss\.xml">RSS<\/a>/);
  assert.match(start, /href="\/panelcast\/feed\.xml">the podcast feed<\/a>/);
  const main = /<main[\s\S]*<\/main>/.exec(shell("start"))[0];
  assert.ok(main.trimEnd().endsWith("</section>\n  </main>") && main.lastIndexOf('id="follow"') > main.lastIndexOf('id="ck-recap"'), "after the last section");
  for (const page of ["", "start"]) assert.match(shell(page), /<link rel="alternate" type="application\/rss\+xml"[^>]*href="\/panelcast\/feed\.xml">/);
});

test("item 8 / round 2 (front): the mark names its floor in ONE line under it — top is the start, floor is the goal — never a left/right pair that reads as a time axis", () => {
  const t = B.today.data;
  const ends = F.markEndsHTML(t.start_weight_lbs, t.goal_weight_lbs);
  assert.equal(ends, '<div class="ck-ends"><span>Each column runs from 327.3 lb, the start, at the top to 185 lb, the goal, at the floor.</span></div>');
  assert.equal((ends.match(/<span>/g) || []).length, 1, "one span, one line");
  // The legend's "grey" is the kit's faint ink, not the hairline colour that did not read as grey.
  const css = readFileSync(join(SITE, "assets", "css", "clean.css"), "utf8");
  assert.match(css, /\.ck-mark__left \{ fill: var\(--ck-faint\); \}/);
  assert.match(shell(""), /green is gone, grey is left to 185/);
  assert.ok(P.frontSlots(EDITION, B, "/next/v8/")["ck-mark"].endsWith(ends));
  assert.equal(F.markEndsHTML(null, 185), "");
  assert.equal(F.markEndsHTML(180, 185), "", "a start under the goal names no floor");
  // front:F5: the caption sits under the mark, then the record — not the record between them.
  const front = shell("");
  assert.ok(front.indexOf('id="ck-mark"') < front.indexOf("One column a day") && front.indexOf("One column a day") < front.indexOf('id="ck-record"'));
});

// ── site-to-A round 1 (2026-10-18, the verified shared-helper defects of #4580, lane J) ──────
// One case per item, each on the committed fixtures: the chart's frame, the unit agreement, the
// Food row's dot, the trend index rows, the call page rendered once, the sheet's headline, the
// coach not-found doors. (The dek passthrough and the Story status binding are the tests above.)
const D = await import("../../site/assets/js/ck_depth.js");
const S = await import("../../site/assets/js/ck_sheet.js");
const K = await import("../../site/assets/js/ck_coach.js");
const { TERMS } = await import("../../site/assets/js/ck_terms.js");

test("Start: the weight chart is framed start to goal, as the front page's mark is, with no fill and both ends labelled", () => {
  const series = B.week.data.weight_series;
  const t = B.today.data;
  const html = P.chartHTML(series, { start: t.start_weight_lbs, goal: t.goal_weight_lbs });
  assert.doesNotMatch(html, /<polygon/, "no fill under a level");
  // Round 2 (start, G10): no text inside the SVG — it scaled with the viewBox to ~6 px on a phone.
  // The frame's two rules are named in one kit text row under the dates.
  assert.doesNotMatch(html, /<text/, "no text inside the drawing");
  assert.ok(html.includes(`<div class="ck-ends"><span>The top rule is ${String(t.start_weight_lbs)} lb, the start; the dashed rule is ${String(Number(t.goal_weight_lbs))} lb, the goal.</span></div>`), html.slice(-300));
  assert.ok(html.indexOf("October 17 · ") < html.indexOf("The top rule is"), "the dates row first, the frame line under it");
  assert.doesNotMatch(P.chartHTML(series), /The top rule/, "no frame served: no frame line");
  // The same frame as the mark: the latest point sits the same share of the way down the frame
  // as the mark says is gone.
  const pts = [...series].sort((a, b) => a.date.localeCompare(b.date));
  const last = pts[pts.length - 1];
  const cy = Number(/<circle class="ck-chart__now" cx="[\d.]+" cy="([\d.]+)"/.exec(html)[1]);
  const cells = F.markDays(series, last.date, t.start_weight_lbs, t.goal_weight_lbs);
  const gone = cells[cells.length - 1].gone;
  assert.ok(Math.abs((cy - 20) / 122 - gone) < 0.002, `${(cy - 20) / 122} vs the mark's ${gone}`);
  assert.ok(gone < 0.3 && cy < 20 + 122 * 0.3, "a 25 lb drop is a small share of the frame, not most of it");
  assert.match(html, /aria-label="[^"]*in the frame from the start weight of 327\.3 to the goal of 185"/);
  // Without a start and goal the frame is the series' own range, still unfilled.
  const bare = P.chartHTML(series);
  assert.doesNotMatch(bare, /<polygon|the goal/);
  assert.match(bare, /ck-chart__line/);
});

test("one quantity, one unit: recovery is a percentage on the day line, the trend and the call card; a served unit wins", () => {
  assert.equal(F.recoveryShown("recovery 62 out of 100"), "recovery 62%");
  assert.equal(D.MEASURES.recovery.write(62), "62%");
  assert.equal(D.MEASURES.recovery.unit, "%");
  assert.doesNotMatch(D.MEASURES.recovery.about, /out of 100/);
  const calls = load("calls").calls;
  const recovery = calls.find((c) => c.kind === "number" && /recovery score/.test(c.called) && /^\d+(\.\d+)?$/.test(c.tolerance.text));
  assert.match(V.ruleFor(recovery, recovery.verdict === "right"), /^(not )?within [\d.]+% either way$/);
  assert.doesNotMatch(V.ruleFor(recovery, true), /points|out of 100/);
  assert.match(TERMS.find(([, term]) => term === "Recovery")[2], /percentage/);
  // The served unit, when the route names one (lane E of #4580), is read before any of this.
  assert.equal(V.ruleFor({ ...recovery, tolerance: { ...recovery.tolerance, unit: "points" } }, true), `within ${recovery.tolerance.text} points either way`);
  assert.equal(D.servedUnit("recovery", { pulse: { units: { recovery_pct: "points" } } }), "points");
  assert.equal(D.writerFor("recovery", { pulse: { units: { recovery_pct: "points" } } })(62), "62 points");
  assert.equal(D.writerFor("recovery", { pulse: {} })(62), "62%");
  // A unit in parentheses beside a number survives the rule reader; a gloss in parentheses does not.
  const bet = { kind: "bet", called: "Two coaches bet on whether his weight (lb) would be below 305 on October 16. Max Reyes said yes." };
  assert.equal(V.ruleFor(bet, true), "on whether his weight (lb) would be below 305 on October 16");
  const gloss = { kind: "bet", called: "Two coaches bet on whether his morning recovery score (his wrist strap’s morning score out of 100) would be below 70 on September 30. Max Reyes said yes." };
  assert.equal(V.ruleFor(gloss, true), "on whether his morning recovery score would be below 70 on September 30");
});

test("Week: a row with too little data takes the hollow dot and says so; every scored row has a dot", () => {
  const html = F.scorecardHTML(B.scorecard, "/next/v8/");
  const food = /<li><a class="ck-rows__key" href="[^"]*">Food<\/a><span>(.*?)<\/span><\/li>/.exec(html);
  assert.ok(food, "the Food row");
  assert.equal(B.scorecard.data.rows.food.data.verdict, "not_enough_data", "the capture's Food row is the thin one");
  assert.match(food[1], /^<i class="ck-dot ck-dot--off ck-dot--none" aria-hidden="true"><\/i><b>Too few days logged\.<\/b> 2 days logged; 5 are needed\. <span class="ck-small">Not enough data for a verdict\.<\/span>/);
  const rows = F.scorecardRows(B.scorecard).filter(({ row }) => row.state === "ok" && row.data && row.data.verdict_text);
  assert.equal((html.match(/<i class="ck-dot/g) || []).length, rows.length, "one dot per scored row, the thin one included");
  assert.equal((html.match(/ck-dot--none/g) || []).length, 1);
});

test("Trend index: each row carries its latest served reading and the day, and the page has a date line", () => {
  const src = { pulse: load("pulse_history"), nutrition: load("nutrition_overview"), training: load("training_overview") };
  const today = EDITION.as_of;
  const html = D.trendIndexHTML("/next/v8/", src, today);
  assert.match(html, /Weight · 302\.2 lb <span>October 17 <span aria-hidden="true">→<\/span><\/span>/);
  for (const [key, m] of Object.entries(D.MEASURES)) {
    const pts = D.seriesOf(key, src, today);
    const last = pts[pts.length - 1];
    assert.ok(last, `${key} has a served reading`);
    assert.ok(html.includes(`>${m.name} · ${m.write(last.value)} <span>${new Date(`${last.date}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" })} `), `${key}: its latest value and day`);
  }
  assert.match(D.trendIndexDay(src), /^Saturday, October 17 · Day 42$/);
  assert.equal(D.trendIndexDay({}), "");
  assert.doesNotMatch(D.trendIndexHTML("/next/v8/"), / · /, "with no bodies, the names alone");
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}|undefined|NaN/);
});

test("Call page: the call once at the top, the record as two sentences naming the coach, the guess's win on the verdict line", () => {
  const body = load("calls");
  const call = body.calls[0];
  assert.equal(call.kind, "number", "the capture's newest settled call is a number call");
  const claim = C.claimHTML(call, "/next/v8/");
  const outcome = C.outcomeHTML(call, "/next/v8/");
  const record = C.recordHTML(call, body);
  // The route's call sentence is the title; the card under it is who, when, and the coach's own words.
  assert.ok(claim.includes(`<b>“${call.claim}”</b>`));
  assert.ok(!claim.includes(call.called) && !claim.includes(call.called_short), "the call is not said again under its title");
  // The result is the heading; the outcome card is the verdict tag and its rule, with the guess's win.
  assert.ok(!outcome.includes(call.happened) && !outcome.includes(call.verdict_text), "neither the result nor the verdict sentence is restated");
  assert.match(outcome, /<p class="ck-soft">The allowed distance is [^<]+\. Graded on the reading for <a [^>]+>October 16<\/a>\. The simple guess was also right\.<\/p>/);
  assert.doesNotMatch(outcome, /Checked October/);
  const number = String(/about ([\d.]+)/.exec(call.called)[1]);
  const page = [call.called_short, claim, call.happened_short, outcome, record].join("");
  assert.equal(page.split(number).length - 1, 2, "the called number: once in the title, once in the coach's own words");
  // The record: the served count and the comparison's verdict per kind, naming the coach, and the served sentence one tap below.
  const p = /<p>([^<]+)<\/p><details><summary>The record by kind of call<\/summary>/.exec(record);
  assert.ok(p, record);
  assert.equal(p[1].split(/(?<=\.) /).length, 2, "two sentences");
  assert.ok(p[1].startsWith(`${call.coach_name}: `) && p[1].includes(`, ${call.coach_name} is `), p[1]);
  assert.doesNotMatch(p[1], /the coaches/);
  assert.ok(record.includes(`data-coach-comparison>${call.records[0].comparison.sentence}</p>`), "the served sentence, whole");
});

test("Sheet: 'Level 12 on Friday, October 16'; badges say lb and Level", () => {
  const character = load("character");
  const html = S.levelHTML(character);
  assert.match(html, new RegExp(`<p class="ck-big"><span>Level </span>${Math.round(character.character.level)}<span> on [A-Z][a-z]+day, [A-Z][a-z]+ \\d+</span></p>`));
  assert.doesNotMatch(html, /\d+<span> level/);
  const badges = S.badgesHTML(load("achievements"));
  assert.doesNotMatch(badges, /\blbs\b|Character Level/);
  assert.equal(S.badgeWords("Lost 10 lbs · Reached Character Level 2"), "Lost 10 lb · Reached Level 2");
});

test("Coach, no coach by that name: the eight coaches as doors, from the roster or the page's own eight ids", () => {
  const roster = load("coaches");
  const html = K.coachListHTML(roster, "/next/v8/");
  const links = [...html.matchAll(/<a href="\/next\/v8\/coach\/\?c=([a-z_]+)">([^<]+) <span>/g)];
  assert.equal(links.length, 8);
  assert.deepEqual(links.map((m) => m[1]).sort(), roster.coaches.map((c) => c.persona_id).sort());
  for (const m of links) assert.equal(m[2], roster.coaches.find((c) => c.persona_id === m[1]).name);
  const fallback = K.coachListHTML(null, "/next/v8/");
  assert.equal((fallback.match(/<a href="\/next\/v8\/coach\/\?c=/g) || []).length, 8);
  assert.doesNotMatch(fallback, /undefined/);
});

// ── site-to-A round 1, lane B (2026-10-18, #4580): story, coaches, week, day ────
const EPISODES = load("episodes");
const COACHES = load("coaches");
const CALLS = load("calls");
const SRC = { pulse: load("pulse_history"), workouts: load("workouts"), training: load("training_overview"), nutrition: load("nutrition_overview") };
const plain = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

test("Story ST10: one frame sentence under the chapter title says what the site is", () => {
  const html = P.storyChapterHTML(EDITION, B, POSTS, EPISODES);
  assert.match(html, new RegExp(`</h1><p class="ck-soft">${P.STORY_FRAME.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/’/g, "(?:’|&#39;|&rsquo;)")}</p>`));
  assert.match(P.STORY_FRAME, /predicts how it will go, and code checks every call\.$/);
});

test("Story: the chapter's dek is printed as served, not recomposed around the page's numbers", () => {
  const html = P.storyChapterHTML(EDITION, B, POSTS, EPISODES);
  assert.ok(plain(html).includes(B.chapter.data.dek.replace(/\s+/g, " ")), "the served dek, whole");
  assert.doesNotMatch(html, /went (below|above) \d+ pounds/);
});

test("Story ST1: the newest published episode plays under the chapter when this chapter's own is held; no row links a bare .mp3", () => {
  const html = P.storyChapterHTML(EDITION, B, POSTS, EPISODES);
  const newest = [...EPISODES.episodes].sort((a, b) => b.date.localeCompare(a.date))[0];
  assert.match(html, new RegExp(`<audio controls preload="none" src="${newest.url}"`));
  assert.match(html, new RegExp(`The newest episode, for week ${newest.week}: ${newest.guest_name} · ${Math.round(newest.duration_sec / 60)} min\\.`));
  assert.match(html, /This chapter’s own episode is recorded and held for review\./);
  const rows = P.episodeRowsHTML(EPISODES, { playing: newest.url });
  assert.doesNotMatch(rows, /href="[^"]*\.mp3"/, "no bare .mp3 link");
  assert.doesNotMatch(rows, /Listen →/);
  assert.match(rows, new RegExp(`^<ul class="ck-rows ck-rows--more"><li><span class="ck-rows__key">EP${EPISODES.pending.week}</span><span>Held for review before it publishes\\.</span></li>`), "the held episode is the first row");
  for (const e of EPISODES.episodes) assert.ok(rows.includes(`${e.title} · ${e.guest_name}`), `${e.title} names its guest`);
  assert.match(rows, /\(playing above\)/);
  const titles = [...rows.matchAll(/<li><span>(EP\d+)/g)].map((m) => m[1]);
  assert.deepEqual(titles, [...titles].sort((a, b) => Number(b.slice(2)) - Number(a.slice(2))), "newest first");
  assert.equal(P.newestEpisode({ episodes: [] }), null);
  assert.doesNotMatch(P.storyChapterHTML(EDITION, B, POSTS, { episodes: [] }), /<audio/, "no episode with audio: no player");
});

test("Story: the chapter list runs newest first with each chapter's day, the weights unchanged", () => {
  const posts = P.postsInOrder(POSTS);
  const html = P.chapterRowsHTML(posts, { startLb: B.today.data.start_weight_lbs, newestFirst: true });
  const keys = [...html.matchAll(/<span class="ck-rows__key">([^<]*)<br><span class="ck-small">([^<]*)<\/span>/g)].map((m) => [m[1], m[2]]);
  assert.equal(keys.length, posts.length);
  assert.equal(keys[0][0], posts[posts.length - 1].label, "the newest chapter is first");
  assert.match(keys[0][1], /^(September|October|November) \d+$/, "its day under the week label");
  const values = [...html.matchAll(/<span class="ck-rows__value">([^<]*)<\/span>/g)].map((m) => m[1]);
  for (const v of values) assert.match(v, /^(Before day one|\d+(\.\d)? lb(, the start)?)$/, v);
  assert.doesNotMatch(P.chapterRowsHTML(posts), /ck-small/, "Start's own list is unchanged");
});

test("Coaches C1: the sureness clause says the direction and the size in words, never a bare percentage", () => {
  const d = B.record.data;
  assert.match(P.skillClause(d), /^Counting how sure each call was, they come out (slightly|well) (ahead of|behind) that guess\.$/);
  assert.doesNotMatch(P.skillClause(d), /%/);
  assert.equal(P.skillClause({ ...d, brier_skill: 0 }), "Counting how sure each call was, they come out level with that guess.");
  assert.equal(P.skillClause({ ...d, brier_skill: 0.2 }), "Counting how sure each call was, they come out well ahead of that guess.");
  assert.equal(P.skillClause({ ...d, brier_skill: -0.01 }), "Counting how sure each call was, they come out slightly behind that guess.");
});

test("Coaches C2/C5: a lagging record says its day, the lead's row says why there is none, sitting out is one line under the list", () => {
  const html = P.teamHTML(COACHES, "", "", { asOf: EDITION.as_of });
  const row = (name) => html.split("<li>").find((li) => li.includes(name));
  const lag = COACHES.coaches.filter((c) => c.record && c.record.through < EDITION.as_of);
  const current = COACHES.coaches.filter((c) => c.record && c.record.through === EDITION.as_of);
  assert.ok(lag.length >= 1 && current.length >= 1, "the capture has both kinds");
  for (const c of lag) assert.match(row(c.name), new RegExp(`${c.record.confirmed} of ${c.record.n}<br><span class="ck-small">through [A-Z][a-z]+ \\d+</span>`), c.name);
  for (const c of current) assert.doesNotMatch(row(c.name), /through/, c.name);
  assert.match(row("Eli Marsh"), /ck-coach__job">Lead, the day's plan; runs the program, so no checked calls<\/span><span class="ck-coach__record">none<\/span>/);
  assert.doesNotMatch(row("Amara Patel").split("</li>")[0], /sitting out/i, "not in the row");
  assert.match(html, /<\/ul><p class="ck-small">Amara Patel is sitting out: no sensor since August 27\.<\/p>$/, "one line under the list");
  assert.doesNotMatch(html, /ck-meter/);
  assert.doesNotMatch(P.teamHTML(COACHES), /through/, "no edition day: no lag claim");
});

test("Coaches C3/C4: the record track is neutral, and what the count counts is one tap deeper", () => {
  const html = P.recordBigHTML(B.record);
  assert.match(html, /<div class="ck-track"[^>]*><i style="width:\d+%;background:var\(--ck-faint\)"><\/i><\/div>/);
  assert.match(html, new RegExp(`<details class="ck-small"><summary>What the ${B.record.data.decided} are</summary>`));
  assert.match(html, /Not all of them are formal predictions\./);
});

test("Coaches C6: the next day to come back for is the earliest pending call's due day", () => {
  const preds = load("predictions");
  const want = preds.predictions.filter((p) => p.status === "pending" && p.due_date >= EDITION.as_of).sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  const line = P.nextSettleLine(preds, EDITION.as_of);
  assert.match(line, new RegExp(`^Next to settle: ${want.coach_name}’s call on [a-z ]+, [A-Z][a-z]+day, [A-Z][a-z]+ \\d+\\.$`));
  assert.doesNotMatch(line, /\b20\d\d-\d\d-\d\d\b|_/);
  assert.equal(P.nextSettleLine({ predictions: [] }, EDITION.as_of), "");
  assert.equal(P.nextSettleLine(null, EDITION.as_of), "");
  assert.equal(P.nextSettleLine({ predictions: [{ status: "pending", coach_name: "X", due_date: "2026-10-01" }] }, EDITION.as_of), "", "a due day already past is not next");
});

test("Week W3: the AI row prints the engine's shared sentence when the row serves one, else its verdict", () => {
  const sc = structuredClone(B.scorecard);
  sc.data.rows.ai.data.comparison_text = "So far they do not beat a simple guess.";
  assert.match(F.scorecardHTML(sc), /<b>So far they do not beat a simple guess\.<\/b>/);
  assert.match(F.scorecardHTML(B.scorecard), new RegExp(`<b>${B.scorecard.data.rows.ai.data.verdict_text}\\.</b>`));
  // The record block's one sentence (lane E, record_words) reaches the row through weekSlots.
  const withRecord = { ...B, record: { ...B.record, data: { ...B.record.data, comparison_text: "The coaches do not beat a simple guess yet." } } };
  assert.match(P.weekSlots(EDITION, withRecord, "/next/v8/")["ck-week"], /<b>The coaches do not beat a simple guess yet\.<\/b>/);
});

test("Week W4: the page ends on a dated next line from the served next block, else the standing Wednesday", () => {
  assert.equal(P.weekNextLine(B.next, EDITION.as_of), `Next: the chapter draft ${new Date(B.next.data.chapter.data.date + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" })}; the numbers every Sunday.`);
  const nextDue = structuredClone(B.next);
  nextDue.data.chapter.data.next_due = "2026-10-28";
  assert.match(P.weekNextLine(nextDue, EDITION.as_of), /^Next: the chapter draft Wednesday, October 28;/, "next_due wins when served");
  assert.match(P.weekNextLine({ state: "unavailable", data: null }, "2026-10-21"), /^Next: the chapter draft Wednesday, October 28;/, "on a Wednesday the standing day is the next one");
  assert.match(P.weekNextLine(null, "2026-10-17"), /^Next: the chapter draft Wednesday, October 21;/);
  assert.equal(P.weekNextLine(null, ""), "");
  assert.match(P.weekSlots(EDITION, B, "/next/v8/")["ck-next-line"], /^Next: the chapter draft/);
  // Lane E's chronicle date on the chapter block comes first when it is served.
  const chapter = structuredClone(B.chapter);
  chapter.data.next_due = "2026-11-04";
  assert.match(P.weekNextLine(B.next, EDITION.as_of, chapter), /^Next: the chapter draft Wednesday, November 4;/);
});

test("Day D1: no lifts and a walk say the absence first, and the walk is the served modality minutes", () => {
  const iso = EDITION.as_of;
  const row = SRC.training.daily_modality_minutes_30d.find((r) => r.date === iso);
  assert.ok(row && row.walking_min > 0 && !SRC.workouts.workouts.some((w) => w.date === iso), "the capture's day has a walk and no session");
  const html = D.dayLiftsHTML(iso, SRC, "/next/v8/");
  assert.equal(html, `<p class="ck-soft">No lifting logged that day.</p><p class="ck-soft">Also that day: ${row.walking_min} minutes of walking.</p>`);
  assert.match(D.dayLiftsHTML("2026-01-01", SRC, "/next/v8/"), /^<p class="ck-soft">No training was recorded on this day\.<\/p>$/);
});

test("Day D2: the checked call carries the day of its reading — observed_on when served, the served sentence's day until then", () => {
  const call = CALLS.calls.find((c) => c.settled_date === EDITION.as_of && c.kind === "number");
  assert.ok(call, "a number call settled on the capture's day");
  assert.match(D.daySettledHTML(EDITION.as_of, CALLS, "/next/v8/"), /Graded on the reading for [A-Z][a-z]+ \d+\./);
  assert.equal(D.observedOnText({ ...call, observed_on: "2026-10-16" }), "Graded on Friday’s reading, October 16.");
  assert.equal(D.observedOnText({ ...call, observed_on: null, observed_on_text: "Friday, October 16" }), "Graded on Friday’s reading, October 16.", "lane E's served words");
  assert.equal(D.observedOnText({ ...call, called: "Max Reyes called his weight at about 304.5 lb.", observed_on: null }), "");
});

test("Day D3: a 'call' with no date and no number in it is labelled a note", () => {
  const moves = load("coach_moves_2026-10-17");
  const html = D.daySaidHTML(EDITION.as_of, moves, "/next/v8/");
  assert.match(html, /Nathan Reeves<\/a> · A note<\/span>/);
  assert.doesNotMatch(html, /· A call/);
  assert.equal(D.datedCall("Weight will be around 304.5 pounds tomorrow morning"), true);
  assert.equal(D.datedCall("Recovery will be above 60 on Monday."), true);
  assert.equal(D.datedCall("I expect the silence continues until he names what he's avoiding."), false);
  assert.equal(D.datedCall("Protein will rise next week."), false, "a date word with no number is not a checkable call");
  const dated = { ...moves, lines: [{ ...moves.lines[0], text: "Weight will be around 304.5 pounds tomorrow morning" }] };
  assert.match(D.daySaidHTML(EDITION.as_of, dated, "/next/v8/"), /· A call<\/span>/);
});

// ── site-to-A round 1, lane D (2026-10-18): the sheet, how it's built, the appendix, a call, a coach ──
const BU = await import("../../site/assets/js/ck_built.js");
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

test("Sheet (round 2, item 7): which areas count is ONE statement in one place, beside the level; a thin area's row prints its score like the rest", () => {
  const character = load("character");
  const held = character.pillars.filter((p) => p.coverage_hold && !p.not_instrumented);
  assert.ok(held.length >= 1, "the capture has a held area (metabolic)");
  assert.equal(S.countsNote(character), "Relationships has nothing measuring it and is left out; Metabolic health is measured thinly and still counts.");
  const level = S.levelHTML(character);
  assert.match(level, /Worked out from 6 of 7 areas: Relationships has nothing measuring it and is left out; Metabolic health is measured thinly and still counts\.<\/p>/);
  const areas = S.areasHTML(character);
  const whole = textOf(level + areas);
  assert.doesNotMatch(whole, /on hold|Too little|not counted as average/, "the three round-1 phrasings are gone");
  assert.equal((whole.match(/still counts/g) || []).length, 1, "said once");
  assert.equal((whole.match(/left out/g) || []).length, 1, "said once");
  const metabolic = character.pillars.find((p) => p.name === "metabolic");
  assert.match(areas, new RegExp(`Metabolic health</span><span class="ck-coach__job">Score ${metabolic.raw_score.toFixed(1)} of 100, [a-z0-9. ]+</span>`), "the thin area's score is printed, like every other row");
  assert.equal(typeof S.compositeNote, "undefined", "the separate note under the level is gone");
  assert.doesNotMatch(page("sheet"), /ck-sheet-note/, "and so is its hook in the shell");
  assert.equal(S.countsNote({ pillars: character.pillars.filter((p) => !p.coverage_hold && !p.not_instrumented) }), "", "every area measured and counted: no note");
  assert.equal(S.countsNote({ pillars: [{ name: "metabolic", coverage_hold: true }, { name: "mind", coverage_hold: true }] }), "Metabolic health and Mind are measured thinly and still count.");
  assert.match(S.levelHTML({ character: { level: 12, composite_pillar_count: 7, composite_pillar_total: 7 }, pillars: [] }), /Worked out from 7 of 7 areas\.<\/p>/);
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

// ── site-to-A round 2 (2026-10-18, the fresh graders G9/G10) ──────────────────
test("round 2 (built, item 1): the page says what Matthew approves by hand in the same terms as the front, Start, Story and Week — chapters and podcast episodes too", () => {
  const html = page("built");
  const text = textOf(html);
  const rule = "Matthew approves two things by hand: a change to what the programs are permitted to do, and each chapter and podcast episode before it publishes. Everything else, code and pages alike, goes live when the automated checks pass.";
  assert.ok(text.includes(rule), text.match(/[^.]*by hand[^.]*\./g));
  assert.doesNotMatch(text, /approves one thing|The one thing I approve/, "the one-thing claim is gone from both places");
  assert.match(text, /I approve two things by hand, a change to what the programs are permitted to do and each chapter and podcast episode before it publishes;/, "the draft says the same");
  // The four pages it contradicted still say the chapter waits on him.
  assert.match(shell("story"), /each once Matthew approves it/);
  assert.match(P.nextChapterLine(B.next), /^The next draft is due [A-Z][a-z]+day, [A-Z][a-z]+ \d+; it publishes once Matthew approves it\.$/);
});

test("round 2 (week, item 4): 'faster than planned' takes the hollow dot and its own word; the legend and the dot agree", () => {
  const sc = B.scorecard;
  const fast = sc.data.order.filter((k) => sc.data.rows[k].data.verdict === "faster_than_planned");
  assert.ok(fast.length >= 1, "the capture's body row is faster_than_planned");
  const html = F.scorecardHTML(sc, "/next/v8/", { label: false, aiText: B.record.data.comparison_text });
  const row = (key) => html.split("<li>").find((li) => li.includes(`<b>${sc.data.rows[key].data.verdict_text}.</b>`));
  for (const k of fast) assert.match(row(k), /<i class="ck-dot ck-dot--off" aria-hidden="true"><\/i><b>/, `${k}: hollow`);
  for (const k of sc.data.order.filter((k) => sc.data.rows[k].data.verdict === "going_well")) assert.match(row(k), /<i class="ck-dot" aria-hidden="true"><\/i><b>/, `${k}: filled`);
  const plain = textOf(html);
  assert.match(plain, /A filled dot is an area going well this week\. A hollow dot beside “faster than planned” is a flag, not a win\./);
  assert.equal((html.match(/class="ck-dot"/g) || []).length, sc.data.order.filter((k) => sc.data.rows[k].data.verdict === "going_well").length, "filled = going_well, exactly");
  // Without a flagged row the extra sentence is not printed.
  const calm = JSON.parse(JSON.stringify(sc));
  for (const k of fast) calm.data.rows[k].data.verdict = "going_well";
  assert.doesNotMatch(textOf(F.scorecardHTML(calm, "/next/v8/", { label: false, aiText: B.record.data.comparison_text })), /flag, not a win/);
  assert.equal(P.weekSlots(EDITION, B, "/next/v8/")["ck-week"], html, "the week page prints this");
});

test("round 2 (story, item 5): a stale chapter takes the neutral label, never the accent badge", () => {
  const stale = P.chapterHTML({ ...B.chapter, state: "stale" }, B.next, { asOf: EDITION.as_of });
  assert.match(stale, /^<span class="ck-label">Latest chapter · Week 5 \(written October 6\)<\/span><h1>/);
  assert.doesNotMatch(stale, /ck-badge/);
  const old = P.chapterHTML(B.chapter, B.next, { asOf: later(B.chapter.data.date, 11) });
  assert.match(old, /^<span class="ck-label">Latest chapter/, "ok but eleven days old: the same neutral label");
  assert.doesNotMatch(old, /ck-badge/);
  const fresh = P.chapterHTML({ ...B.chapter, state: "ok" }, B.next, { asOf: later(B.chapter.data.date, 3) });
  assert.match(fresh, /^<span class="ck-badge">New this week · Week 5<\/span><h1>/, "fresh: the accent badge, as before");
  assert.doesNotMatch(P.storyChapterHTML({ ...EDITION, as_of: later(B.chapter.data.date, 11) }, { ...B, chapter: { ...B.chapter, state: "stale" } }, POSTS, load("episodes")), /ck-badge/);
});

test("round 2 (call, item 6): the list's counts add up to the record's total, from served fields, or say what they account for — never two totals", () => {
  const body = load("calls");
  const decided = B.record.data.decided;
  const bets = body.calls.filter((c) => c.kind === "bet").length;
  assert.equal(body.count + bets + body.excluded.count, decided, "the capture: 63 pages + 5 bets (two sides each in the record) + 115 without = 183");
  const want = `${decided} checked calls in all: ${body.count} with a page here, ${bets} of them bets the record counts once for each coach, and ${body.excluded.count} without.`;
  assert.equal(C.countsLine(body, decided), want);
  const html = C.listHTML(body, "/next/v8/", { decided });
  assert.ok(html.endsWith(`<p class="ck-small">${want}</p>`), html.slice(-200));
  assert.equal((textOf(html).match(/\b183\b/g) || []).length, 1, "the total once");
  assert.doesNotMatch(textOf(html), /\b178\b/);
  // Served numbers that do not add up: no invented bucket, the honest share.
  assert.equal(C.countsLine(body, decided + 5), `${body.count + body.excluded.count} of the ${decided + 5} checked calls are accounted for on this page; the rest count in the record only.`);
  assert.equal(C.countsLine(body, null), "", "no record total: no line");
  assert.equal(C.listHTML(body, "/next/v8/"), C.listHTML(body, "/next/v8/", { decided: null }), "the old call shape prints no counts line");
  // A capture with no bet pages (each bet's two sides then sit among the unpaged): no bet clause.
  assert.equal(C.countsLine({ ...body, calls: body.calls.filter((c) => c.kind !== "bet"), count: body.count - bets, excluded: { count: body.excluded.count + 2 * bets } }, decided), `${decided} checked calls in all: ${body.count - bets} with a page here, and ${body.excluded.count + 2 * bets} without.`, "no bets: no bet clause");
});

test("round 2 (coaches, item 8): until the served sentence lands, the big record names ONE baseline in the front's words, the exact rate one tap deeper", () => {
  const html = P.recordBigHTML(B.record);
  assert.match(html, /<\/div><p>The coaches do not beat a simple guess yet\.<\/p><details class="ck-small"><summary>The exact rate<\/summary><p>A guess that every call has a 42% chance of coming true does about as well\. Counting how sure each call was, they come out slightly behind that guess\.<\/p><\/details>/);
  assert.equal(textOf(html).indexOf("The coaches do not beat a simple guess yet.") < textOf(html).indexOf("42%"), true);
  assert.equal(P.recordHTML(B.record).includes("The coaches do not beat a simple guess yet."), true, "the same sentence the front and Start print");
  // Lane E's served sentence wins here as it does on the front; its baseline text is the exact rate.
  const served = { ...B.record, data: { ...B.record.data, comparison_text: "Too few checked calls yet to compare the coaches with a simple guess.", baseline: { text: "A guess that every call has a 42% chance of coming true does about as well." } } };
  assert.match(P.recordBigHTML(served), /<p>Too few checked calls yet to compare the coaches with a simple guess\.<\/p><details class="ck-small"><summary>The exact rate<\/summary>/);
  assert.doesNotMatch(P.recordBigHTML({ ...B.record, data: { ...B.record.data, brier_skill: null } }), /The exact rate/, "no skill served: no fold");
});

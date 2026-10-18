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

test("Start: a week's change is its own window's first reading against its last, never a reading from before the window (item 7)", () => {
  const weights = load("timeline").timeline.weights;
  const startDate = B.today.data.start_date;
  const html = P.recapHTML(P.postsInOrder(POSTS), { weights, startDate });
  assert.doesNotMatch(html, /\blbs\b/, "lb everywhere");
  assert.doesNotMatch(html, /this week/, "a historical row never says 'this week'");
  for (const p of P.postsInOrder(POSTS)) {
    const m = /Day (\d+) to Day (\d+)/.exec(p.stats_line || "");
    if (!m) continue;
    const day = (n) => new Date(Date.parse(`${startDate}T12:00:00Z`) + (n - 1) * 86400000).toISOString().slice(0, 10);
    const inside = weights.filter((r) => r.date >= day(Number(m[1])) && r.date <= day(Number(m[2]))).sort((a, b) => a.date.localeCompare(b.date));
    const want = inside.length < 2 ? "" : `${inside[0].lbs > inside[inside.length - 1].lbs ? "down" : "up"} ${Math.abs(inside[0].lbs - inside[inside.length - 1].lbs).toFixed(1)} that week`;
    assert.equal(P.windowChange(p.stats_line, weights, startDate), want, p.label);
    if (want) assert.ok(html.includes(`, ${want}`), `${p.label}: ${want}`);
  }
  // The specimen: week 2 ("Day 4 to Day 10") used to print Day 1's 327.3 against Day 10 as "down 8.4 this week".
  const week2 = P.postsInOrder(POSTS).find((p) => /^Week 2/.test(p.label));
  assert.doesNotMatch(P.windowChange(week2.stats_line, weights, startDate), /8\.4/);
  assert.equal(P.windowChange(week2.stats_line, null, startDate), "", "no timeline: no change claimed");
  assert.equal(P.weekChange("315.0", "312.3"), "down 2.7 this week");
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
const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "next", "v8");
const shell = (page) => readFileSync(join(SITE, page, "index.html"), "utf8");

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
  assert.equal(P.guessSentence({ ...B.record.data, baseline: "A guess that nothing changes does about as well." }), "A guess that nothing changes does about as well.", "lane E's served sentence wins");
  assert.equal(P.guessSentence({ ...B.record.data, baseline: { text: "Served." } }), "Served.");
  assert.equal(P.guessSentence({ ...B.record.data, baseline: { rate: 0.42 } }), "The coaches do not beat a simple guess yet.", "a baseline with no sentence changes nothing");
  const failed = { state: "unavailable", absent_text: "The record is not here.", data: null };
  assert.equal(P.recordHTML(failed, { href: "/x/" }), "The record is not here.");
});

test("item 4: Go deeper leads with the latest chapter — chronicle.latest when served, else the chapter block; no held claim anywhere", () => {
  const front = shell("");
  const deeper = /<ul class="ck-rows ck-rows--deeper">\s*<li id="ck-chapter-row">/.test(front);
  assert.ok(deeper, "the chapter row is the first row");
  assert.equal(P.latestChapterBlock(B), B.chapter, "no chronicle block: the chapter block as today");
  const latest = { title: "The Quiet Accumulation", date: "2026-10-13", url: "/journal/posts/week-09/", week_label: "Week 6", read_minutes: 7, status: "published", next_due: "2026-10-21" };
  const withChronicle = { ...B, chronicle: { state: "ok", as_of: "2026-10-18", absent_text: "", data: { latest } } };
  const row = P.frontSlots(EDITION, withChronicle, "/next/v8/")["ck-chapter-row"];
  assert.match(row, /Week 6 · “The Quiet Accumulation”/);
  assert.match(row, /The latest chapter · October 13 · 7 min/);
  assert.equal(P.latestChapterBlock({ ...B, chronicle: { state: "ok", data: { latest: { title: "x" } } } }), B.chapter, "a latest with no url or date is not bound");
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

test("item 8: the mark names its floor — the start at one end, 185 at the other", () => {
  const t = B.today.data;
  const ends = F.markEndsHTML(t.start_weight_lbs, t.goal_weight_lbs);
  assert.equal(ends, '<div class="ck-ends"><span>327.3 lb at the start</span><span>185 lb, the goal</span></div>');
  assert.ok(P.frontSlots(EDITION, B, "/next/v8/")["ck-mark"].endsWith(ends));
  assert.equal(F.markEndsHTML(null, 185), "");
  assert.equal(F.markEndsHTML(180, 185), "", "a start under the goal names no floor");
  // front:F5: the caption sits under the mark, then the record — not the record between them.
  const front = shell("");
  assert.ok(front.indexOf('id="ck-mark"') < front.indexOf("One column a day") && front.indexOf("One column a day") < front.indexOf('id="ck-record"'));
});

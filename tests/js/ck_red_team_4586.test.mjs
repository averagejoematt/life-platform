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
  assert.equal(out["ck-argue-heading"], "The latest from the coaches.");
  const silent = { ...B, moves: { state: "ok", data: { days: [] } } };
  assert.equal(P.frontReadSlots(EDITION, silent, "/next/v8/")["ck-argue-heading"], "No open bet between them this week.");
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
  assert.match(html, new RegExp(`<text [^>]*>${String(t.start_weight_lbs)} lb, the start</text>`));
  assert.match(html, new RegExp(`<text [^>]*>${String(Number(t.goal_weight_lbs))} lb, the goal</text>`));
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

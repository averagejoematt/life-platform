// tests/js/coach_today_4182.test.mjs — #4182/#4188: the coaching door opens on ONE read,
// dated in words, and the integrator's weekly call is labelled weekly.
//
// THE DEFECT (live, Friday 2026-09-25, Day 20). The door's top read was the integrator's
// WEEKLY priority, written Monday 09-21, served unlabelled on Friday as "the board's read
// … as of 2026-09-21" — 4.6 days old and wrong in two figures by then (316.9 lb / 3.7
// lb/wk against 313.1 / −4.58). Found by Session AV's B2 lens; ruled by the red-team
// panel (epic #4182, ruling 2(iv)).
//
// Every function under test takes `now` explicitly: the fixtures below never read the
// wall clock, so none of them can rot into a #3535 date bomb.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const T = await import("../../site/assets/js/coach_today.js");
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

// The live shapes (/api/coaching-dashboard.coaches[], 2026-09-26T04:40Z capture), trimmed.
const COACHES = [
  { coach_id: "sleep", name: "Dr. Lisa Park", position_summary: "On the night of 2026-09-23, Whoop logged 86% recovery, HRV at 48.2 ms…", analysis_generated_at: "2026-09-25T17:01:48.880845+00:00" },
  { coach_id: "physical", name: "Dr. Max Reyes", position_summary: "On the night of 2026-09-23, his Whoop registered 86% recovery…", analysis_generated_at: "2026-09-25T17:05:56.896879+00:00" },
  { coach_id: "explorer", name: "Dr. Henning Brandt", position_summary: "Matthew is at a critical fork.", analysis_generated_at: "2026-09-25T17:10:57.817264+00:00" },
  { coach_id: "labs", name: "Dr. James Okafor", position_summary: "", analysis_generated_at: "2026-09-25T17:20:00+00:00" },
  { coach_id: "mind", name: "Dr. Nathan Reeves", position_summary: "A read with no timestamp.", analysis_generated_at: "" },
];
const MONDAY_CALL = "2026-09-21T14:02:56.543529+00:00"; // the integrator's cron: Mondays 14:00Z
const FRIDAY_NIGHT_PT = new Date("2026-09-26T04:40:00Z"); // Friday Sep 25, 9:40 PM PT
const WEIGHTS = [
  { date: "2026-09-19", weight_lbs: 315.6 },
  { date: "2026-09-20", weight_lbs: 316.9 },
  { date: "2026-09-21", weight_lbs: 315.8 },
  { date: "2026-09-24", weight_lbs: 313.7 },
  { date: "2026-09-25", weight_lbs: 313.1 },
];
const NUTRITION = { pro_7d_avg: 158.0, avg_protein_g: 153.3 };

test("selection: the freshest SERVED, DATABLE read wins — an empty text or an undatable read never leads", () => {
  const c = T.pickTodaysRead(COACHES);
  assert.equal(c.coach_id, "explorer"); // labs is newer but serves no text; mind has no timestamp
  // positive control: give mind a newer timestamp and it wins — the filter, not the order, decides
  const withMind = COACHES.map((x) => (x.coach_id === "mind" ? { ...x, analysis_generated_at: "2026-09-25T18:00:00Z" } : x));
  assert.equal(T.pickTodaysRead(withMind).coach_id, "mind");
  assert.equal(T.pickTodaysRead([]), null);
  assert.equal(T.pickTodaysRead(undefined), null);
});

test("freshness tiers: <=48 h fresh, >48 h stale (banner first), >7 d old (off the first screen)", () => {
  const now = new Date("2026-09-25T20:00:00Z");
  assert.equal(T.freshness("2026-09-25T17:00:00Z", now), "fresh");
  assert.equal(T.freshness("2026-09-23T19:00:00Z", now), "stale"); // 49 h
  assert.equal(T.freshness("2026-09-23T21:00:00Z", now), "fresh"); // 47 h
  assert.equal(T.freshness(MONDAY_CALL, now), "stale");
  assert.equal(T.freshness("2026-09-18T19:00:00Z", now), "old"); // 7 d + 1 h
  assert.equal(T.freshness("", now), "unknown");
});

test("the written stamp is in words, Pacific, and never the machine 'as of'", () => {
  const now = new Date("2026-09-25T20:00:00Z");
  assert.equal(T.writtenStamp("2026-09-25T17:10:57Z", now), "written Friday 10:10 AM PT");
  // six days or more: the date joins the weekday so it can't be misread as this week's
  assert.equal(T.writtenStamp("2026-09-18T14:02:00Z", now), "written Friday Sep 18, 7:02 AM PT");
  assert.equal(T.writtenStamp("not a date", now), "");
  for (const s of [T.writtenStamp("2026-09-25T17:10:57Z", now), T.weekCallLabel(MONDAY_CALL), T.weeklyCadenceLine(MONDAY_CALL, 16)]) {
    assert.doesNotMatch(s, /as of/i, `a first-screen stamp says "as of": ${s}`);
  }
});

test("the week's call is labelled weekly, with the day it was written", () => {
  assert.equal(T.weekCallLabel(MONDAY_CALL), "the week's call · written Monday Sep 21");
  assert.match(T.weekCallLabel(MONDAY_CALL), /week/);
  assert.equal(T.weekCallLabel(""), "the week's call"); // undatable: the cadence, never a guessed date
  assert.equal(
    T.weeklyCadenceLine(MONDAY_CALL, 16),
    "The integrator's read is weekly — written Mondays; this one is from Monday Sep 21, Day 16.",
  );
  assert.equal(T.weeklyCadenceLine(MONDAY_CALL, 0), "The integrator's read is weekly — written Mondays; this one is from Monday Sep 21.");
  assert.equal(T.weeklyCadenceLine("", 16), "");
});

test("the >48 h banner: its age, then what moved — from the served series, never from the read", () => {
  const b = T.sinceBanner(MONDAY_CALL, FRIDAY_NIGHT_PT, WEIGHTS, NUTRITION);
  // "before" = the last weigh-in BEFORE the day it was written (Sun 09-20: 316.9, the figure
  // the Monday read itself quoted), "after" = the newest weigh-in.
  assert.equal(b, "This read is 4 days old. Since it was written: weight 316.9 → 313.1 lb, protein 7-day 158 g.");
  // absence stays absence: no series, no weight clause — never a guessed "before"
  assert.equal(T.sinceBanner(MONDAY_CALL, FRIDAY_NIGHT_PT, [], null), "This read is 4 days old.");
  // a read written Friday evening PT (09-25): "before" is Thursday's weigh-in, "after" Friday's
  assert.equal(
    T.sinceBanner("2026-09-26T01:00:00Z", new Date("2026-09-29T01:00:00Z"), WEIGHTS, null),
    "This read is 3 days old. Since it was written: weight 313.7 → 313.1 lb.",
  );
  // no LATER weigh-in than the one the writer saw -> no weight clause
  assert.equal(
    T.sinceBanner("2026-09-26T01:00:00Z", new Date("2026-09-29T01:00:00Z"), WEIGHTS.slice(0, 4), null),
    "This read is 3 days old.",
  );
  assert.equal(T.sinceBanner("", FRIDAY_NIGHT_PT, WEIGHTS, NUTRITION), "");
});

test("the record line counts, never a percentage — and says nothing when nothing is decided", () => {
  assert.equal(T.recordLine({ total: 322, observational: 169, decided: 33, confirmed: 17, accuracy_pct: 51.5 }), "33 predictions checked, 17 came true");
  assert.doesNotMatch(T.recordLine({ decided: 33, confirmed: 17, accuracy_pct: 51.5 }), /%|falsifiable|held up/);
  assert.equal(T.recordLine({ decided: 1, confirmed: 0 }), "1 prediction checked, 0 came true");
  assert.equal(T.recordLine({ decided: 0 }), "");
  assert.equal(T.recordLine(null), "");
});

test("the ask: the chosen coach's own open action first, else the soonest-due; [] -> none (never invented)", () => {
  const acts = [
    { coach_id: "sleep", coach_name: "Dr. Lisa Park", text: "Lights out by 10:30.", due: "2026-09-28" },
    { coach_id: "physical", coach_name: "Dr. Max Reyes", text: "170 g protein every day for seven days.", due: "2026-10-02" },
  ];
  assert.equal(T.pickAsk(acts, "physical").coach_id, "physical");
  assert.equal(T.pickAsk(acts, "explorer").coach_id, "sleep");
  assert.equal(T.pickAsk([], "physical"), null); // live until #4187 deploys
  assert.equal(T.pickAsk([{ coach_id: "x", text: "  " }], "x"), null);
  assert.equal(T.calendarDay("2026-10-02"), "Friday Oct 2");
  assert.equal(T.calendarDay("soon"), "");
});

test("glosses: only for terms the served text uses; HRV's and EWMA's lines ARE the site glossary's (one definition per term)", () => {
  assert.deepEqual(T.glossesFor("Whoop logged 86% recovery, HRV at 48.2 ms").map((g) => g.term), ["HRV", "recovery"]);
  assert.deepEqual(T.glossesFor("His protein EWMA sits at 154g").map((g) => g.term), ["EWMA"]);
  assert.deepEqual(T.glossesFor("Matthew is at a critical fork."), []);
  const glossary = JSON.parse(readFileSync(join(REPO, "site", "config", "glossary.json"), "utf8")).terms;
  for (const term of ["HRV", "EWMA"]) {
    const g = T.READER_GLOSS.find((x) => x.term === term);
    assert.equal(g.plain, glossary[term], `the door's ${term} gloss drifted from site/config/glossary.json`);
  }
});

test("SOURCE: on the first screen today's read renders BEFORE the week's call, and the lab notes are not 'the Third Wall'", () => {
  const src = readFileSync(join(REPO, "site", "assets", "js", "coaching.js"), "utf8");
  const body = src.slice(src.indexOf("async function renderToday("));
  assert.ok(body.includes("today's read") && body.includes("weekCallLabel("), "renderToday lost its read or its week's call");
  assert.ok(body.indexOf("today's read") < body.indexOf("weekCallLabel("), "the week's call must render BELOW today's read");
  assert.ok(body.indexOf("weekCallLabel(") < body.indexOf("Where they disagree"), "the disagreements follow the week's call");
  assert.match(src, /key: "lab-notes", label: "What the AI said, and how it felt"/);
  // the retired ribbon phrasing is gone
  assert.ok(!src.includes("falsifiable calls · ${"), "the retired '153 falsifiable calls · …' ribbon template is back");
  assert.ok(!src.includes('"% held up"'), "the retired '51.5% held up' ribbon template is back");
});

// ── the selection chain (coordinator's ruling on PR #4199) ───────────────────────────────
// "Freshest" alone resolved to whichever coach the daily batch ran last. The chain: the
// open ask → the best checked record at n >= 10 within today's batch → the freshest.
const BATCH = [
  { coach_id: "sleep", name: "Dr. Lisa Park", position_summary: "Sleep read.", analysis_generated_at: "2026-09-25T17:01:48Z" },
  { coach_id: "labs", name: "Dr. James Okafor", position_summary: "Labs read.", analysis_generated_at: "2026-09-25T17:09:01Z" },
  { coach_id: "explorer", name: "Dr. Henning Brandt", position_summary: "Explorer read.", analysis_generated_at: "2026-09-25T17:10:57Z" },
];
const CALIB = {
  coaches: [
    { coach_id: "sleep", n: 16, confirmed: 7, accuracy_pct: 43.8, accuracy_ci95: [23.1, 66.8] },
    { coach_id: "labs", n: 4, confirmed: 4, accuracy_pct: 100.0, accuracy_ci95: [51.0, 100.0] },
    { coach_id: "explorer", n: 4, confirmed: 3, accuracy_pct: 75.0 },
    { coach_id: "training", retired: true, n: 40, confirmed: 40, accuracy_pct: 100.0 },
  ],
};

test("chain (a): an open ask picks its owner, and says so", () => {
  const p = T.chooseTodaysRead(BATCH, [{ coach_id: "labs", text: "Book the bloodwork.", due: "2026-10-02" }], CALIB);
  assert.equal(p.coach.coach_id, "labs");
  assert.equal(p.rule, "ask");
  assert.equal(p.reason, "chosen: the open ask");
  // an ask whose owner serves no read falls through to the record rule
  assert.equal(T.chooseTodaysRead(BATCH, [{ coach_id: "mind", text: "Journal." }], CALIB).rule, "record");
});

test("chain (b): no ask -> the best record at n >= 10 in today's batch; n < 10 is excluded even at 100 %", () => {
  const p = T.chooseTodaysRead(BATCH, [], CALIB);
  assert.equal(p.coach.coach_id, "sleep"); // 43.8 % at n=16 beats labs' 100 % at n=4
  assert.equal(p.rule, "record");
  assert.equal(p.reason, "chosen: the best checked record this cycle — 7 of 16 held up");
  assert.doesNotMatch(p.reason, /%/); // counts with their n, never a bare percentage (ADR-105)
  // a read outside the 24 h batch is not eligible however good its record
  const stale = BATCH.map((c) => (c.coach_id === "sleep" ? { ...c, analysis_generated_at: "2026-09-24T12:00:00Z" } : c));
  assert.equal(T.chooseTodaysRead(stale, [], CALIB).rule, "freshest");
  // ties on accuracy -> the newer read
  const tie = { coaches: [{ coach_id: "sleep", n: 10, confirmed: 5, accuracy_pct: 50 }, { coach_id: "explorer", n: 12, confirmed: 6, accuracy_pct: 50 }] };
  assert.equal(T.chooseTodaysRead(BATCH, [], tie).coach.coach_id, "explorer");
});

test("chain (c): nothing qualifies -> the freshest read, labelled; nothing servable -> null", () => {
  const p = T.chooseTodaysRead(BATCH, [], { coaches: [{ coach_id: "labs", n: 4, confirmed: 4, accuracy_pct: 100 }] });
  assert.equal(p.coach.coach_id, "explorer");
  assert.equal(p.reason, "chosen: the freshest read");
  assert.equal(T.chooseTodaysRead(BATCH, [], null).rule, "freshest");
  assert.equal(T.chooseTodaysRead([{ coach_id: "x", position_summary: "", analysis_generated_at: "2026-09-25T17:00:00Z" }], [], CALIB), null);
});

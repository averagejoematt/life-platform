// The Coaching Room's coach profiles (src/lib/coach_room.js, CR2): carried values only, the withheld rule, the
// "what Matt did" rule, the docket from one coach's side, and the record labelled as first graded.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  NOT_PUBLISHED,
  WHAT_MATT_DID,
  askCountsText,
  askRows,
  callsByDay,
  coachRecord,
  correctionArrow,
  criterionWords,
  currentStance,
  datesInWords,
  docketRows,
  fidelityText,
  latestRead,
  roomCoach,
  stanceTimeline,
  voiceRows,
  wordsOrMessage,
} from "../src/lib/coach_room.js";

const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "content", "fixtures");
const FILE = JSON.parse(readFileSync(join(FIX, "coach_room.json"), "utf8"));
const CAL = JSON.parse(readFileSync(join(FIX, "calibration.json"), "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));
const sleep = () => roomCoach(FILE, "sleep_coach");

test("a withheld read shows the API's own message when the row carries one, else only that its words are not published", () => {
  assert.deepEqual(wordsOrMessage("Said this.", null), { text: "Said this.", message: null });
  assert.deepEqual(wordsOrMessage("", null, "read"), { text: null, message: NOT_PUBLISHED.read });
  assert.deepEqual(wordsOrMessage("  ", "withheld: this text's sources are not recorded as publishable"), {
    text: null,
    message: "withheld: this text's sources are not recorded as publishable",
  });
  // the control: a message never rides beside served words
  assert.equal(wordsOrMessage("Said this.", "withheld: x").message, null);
});

test("the latest read is dated, timed and sourced; withheld words are replaced, never paraphrased", () => {
  const r = latestRead(sleep());
  assert.equal(r.day, "29 October 2026");
  assert.equal(r.written, "29 October 2026, 17:02 UTC");
  assert.equal(r.through, "28 October 2026");
  assert.equal(r.source, "/api/coach · recent_outputs");
  assert.equal(r.text, null);
  assert.equal(r.message, NOT_PUBLISHED.read);
  const lead = latestRead(roomCoach(FILE, "eli_marsh"));
  assert.equal(lead.kind, "lead_daily");
  assert.match(lead.text, /^Sample read/);
  assert.equal(lead.cited.length, 2);
  assert.equal(latestRead(roomCoach(FILE, "nutrition_coach")), null);
});

test("the stance: an absent instrument says so with its date in words; a withheld stance never borrows another's words", () => {
  const g = currentStance(roomCoach(FILE, "glucose_coach"));
  assert.equal(g.absent, true);
  assert.equal(g.reason, "no sensor since 12 October 2026");
  const n = currentStance(roomCoach(FILE, "nutrition_coach"));
  assert.equal(n.text, null);
  assert.equal(n.message, NOT_PUBLISHED.stance);
  assert.equal(currentStance(roomCoach(FILE, "eli_marsh")), null, "the lead has no stance (source none)");
});

test("the stance timeline keeps every dated row, newest first, with its correction and the API's unsourced sentence", () => {
  const t = stanceTimeline(sleep());
  assert.deepEqual(
    t.map((x) => x.date),
    ["2026-10-31", "2026-10-24", "2026-10-17", "2026-10-10"]
  );
  assert.equal(t[1].corrections.length, 1);
  assert.equal(correctionArrow(t[1].corrections[0]), "right → wrong");
  assert.equal(t[2].message, NOT_PUBLISHED.stance);
  assert.match(t[3].message, /^Not quoted: the sleep sensor/);
});

test("the asks: the producer's tally carried as served, and every row's 'what Matt did' is not recorded", () => {
  assert.equal(askCountsText(sleep().asks.commitment_counts), "4 held: 1 kept, 1 broken, 1 pending, 1 unresolved.");
  // the control: a tally that does not add up is printed as carried, never re-counted from the rows
  assert.equal(askCountsText({ held: 9, kept: 1, broken: 0, pending: 0, unresolved: 0, ungradeable: 0 }), "9 held: 1 kept.");
  assert.equal(askCountsText({ held: 0 }), "No ask on the record this cycle.");
  assert.equal(askCountsText(null), null);
  const rows = askRows(sleep());
  assert.equal(rows.length, 4);
  assert.ok(rows.every((r) => r.did === WHAT_MATT_DID && WHAT_MATT_DID === "not recorded"));
  // a KEPT ask is still not evidence of what Matt did — the grader's outcome and Matt's action are different facts
  const kept = rows.find((r) => r.status === "kept");
  assert.equal(kept.outcome, "kept");
  assert.equal(kept.did, "not recorded");
  assert.equal(rows[0].checked, "sleep duration hours, up");
  assert.equal(rows[3].checked, "not recorded");
});

test("the docket from this coach's side: its bet, its frozen stake, how it ended; withheld claims stay withheld", () => {
  const names = { sleep_coach: "Lisa Park", nutrition_coach: "Nathan Reeves" };
  const [d] = docketRows(sleep(), "sleep_coach", (id) => names[id]);
  assert.equal(d.versus, "Nathan Reeves");
  assert.equal(d.result, "won");
  assert.equal(d.side, "said it would hold");
  assert.equal(d.criterion, "recovery score 7day avg at or above 70");
  assert.match(d.stake, /^its Brier score 0\.251 over 20 calls/);
  assert.equal(d.mine.message, NOT_PUBLISHED.claim);
  const [o] = docketRows(roomCoach(FILE, "nutrition_coach"), "nutrition_coach", (id) => names[id]);
  assert.equal(o.result, "lost");
  assert.equal(o.side, "said it would not hold");
  assert.equal(criterionWords({ description: "Their own words." }), "Their own words.");
});

test("the voice: served lines only, the fidelity line carried with the API's label", () => {
  assert.equal(voiceRows(sleep().voice).length, 6);
  assert.equal(voiceRows(null).length, 0);
  assert.equal(fidelityText(sleep().fidelity), "Judges picked this coach's own writing in 4 of 8 blind reads (50.0%) — “distinct”, as the platform labels it.");
  assert.equal(fidelityText({ n: 0, correct: 0 }), null);
});

test("the calls by day: newest day first, each call keeps its own word, a disputed verdict is flagged", () => {
  const preds = JSON.parse(readFileSync(join(FIX, "predictions.json"), "utf8")).filter((p) => p.coach_id === "sleep_coach" && p.visibility === "public");
  const days = callsByDay(preds);
  assert.deepEqual(
    days.map((d) => d.date),
    [...new Set(preds.map((p) => p.logged_date))].sort().reverse()
  );
  const all = days.flatMap((d) => d.calls);
  const disputed = all.find((x) => x.p.id === "sleep-20261005-deepsleep01");
  assert.equal(disputed.disputed, true);
  assert.equal(disputed.word, "wrong", "the stored verdict word stays; the page flags it, never counts it");
  assert.equal(disputed.corrected, true);
});

test("the record is labelled as first graded, carries its interval, and never computes a percentage", () => {
  const cc = CAL.calibration.coaches.find((x) => x.coach_id === "sleep");
  const r = coachRecord(cc, null);
  assert.match(r.line, /, as first graded$/);
  assert.ok(r.interval.startsWith("95% interval") || r.interval === "no interval served");
  const planted = clone(cc);
  planted.accuracy_pct = 12.3; // deliberately not confirmed/n
  assert.equal(coachRecord(planted, null).pct, "12.3%");
  assert.equal(coachRecord(null, null), null);
  assert.equal(coachRecord(null, { right: 3, n: 4 }).interval, "no interval served");
});

test("dates inside a served sentence are put in words", () => {
  assert.equal(datesInWords("no sensor since 2026-10-12"), "no sensor since 12 October 2026");
  assert.equal(datesInWords("at 2026-10-12T03:04:05+00:00 it stopped"), "at 12 October 2026 it stopped");
  assert.equal(datesInWords(null), "");
});

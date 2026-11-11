// CR2's two public-safe sources on the coach record (owner ruling 2026-11-09, third, D + E): the owner-approved historical
// words (/api/coach_room_words) and the public-safe brief (/api/coach_brief). Fixture-driven; pure helpers only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { approvedWords, briefFact, briefView, readsCoverage, roomCoach, weekOf, withApprovedClaims } from "../src/lib/coach_room.js";
import { CR23_DATA_KEYS } from "../src/lib/room.js";

const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "content", "fixtures");
const FILE = JSON.parse(readFileSync(join(FIX, "coach_room.json"), "utf8"));
const ISO = /\b20\d\d-\d\d-\d\d\b/;

test("both CR2 sources are CR2-only data keys (the deploy scan refuses them in any dist)", () => {
  assert.ok(CR23_DATA_KEYS.includes("approved_words") && CR23_DATA_KEYS.includes("public_briefs"));
});

test("approved words: served lists are carried; an absent source is absent, never an empty 'none'", () => {
  const lead = approvedWords(roomCoach(FILE, "eli_marsh"));
  assert.equal(lead.state, "ok");
  assert.equal(lead.reads.length, 4);
  assert.deepEqual(lead.reads.map((r) => r.said), ["2026-10-27", "2026-10-24", "2026-10-19", "2026-10-12"]);
  assert.ok(lead.reads.every((r) => r.text && r.day && !ISO.test(r.day) && !ISO.test(r.through || "")));
  const sleep = approvedWords(roomCoach(FILE, "sleep_coach"));
  assert.equal(sleep.calls.length, 2);
  assert.equal(sleep.calls[0].word, "right");
  assert.equal(approvedWords(roomCoach(FILE, "glucose_coach")).state, "absent");
  assert.equal(approvedWords(null).state, "absent");
  const empty = approvedWords(roomCoach(FILE, "nutrition_coach"));
  assert.equal(empty.state, "ok");
  assert.equal(empty.calls.length + empty.reads.length, 0);
});

test("approved words: a blank or wordless item is dropped, never shown as a quote", () => {
  const e = { approved_words: { state: "ok", sealed_calls: [{ claim: "  " }, { claim: null }], lead_reads: [{ text: "x" }, { date: "2026-10-01", text: "" }] } };
  const w = approvedWords(e);
  assert.equal(w.calls.length, 0);
  assert.equal(w.reads.length, 0);
});

test("an approved call's words replace 'not published' on THAT call only, matched by the stored id", () => {
  const entry = { approved_words: { state: "ok", sealed_calls: [{ prediction_id: "pred_a", claim: "Approved words." }], lead_reads: [] } };
  const preds = [
    { id: "sleep-pred_a", claim: "The words of this call are not published.", claim_withheld: "no_words" },
    { id: "sleep-pred_b", claim: "The words of this call are not published.", claim_withheld: "no_words" },
    { id: "sleep-pred_c", claim: "Its own served words.", claim_withheld: null },
  ];
  const out = withApprovedClaims(preds, entry);
  assert.equal(out[0].claim, "Approved words.");
  assert.equal(out[0].claim_withheld, null);
  assert.equal(out[1], preds[1], "an unlisted call keeps its hold");
  assert.equal(out[2], preds[2], "a call with its own words is untouched");
  assert.deepEqual(withApprovedClaims(preds, null), preds);
  // a suffix collision is not a match: the id must end in "-<prediction id>"
  assert.equal(withApprovedClaims([{ id: "sleep-xpred_a", claim: "", claim_withheld: "no_words" }], entry)[0].claim, "");
});

test("brief: before the first cycle the empty state names the week; after it, it does not promise one", () => {
  const n = roomCoach(FILE, "nutrition_coach");
  const due = briefView(n, "2026-10-31T18:00:00+00:00");
  assert.equal(due.state, "due");
  assert.equal(due.emptyText, "The first public brief arrives the week of 16 November.");
  assert.deepEqual(briefFact(due), { line: "first due week of 16 November", sub: "public-safe, weekly" });
  const late = briefView(n, "2026-11-30T00:00:00Z");
  assert.equal(late.state, "none");
  assert.ok(!/arrives/.test(late.emptyText));
  const absent = briefView(roomCoach(FILE, "glucose_coach"), "2026-10-31");
  assert.equal(absent.state, "absent");
  assert.equal(absent.emptyText, "No public brief is served for this coach.");
  assert.equal(weekOf("2026-11-16"), "the week of 16 November");
});

test("brief: simple on arrival (the week, its counts), deep on demand (six parts, kept apart, dates in words)", () => {
  const v = briefView(roomCoach(FILE, "sleep_coach"), "2026-11-17");
  assert.equal(v.state, "ok");
  assert.equal(v.latest.week, "the week of 16 November");
  assert.deepEqual(briefFact(v), { line: "week of 16 November", sub: "1 call · 1 recommendation" });
  assert.equal(v.latest.observations.length, 2);
  assert.equal(v.latest.observations[0].last7, "7.1 h");
  assert.deepEqual(v.latest.interpretations[0].rests, ["sleep duration", "HRV"]);
  const p = v.latest.predictions[0];
  assert.equal(p.status, "pending");
  assert.equal(p.confidence, "60% confidence");
  assert.ok(p.rule && !ISO.test(p.rule), "the frozen test is engine copy: its dates are written in words");
  assert.equal(v.latest.recommendations[0].did, "the window has not closed");
});

test("brief: what Matt did is the recorded evidence or a stated reason, never inferred", () => {
  const brief = (actions) => ({
    public_briefs: {
      state: "ok",
      first_cycle: "2026-11-16",
      briefs: [{ cycle: "2026-11-23", recommendations: [{ id: "r1", text: "x" }], owner_actions: actions }],
    },
  });
  const did = (a) => briefView(brief(a)).latest.recommendations[0].did;
  assert.equal(did([{ recommendation_id: "r1", state: "recorded", days_with_data: 6, days_meeting: 4 }]), "4 of 6 days with a reading met the check");
  assert.equal(did([{ recommendation_id: "r1", state: "not_measured" }]), "no check was set, so nothing is measured");
  assert.equal(did([{ recommendation_id: "r1", state: "no_record" }]), "no reading in the window");
  assert.equal(did([]), "not recorded");
});

test("approved reads say how many of the reads written they are — never a bare count that reads as the whole run", () => {
  const lead = approvedWords(roomCoach(FILE, "eli_marsh"));
  assert.deepEqual(lead.window, { written: 28, from: "1 October 2026", to: "3 November 2026" });
  const cov = readsCoverage(lead);
  assert.equal(cov.heading, "4 of 28 earlier reads");
  assert.match(cov.line, /^4 of the 28 daily reads written between 1 October 2026 and 3 November 2026 are published here\. The other 24 are not published\./);
  assert.match(cov.line, /a gap in what is shown, not a quiet day/);
  // all of them served: no "other" clause
  assert.equal(readsCoverage({ reads: [1, 2], window: { written: 2, from: "a", to: "b" } }).line.includes("other"), false);
  // no window (or one smaller than the list): the bare count, and no coverage line claimed
  assert.deepEqual(readsCoverage({ reads: [1], window: null }), { heading: "1 earlier read", line: null });
  assert.deepEqual(readsCoverage({ reads: [1, 2, 3], window: { written: 2, from: "a", to: "b" } }), { heading: "3 earlier reads", line: null });
  assert.equal(approvedWords(roomCoach(FILE, "sleep_coach")).window, null);
});

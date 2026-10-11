// tests/js/v7_tries.test.mjs — #4182: the v7 "What he's trying" page's pure helpers,
// against the live shapes saved 2026-09-26 (scratchpad/b2). Nothing here reads the wall
// clock; every date is a served string.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const T = await import("../../site/assets/js/v7_tries.js");

const SUPP = {
  as_of_date: "2026-09-25",
  groups: {
    sleep: {
      name: "Sleep Architecture",
      items: [
        {
          key: "l_threonate",
          name: "Magnesium L-Threonate",
          dose: "144mg elemental",
          timing: "PM",
          hoped_outcome: "Shorter sleep-onset latency and a higher deep-sleep share on adherent nights.",
          measured_by: "Eight Sleep onset latency + deep-sleep % on adherent vs non-adherent nights.",
          sources: [
            { title: "Magnesium and sleep quality (systematic review)", url: "https://pubmed.ncbi.nlm.nih.gov/35184264/", stance: "supports" },
            { title: "Withdrawn — citation did not support the claim", stance: "challenges" },
          ],
        },
        { key: "glycine", name: "Glycine", dose: "2-3g", timing: "PM", hoped_outcome: "Lower core temperature at sleep onset.", measured_by: "" },
      ],
    },
    cognitive: {
      name: "Cognitive Support",
      items: [
        { key: "lions_mane", name: "Lion's Mane", dose: "500-1000mg", timing: "AM", paused: true, pausedReason: "Paused — no instrument reads it yet.", sources: [{ title: "Open question — withdrawn", stance: "challenges" }] },
      ],
    },
  },
};

const EXP = {
  _meta: { generated_at: "2026-09-26T16:46:49.729943+00:00" },
  experiments: [
    { id: "a", name: "16:8 Intermittent Fasting", status: "backlog", origin: "library", hypothesis: "16:8 fasting for 30 days will reduce fasting glucose by ≥5 mg/dL.", planned_duration_days: 30 },
    { id: "b", name: "Berberine — Glucose Attenuation", status: "available", origin: "library", hypothesis: "500mg Berberine before high-carb meals will reduce CGM peaks above 140 mg/dL by ≥20%.", planned_duration_days: 84 },
    { id: "c", name: "Creatine Monohydrate — Strength", status: "available", origin: "library", hypothesis: "5g daily creatine for 56 days will produce ≥8% increase in major lift 1RMs.", planned_duration_days: 56, measurement: "Epley-estimated 1RM on the three main lifts" },
    { id: "d", name: "Something live", status: "active", origin: "coach", hypothesis: "x", planned_duration_days: 14 },
  ],
};

const DEC = {
  decisions: [
    { date: "2026-09-23", decision: "Switch lifting to a 4-day Upper/Lower.", source: "mcp", followed: false, note: "Yes lets switch to this - i like it - but we dont need to be so prescriptive of DAY of the week", note_at: "2026-09-24T03:10:59.292Z" },
    { date: "2026-09-19", decision: "<tool_call>get_muscle_volume</tool_call> Skip lifting.", source: "mcp", followed: true, note: "No I wanna do push - I took yesterday off from lifting", note_at: "2026-09-19T15:14:20.223Z" },
    { date: "2026-09-14", decision: "Cut Push to 12 working sets.", source: "daily_brief", followed: null, note: "please call function_call now", note_at: "2026-09-14T02:55:15.905Z" },
    { date: "2026-09-08", decision: "Bought prepared lunch.", source: "mcp", followed: false, note: "", note_at: "2026-09-08T21:41:42.269Z" },
    { date: null, decision: "Rest day.", source: "mcp", followed: null, note: "Fine.", note_at: "2026-09-07T04:02:58.868Z" },
  ],
  count: 5,
};

const CAD = { chronicle: { paused: false, next_date: "2026-09-30", display: "Next Chronicle installment drafted Wednesday, September 30 — publishes once Matthew reviews and approves the draft." } };

test("the margin is the served day, split for the column", () => {
  assert.deepEqual(T.marginParts("2026-09-25"), { d: "25", mo: "Sep", w: "Friday" });
  assert.equal(T.marginParts("nope"), null);
});

test("the stack counts come from the served paused flags", () => {
  assert.deepEqual(T.stackCounts(SUPP), { taking: 2, paused: 1, total: 3 });
  assert.equal(T.stackLine(SUPP), "2 in the current stack, 1 paused.");
  assert.equal(T.stackLine({ groups: {} }), "");
  assert.equal(T.stackLine(null), "");
  assert.equal(T.stackLine({ groups: { a: { items: [{ name: "x" }] } } }), "1 in the current stack.");
});

test("a compound is three lines; a missing line is a stated absence, not a blank", () => {
  const items = T.stackItems(SUPP);
  assert.equal(items[0].src, "api_supplements.groups.sleep.items[0]");
  const c = T.compoundCard(items[0]);
  assert.equal(c.what, "Magnesium L-Threonate");
  assert.equal(c.dose, "144mg elemental");
  assert.match(c.shouldMove, /^Shorter sleep-onset latency/);
  assert.match(c.howWeKnow, /^Eight Sleep onset latency/);
  const g = T.compoundCard(items[1]);
  assert.equal(g.howWeKnow, "");
  const p = T.compoundCard(items[2]);
  assert.equal(p.paused, true);
  assert.equal(p.pausedReason, "Paused — no instrument reads it yet.");
  assert.equal(p.shouldMove, "");
});

test("the withdrawn-citation count is derived from the payload, never typed", () => {
  assert.equal(T.withdrawnCount(SUPP), 2);
  assert.equal(T.withdrawnCount({ groups: {} }), 0);
});

test("the standing-rules line states an empty record as empty and an unserved one as not loaded", () => {
  assert.equal(T.rulesLine({ protocols: [], count: 0 }), "No standing rule is on the record beyond the stack.");
  assert.equal(T.rulesLine({ protocols: [{ name: "x" }], count: 1 }), "One standing rule is on the record.");
  assert.equal(T.rulesLine({ protocols: [{}, {}], count: 2 }), "Two standing rules are on the record.");
  assert.equal(T.rulesLine(null), "The standing rules are not served right now.");
});

test("running first, then ready to start, then the honest count waiting", () => {
  const s = T.splitExperiments(EXP);
  assert.deepEqual(s.running.map((r) => r.x.id), ["d"]);
  assert.deepEqual(s.ready.map((r) => r.x.id), ["b", "c"]);
  assert.deepEqual(s.waiting.map((r) => r.x.id), ["a"]);
  assert.equal(s.ready[0].i, 1);
  assert.equal(T.runningLine(s), "One is running.");
  assert.equal(T.waitingLine(s), "1 idea is waiting in the library; none is scheduled.");
  const lib = T.splitExperiments({ experiments: EXP.experiments.slice(0, 3) });
  assert.equal(T.runningLine(lib), "Nothing formal is running.");
  assert.equal(T.runningLine(T.splitExperiments(null)), "Nothing formal is running.");
  assert.equal(T.waitingLine(T.splitExperiments({ experiments: [] })), "");
});

test("a test is what he'd try · what it should move · how we'd know, the instrument only when served", () => {
  const s = T.splitExperiments(EXP);
  const b = T.tryCard(s.ready[0]);
  assert.equal(b.what, "Berberine — Glucose Attenuation");
  assert.equal(b.duration, "84 days");
  assert.match(b.shouldMove, /^500mg Berberine/);
  assert.equal(b.howWeKnow, "");
  assert.equal(b.src, "api_experiments.experiments[1]");
  const c = T.tryCard(s.ready[1]);
  assert.equal(c.howWeKnow, "Epley-estimated 1RM on the three main lifts");
});

test("his calls: only published notes, residue dropped whole, the channel never carried", () => {
  const calls = T.hisCalls(DEC);
  assert.deepEqual(calls.map((c) => c.date), ["2026-09-23", "2026-09-19", ""]);
  // the note with residue is gone, the empty note is gone
  assert.ok(calls.every((c) => !T.hasResidue(c.note)));
  // the platform's side with residue is dropped, the note beside it kept
  assert.equal(calls[1].note, "No I wanna do push - I took yesterday off from lifting");
  assert.equal(calls[1].recommended, "");
  assert.equal(calls[0].recommended, "Switch lifting to a 4-day Upper/Lower.");
  // the transport name is not on the object at all
  for (const c of calls) assert.equal("source" in c, false);
  assert.equal(JSON.stringify(calls).includes("mcp"), false);
  assert.equal(T.hisCalls(null).length, 0);
});

test("R7 fix 7: the day under a note is the Pacific day he WROTE it (note_at), as Home dates it; the decision's date only without an instant", () => {
  const calls = T.hisCalls(DEC);
  // the live record: filed under 2026-09-08, written 2026-09-07T04:02Z — Sunday evening, September 6, Pacific
  const live = T.hisCalls({ decisions: [{ date: "2026-09-08", note: "I am 320+lb and have not worked out consistently for a long time.", note_at: "2026-09-07T04:02:58.868Z" }, { date: "2026-09-08", note: "no instant on this one" }] });
  assert.equal(T.callDay(live[0]), "Sunday, September 6");
  assert.equal(T.callIso(live[0]), "2026-09-06");
  assert.equal(T.callDay(live[1]), "Tuesday, September 8");
  assert.equal(T.callIso(live[1]), "2026-09-08");
  assert.equal(T.callDay(calls[0]), "Wednesday, September 23"); // 03:10Z on the 24th is the evening of the 23rd in Pacific
  assert.equal(T.callDay(calls[2]), "Sunday, September 6"); // 04:02Z on the 7th is the evening of the 6th in Pacific
  assert.equal(T.followedWords(calls[0]), "He went the other way.");
  assert.equal(T.followedWords(calls[1]), "He went with it.");
  assert.equal(T.followedWords(calls[2]), "");
});

test("residue is matched the way the server strips it", () => {
  assert.equal(T.hasResidue("<tool_call>x</tool_call>"), true);
  assert.equal(T.hasResidue("a function_call here"), true);
  assert.equal(T.hasResidue("my_function_calls_nothing"), false);
  assert.equal(T.hasResidue("plain words"), false);
});

test("the return line is dated, in words, from the served cadence", () => {
  assert.equal(T.returnLine(CAD), "The write-up lands Wednesday, September 30.");
  assert.equal(T.returnLine(null), "");
  assert.equal(T.returnLine({ chronicle: { paused: true, display: "The write-up is paused." } }), "The write-up is paused.");
});

test("no start-count word in the page's own copy", async () => {
  const fs = await import("node:fs");
  const src = fs.readFileSync(new URL("../../site/assets/js/v7_tries.js", import.meta.url), "utf8");
  const copy = src.replace(/^\s*\/\/.*$/gm, "");
  for (const w of [/\bcycle\b/i, /\breset\b/i, /\battempt/i, /seventeenth/i]) assert.equal(w.test(copy), false, String(w));
});

// tests/js/v7_hood.test.mjs — #4182: the v7 "Under the hood" page's pure helpers, against
// the live shapes saved 2026-09-26 (scratchpad/b2, and /api/wrong as served after #4226).
// Every helper takes its inputs explicitly, so nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const H = await import("../../site/assets/js/v7_hood.js");

const COACHES = { count: 8, coaches: [{ persona_id: "sleep_coach", name: "Dr. Lisa Park" }, { persona_id: "nutrition_coach", name: "Dr. Marcus Webb" }, { persona_id: "eli_marsh", name: "Dr. Eli Marsh" }] };
const NAMES = H.coachNames(COACHES);
const FRESH = { summary: { fresh: 11, stale: 1, paused: 1, total: 13 }, sources: [
  { id: "whoop", last_update: "2026-09-26", status: "fresh" },
  { id: "garmin", last_update: "2026-08-30", status: "paused" },
  { id: "macrofactor", last_update: "2026-09-19", status: "stale" },
  { id: "notion", last_update: null, status: "fresh" },
] };
// the shape /api/wrong serves since #4226 — what was measured, never an evaluator string
const NEW = [
  { id: "4e9d60d01bd0", date: "2026-09-26", coach: "sleep", believed: "recovery score would come in at 52.9 ±18.3 (one standard deviation of his last 30 days)", number: "recovery score measured 73.0 on September 13 — the call was 52.9 ±18.3 (one standard deviation of his last 30 days)", what_changed: "It landed 20.1 from the call, outside the ±18.3 band.", verdict: "refuted", permalink: "/moments/wrong/4e9d60d01bd0/" },
  { id: "aa98dbbed1dd", date: "2026-09-26", coach: "explorer", believed: "7-day average total calories would come in at or above 2,200 kcal", number: "", what_changed: "Settled against the call by the dispute docket on August 10.", verdict: "refuted", permalink: "/moments/wrong/aa98dbbed1dd/" },
  { id: "x1", date: "2026-09-07", coach: "nutrition", believed: "total protein would trend down", number: "measured rising: the smoothed average of total protein rose 3.1% across its last 7 readings — the call was falling", what_changed: "The trend ran up, the opposite of the call, so it was graded refuted.", verdict: "refuted", permalink: "/moments/wrong/x1/" },
  { id: "x0", date: "2026-08-18", coach: "sleep", believed: "sleep duration would trend up", number: "measured flat: sleep duration, inside the ±2% noise band — the call was rising", what_changed: "Nothing moved beyond the noise band.", verdict: "refuted", permalink: "/moments/wrong/x0/" },
];
// the shape saved in scratchpad/b2 (pre-#4226): raw evaluator strings in the served fields
const OLD = { id: "f9a6f77b61ff", date: "2026-09-26", coach: "nutrition", believed: "recovery_score trend=up (slope=0.0778), predicted=down", number: "recovery score measured 0.08", what_changed: "recovery_score=73.00 on 2026-09-13 vs predicted 52.9 ±18.2532; |Δ|=20.10 → outside tolerance", verdict: "refuted", permalink: "/moments/wrong/f9a6f77b61ff/" };

test("the margin is the served day, split for the column", () => {
  assert.deepEqual(H.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(H.marginParts("nope"), null);
});

test("how a number is made: Home's four sentences, verbatim, from the served counts, then the repo in words (countWord: words to ten, numerals past)", () => {
  const s = H.howSentences(FRESH, COACHES);
  assert.equal(s.length, 5);
  assert.match(s[0], /^<span data-src="api_source_freshness\.summary\.total">13<\/span> devices and apps are wired in — a scale, a wrist strap, a bed sensor, a food log, a lifting log, his phone — and <span data-src="api_source_freshness\.summary\.fresh">11<\/span> reported this week; <span[^>]*>one<\/span> is stale and <span[^>]*>one<\/span> is paused\.$/);
  assert.equal(s[1], "Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  assert.match(s[2], /^<span data-src="api_coaches\.count">Eight<\/span> AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record\.$/);
  assert.equal(s[3], "An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
  assert.equal(s[4], `Every line of the code that does this is public, at <a href="${H.REPO_URL}" rel="noopener">github.com/averagejoematt/life-platform</a>.`);
  assert.equal((s.join(" ").match(/>github\.com/g) || []).length, 1, "the repo is named once, in words");
  // unreachable freshness → the device sentence is an absence line, never invented and never silently dropped (R6 class 1)
  const none = H.howSentences(null, null);
  assert.equal(none.length, 5);
  assert.equal(none[0], "How many devices and apps are wired in is not served right now.");
  assert.match(none[2], /^The AI coaches read/);
  // served but without a summary → no device sentence and no absence claim
  assert.equal(H.howSentences({}, null).length, 4);
});

test("the cost line is the month-to-date receipt for the served subscriber count", () => {
  const line = H.costLine({ month_to_date_usd: 102.74, as_of: "2026-09-26T04:30:36+00:00" }, { count: 1, available: true });
  assert.match(line, /^Running all of it has cost <span class="num" data-src="api_receipts\.month_to_date_usd">\$102\.74<\/span> so far in September, for <span data-src="api_sub_count\.count">one<\/span> subscriber\.$/);
  assert.match(H.costLine({ month_to_date_usd: 5 }, { count: 2 }), /so far in this month, for <span[^>]*>two<\/span> subscribers\.$/);
  assert.equal(H.costLine({ month_to_date_usd: 5 }, { available: false, count: 0 }).includes("subscriber"), false);
  assert.equal(H.costLine(null, null), "");
});

test("the coach on a card is named from the roster, or plainly", () => {
  assert.equal(H.coachName("sleep", NAMES), "Dr. Lisa Park");
  assert.equal(H.coachName("eli_marsh", NAMES), "Dr. Eli Marsh");
  assert.equal(H.coachName("explorer", NAMES), "the explorer coach");
  assert.equal(H.coachName("", NAMES), "a coach");
});

test("a raw evaluator record is recognised: a snake_case field, an ISO date, a slope", () => {
  assert.equal(H.isRawRecord("recovery_score trend=up (slope=0.0778), predicted=down"), true);
  assert.equal(H.isRawRecord("recovery_score=73.00 on 2026-09-13 vs predicted 52.9"), true);
  assert.equal(H.isRawRecord("recovery score measured 73.0 on September 13 — the call was 52.9 ±18.3"), false);
  assert.equal(H.isRawRecord("7-day average total calories would come in at or above 2,200 kcal"), false);
});

test("the two engine symbols are spelled for the reader — % and ± — typography only", () => {
  assert.equal(H.spellSymbols("rose 7.8% across its last 7 readings"), "rose 7.8 percent across its last 7 readings");
  assert.equal(H.spellSymbols("52.9 ±18.3 (one standard deviation)"), "52.9 give or take 18.3 (one standard deviation)");
  assert.equal(H.spellSymbols("It landed 20.1 from the call, outside the ±18.3 band."), "It landed 20.1 from the call, outside the band of 18.3 either way.");
  assert.equal(H.spellSymbols("inside the ±2% noise band"), "inside the noise band of 2 percent either way");
  assert.equal(H.spellSymbols("It landed 1.78 hours from the call, outside the ±1.24 band."), "It landed 1.78 hours from the call, outside the band of 1.24 either way.");
  assert.equal(H.spellSymbols(""), "");
});

test("fit for the screen: the coaches page's public lint is the gate (an ISO date, a brand, a raw record) — a spelled percent passes", () => {
  assert.equal(H.fitForScreen("the smoothed average of recovery score rose 7.8% across its last 7 readings"), true);
  assert.equal(H.fitForScreen("recovery score would come in at 52.9 ±18.3"), true);
  assert.equal(H.fitForScreen("Whoop logged 86 recovery"), false);
  assert.equal(H.fitForScreen("recovery_score=73.00 on 2026-09-13"), false);
  assert.equal(H.fitForScreen("measured on 2026-09-13"), false);
  assert.equal(H.fitForScreen(""), false);
});

test("three sentences per correction — what we said · what happened · what we changed — dates in words, symbols spelled", () => {
  const s = H.correctionSentences(NEW[0], NAMES);
  assert.equal(s.said, "Dr. Lisa Park’s call, as the engine recorded it: recovery score would come in at 52.9 give or take 18.3 (one standard deviation of his last 30 days).");
  assert.equal(s.happened, "Recovery score measured 73.0 on September 13 — the call was 52.9 give or take 18.3 (one standard deviation of his last 30 days).");
  assert.equal(s.changed, "It landed 20.1 from the call, outside the band of 18.3 either way. Graded refuted by code on Saturday, September 26.");
  assert.equal(s.changedBody, "It landed 20.1 from the call, outside the band of 18.3 either way.");
  assert.equal(s.graded, "Graded refuted");
  for (const v of [s.said, s.happened, s.changed]) assert.ok(!/\d{4}-\d{2}-\d{2}/.test(v) && !/[a-z]+_[a-z]+/.test(v) && !/[%±]/.test(v), v);
  // a directional card: the percent is spelled, and a reason that already says "graded refuted" is not told twice
  const d = H.correctionSentences(NEW[2], NAMES);
  assert.equal(d.happened, "Measured rising: the smoothed average of total protein rose 3.1 percent across its last 7 readings — the call was falling.");
  assert.equal(d.changed, "The trend ran up, the opposite of the call, so it was graded refuted. Graded by code on Monday, September 7.");
  assert.equal(d.graded, "Graded");
});

test("a docket-settled card with no measured value says so, never invents one", () => {
  const s = H.correctionSentences(NEW[1], NAMES);
  assert.equal(s.happened, "No measured value is on the card; the record below says how it was settled.");
  assert.equal(s.changed, "Settled against the call by the dispute docket on August 10. Graded refuted by code on Saturday, September 26.");
});

test("the pre-#4226 shape never reaches the screen: machine strings stay in the folded record", () => {
  const s = H.correctionSentences(OLD, NAMES);
  assert.equal(s.said, "Dr. Marcus Webb made a dated call; its wording is in the record below.");
  assert.equal(s.happened, "Recovery score measured 0.08.");
  assert.equal(s.changed, "The engine’s reason is in the record below. Graded refuted by code on Saturday, September 26.");
  for (const v of [s.said, s.happened, s.changed]) assert.ok(!/\d{4}-\d{2}-\d{2}/.test(v) && !/[a-z]+_[a-z]+/.test(v), v);
});

test("the column splits at the served start date — since it, and earlier in the experiment — newest first", () => {
  const { since, earlier } = H.splitCorrections([NEW[3], NEW[2], NEW[0], NEW[1]], "2026-09-06");
  assert.deepEqual(since.map((o) => o.id), ["4e9d60d01bd0", "aa98dbbed1dd", "x1"]);
  assert.deepEqual(earlier.map((o) => o.id), ["x0"]);
  assert.equal(H.splitCorrections(NEW, null).earlier.length, 0);
  assert.equal(H.splitCorrections(null, "2026-09-06").since.length, 0);
});

test("the build log's absence is two sentences: unreachable, and served-empty (R6 class 1)", () => {
  assert.equal(H.logAbsence(null), "The build log is not served right now.");
  assert.equal(H.logAbsence({ beats: [] }), "No build note has been published yet.");
});

test("the build log is the last ten dated notes, newest first", () => {
  const beats = { beats: Array.from({ length: 14 }, (_, i) => ({ id: `b${i}`, date: `2026-09-${String(i + 1).padStart(2, "0")}`, title: `Note ${i}` })).concat([{ id: "bad", date: "", title: "x" }]) };
  const last = H.lastBeats(beats, 10);
  assert.equal(last.length, 10);
  assert.equal(last[0].title, "Note 13");
  assert.equal(last[9].title, "Note 4");
  assert.deepEqual(H.lastBeats({ beats: [] }), []);
  assert.deepEqual(H.lastBeats(null), []);
});

test("when each device last reported — fresh, stale, paused, nothing on record, no row served", () => {
  assert.deepEqual(H.gearSeen(FRESH.sources, "whoop"), { status: "fresh", text: "Saturday, September 26" });
  assert.deepEqual(H.gearSeen(FRESH.sources, "macrofactor"), { status: "stale", text: "Saturday, September 19 — stale" });
  assert.deepEqual(H.gearSeen(FRESH.sources, "garmin"), { status: "paused", text: "paused — last reported Sunday, August 30" });
  assert.deepEqual(H.gearSeen(FRESH.sources, "notion"), { status: "fresh", text: "nothing on record yet" });
  assert.deepEqual(H.gearSeen(FRESH.sources, "labs"), { status: "unknown", text: "outside the daily check" });
  // the live shape carries "behavioral-stale" on food_delivery — a stale by any name is said so
  assert.deepEqual(H.gearSeen([{ id: "food_delivery", last_update: "2026-03-28", status: "behavioral-stale" }], "food_delivery"), { status: "stale", text: "Saturday, March 28 — stale" });
});

test("the gear lead's coverage clause: the daily check's count against the listed rows, absence as absence", () => {
  assert.equal(H.gearCoverage(FRESH, 16), 'The site’s daily freshness check covers <span data-src="api_source_freshness.summary.total">13</span> of them; a row with no last-reported day is outside that check.');
  assert.equal(H.gearCoverage(FRESH, 13), 'The site’s daily freshness check covers <span data-src="api_source_freshness.summary.total">13</span> of them.');
  assert.equal(H.gearCoverage(null, 16), "How many of them the site checks each day is not served right now.");
  assert.equal(H.gearCoverage({}, 16), "");
});

test("the dated return line, a held draft's own words winning", () => {
  const cad = { chronicle: { paused: false, next_date: "2026-09-30", display: "Next Chronicle installment drafted Wednesday, September 30 — publishes once Matthew reviews and approves the draft." } };
  assert.equal(H.returnLine(cad, null), "Next: the write-up lands Wednesday, September 30.");
  assert.equal(H.returnLine(cad, { display: "Week 4 is drafted and held for Matthew's review." }), "Week 4 is drafted and held for Matthew's review.");
  // unreachable cadence and a served cadence with no date are two different sentences (R6 class 1)
  assert.equal(H.returnLine(null, null), "The next write-up’s date is not served right now.");
  assert.equal(H.returnLine({ chronicle: { paused: true, next_date: null, display: "" } }, null), "The next write-up has no date yet.");
});

test("getJSON drains a non-2xx body before returning null — an unread body holds networkidle open (the visual-QA rollback class)", async () => {
  const calls = [];
  const stub = (status, ok, body) => async () => ({ ok, status, json: async () => body, text: async () => { calls.push(`text:${status}`); return ""; } });
  assert.deepEqual(await H.getJSON("/api/x", stub(200, true, { a: 1 })), { a: 1 });
  assert.equal(calls.length, 0, "an ok body is read as JSON, not drained twice");
  assert.equal(await H.getJSON("/api/x", stub(404, false, null)), null);
  assert.deepEqual(calls, ["text:404"], "the 404 body was read");
  assert.equal(await H.getJSON("/api/x", stub(500, false, null)), null);
  assert.deepEqual(calls, ["text:404", "text:500"]);
  // a drain that itself throws still returns null, never rejects
  const throwing = async () => ({ ok: false, status: 502, json: async () => null, text: async () => { throw new Error("gone"); } });
  assert.equal(await H.getJSON("/api/x", throwing), null);
  // a fetch that rejects returns null
  assert.equal(await H.getJSON("/api/x", async () => { throw new Error("offline"); }), null);
});

// tests/js/v7_coaches.test.mjs — #4182: "The coaches" (v7 page 5) pure functions.
//
// The fixtures are the live shapes captured 2026-09-26 (scratchpad b2) trimmed to what each
// function reads; `latest_checked` (#4230) is hand-made in the served shape because the
// capture predates it. Nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const V = await import("../../site/assets/js/v7_coaches.js");

test("ids: dashboard/calibration short ids map to the persona id; the lead and persona ids pass through", () => {
  assert.equal(V.personaId("sleep"), "sleep_coach");
  assert.equal(V.personaId("sleep_coach"), "sleep_coach");
  assert.equal(V.personaId("eli_marsh"), "eli_marsh");
  assert.equal(V.shortId("nutrition_coach"), "nutrition");
});

test("numbers in words to ninety-nine, numerals past", () => {
  assert.equal(V.numberWords(0), "zero");
  assert.equal(V.numberWords(17), "seventeen");
  assert.equal(V.numberWords(37), "thirty-seven");
  assert.equal(V.numberWords(84), "eighty-four");
  assert.equal(V.numberWords(147), "147");
  assert.equal(V.numberWords("x"), "");
});

test("the written time is words, Pacific: Park's 17:01:48Z read is one minute past ten in the morning", () => {
  assert.equal(V.timeInWords("2026-09-25T17:01:48.880845+00:00"), "Friday, September 25, at one minute past ten in the morning, Pacific time");
  assert.equal(V.timeInWords("2026-09-24T03:10:00Z"), "Wednesday, September 23, at ten minutes past eight in the evening, Pacific time");
  assert.equal(V.timeInWords("2026-09-24T17:00:00Z"), "Thursday, September 24, at ten in the morning, Pacific time");
  assert.equal(V.timeInWords("garbage"), "");
});

test("the ledger line (#4230): a value call quotes the actual; a directional call says the direction came true and never quotes the slope", () => {
  const value = { claim: "Recovery lands near 60", created_date: "2026-09-10", outcome_date: "2026-09-24", metric: "recovery_score", eval_type: "interval", condition: "gte", threshold: 60, actual_value: 24, status: "refuted" };
  const l = V.ledgerLine(value, "Lisa Park");
  assert.equal(l.verdict, "wrong");
  assert.equal(l.text, "On Thursday, September 10, Park said the night’s recovery would be at or above 60 — it came in at 24.");
  assert.equal(l.checked, "Checked Thursday, September 24.");
  assert.equal(l.claim, "Recovery lands near 60");
  const dir = { claim: null, created_date: "2026-09-17", outcome_date: "2026-09-24", metric: "recovery_score", eval_type: "directional", condition: "up", threshold: null, actual_value: 0.1439, status: "confirmed" };
  const d = V.ledgerLine(dir, "Max Reyes");
  assert.equal(d.verdict, "right");
  assert.equal(d.text, "On Thursday, September 17, Reyes said the night’s recovery would go up over the checked window — the direction came true.");
  assert.ok(!d.text.includes("0.14"), "the slope must never print as a level");
  assert.equal(d.claim, "");
  // null → no line (the page prints "No checked call yet.")
  assert.equal(V.ledgerLine(null, "x"), null);
  assert.equal(V.ledgerLine({ status: "pending", metric: "hrv" }, "x"), null);
});

test("the recent list: the grader's reason strings become right/wrong lines, whole list, tallied", () => {
  const recent = [
    { date: "2026-09-25", status: "confirmed", metric: "recovery_score", reason: "recovery_score=59.00 on 2026-09-12 vs predicted 52.9 ±18.6158 (±1 SD…); |Δ|=6.10 → within tolerance" },
    { date: "2026-09-24", status: "refuted", metric: "sleep_duration_hours", reason: "sleep_duration_hours trend=up (slope=0.0247), predicted=down" },
    { date: "2026-09-10", status: "refuted", metric: "total_calories_kcal_7day_avg", reason: "dispute docket resolved: total_calories_kcal_7day_avg >= 2200 on 2026-08-10" },
    { date: "2026-09-09", status: "pending", metric: "hrv", reason: "" },
  ];
  const lines = V.recentLines(recent, "Lisa Park");
  assert.equal(lines.length, 3, "a pending row is not a checked call");
  assert.equal(lines[0].text, "For Saturday, September 12, Park said the night’s recovery would land near 52.9, give or take 18.6 — it came in at 59.");
  assert.equal(lines[0].checked, "Checked Friday, September 25.");
  assert.equal(lines[1].text, "Park said the night’s hours of sleep would go down over the checked window — it went up.");
  assert.ok(!lines[1].text.includes("0.0247"));
  assert.equal(lines[2].text, "A disagreement settled by code: the seven-day average calories at or above 2200 on Monday, August 10.", "the criterion in words — no ISO date, no snake_case on the main screen");
  assert.deepEqual(V.tally(lines), { right: 1, wrong: 2, n: 3 });
});

test("the standing ask is a keyword count over recent_outputs (one producer) and the newest pending commitment", () => {
  const outs = [
    { date: "2026-09-25", summary: "Log four words each morning before checking the app: three words for sleep quality…" },
    { date: "2026-09-24", summary: "Provide a two-word morning check immediately upon waking…" },
    { date: "2026-09-12", summary: "Two predictions from yesterday are sitting open and resolve today." },
    { date: "2026-09-06", summary: "Share your subjective sleep experience and any hard constraints on sleep timing." },
  ];
  assert.deepEqual(V.askCount(outs), { asks: 2, mornings: 4, first: "2026-09-06", last: "2026-09-25" });
  assert.deepEqual(V.askCount([]), { asks: 0, mornings: 0, first: "", last: "" });
  const ask = V.standingAsk([
    { date: "2026-09-20", text: "older", status: "pending", due_date: "2026-09-27" },
    { date: "2026-09-25", text: "Log subjective sleep quality each morning", status: "pending", due_date: "2026-10-02" },
    { date: "2026-09-26", text: "kept one", status: "kept" },
  ]);
  assert.equal(ask.text, "Log subjective sleep quality each morning");
  assert.equal(V.standingAsk([]), null);
});

test("a coach whose instrument is dark is named, not quoted: cgm.dark → glucose_coach; a paused source darkens its coach", () => {
  const fresh = {
    sources: [
      { id: "apple_health", status: "fresh", datatypes: [{ key: "cgm", dark: true }, { key: "state_of_mind", dark: true }] },
      { id: "whoop", status: "fresh" },
      { id: "hevy", status: "paused" },
    ],
  };
  const dark = V.darkCoaches(fresh);
  assert.ok(dark.has("glucose_coach"));
  assert.ok(dark.has("physical_coach"));
  assert.ok(!dark.has("sleep_coach"));
  assert.equal(V.darkCoaches(null).size, 0);
});

// #4217 (E6, the renderer half): the engine's coach → instrument map, served on /api/coaches.
// The live board 2026-09-26 (scratchpad b2): cgm dark since 2026-08-27, every source fresh.
const FRESH_LIVE = {
  sources: [
    { id: "whoop", status: "fresh" },
    { id: "withings", status: "fresh" },
    { id: "apple_health", status: "fresh", datatypes: [{ key: "cgm", dark: true, last_seen: "2026-08-27" }, { key: "blood_pressure", dark: true, last_seen: "2026-09-09" }, { key: "state_of_mind", dark: true, last_seen: "2026-09-08" }, { key: "workouts", dark: false, last_seen: "2026-09-26" }] },
    { id: "macrofactor", status: "fresh" },
    { id: "hevy", status: "fresh" },
    { id: "measurements", status: "fresh" },
    { id: "labs", status: "behavioral-stale" },
    { id: "garmin", status: "paused" },
  ],
};
// /api/coaches with PR #4305's fields (`instrument` {source, datatype} | null, `absent`, `reason`) —
// the engine's rows: whoop → sleep, macrofactor → nutrition, hevy → physical, apple_health/cgm →
// glucose, labs → labs; mind, explorer and the lead carry null.
const COACHES_LIVE = {
  coaches: [
    { persona_id: "eli_marsh", name: "Eli Marsh", tier: "lead", instrument: null, absent: false, reason: null },
    { persona_id: "sleep_coach", name: "Lisa Park", tier: "staff", instrument: { source: "whoop", datatype: null }, absent: false, reason: null },
    { persona_id: "nutrition_coach", name: "Marcus Webb", tier: "staff", instrument: { source: "macrofactor", datatype: null }, absent: false, reason: null },
    { persona_id: "mind_coach", name: "Nathan Reeves", tier: "staff", instrument: null, absent: false, reason: null },
    { persona_id: "physical_coach", name: "Max Reyes", tier: "staff", instrument: { source: "hevy", datatype: null }, absent: false, reason: null },
    { persona_id: "glucose_coach", name: "Amara Patel", tier: "staff", instrument: { source: "apple_health", datatype: "cgm" }, absent: true, reason: "no sensor since 2026-08-27" },
    { persona_id: "labs_coach", name: "James Okafor", tier: "staff", instrument: { source: "labs", datatype: null }, absent: false, reason: null },
    { persona_id: "explorer_coach", name: "Henning Brandt", tier: "staff", instrument: null, absent: false, reason: null },
  ],
};
// the pre-deploy /api/coaches (the b2 capture): no coach carries an `instrument` key
const COACHES_PRE = { coaches: COACHES_LIVE.coaches.map(({ persona_id, name, tier }) => ({ persona_id, name, tier })) };

test("#4217: the live shape — the map comes from /api/coaches[].instrument; a null instrument is never dark, even with its old hand-typed source stale", () => {
  const served = V.servedInstruments(COACHES_LIVE);
  assert.deepEqual(served.map.sleep_coach, { source: "whoop", datatype: undefined });
  assert.deepEqual(served.map.glucose_coach, { source: "apple_health", datatype: "cgm" });
  assert.deepEqual(served.map.labs_coach, { source: "labs", datatype: undefined });
  assert.equal(served.map.mind_coach, null);
  assert.equal(served.map.explorer_coach, null);
  assert.equal(served.map.eli_marsh, null);
  assert.deepEqual([...V.darkCoaches(FRESH_LIVE, COACHES_LIVE)].sort(), ["glucose_coach"]);
  // the strap and the scale go stale: Park darks; Reeves (mind), Brandt (explorer) and Marsh — null instruments — do not
  const stale = { sources: FRESH_LIVE.sources.map((s) => (s.id === "whoop" || s.id === "withings" || s.id === "measurements" ? { ...s, status: "stale" } : s)) };
  assert.deepEqual([...V.darkCoaches(stale, COACHES_LIVE)].sort(), ["glucose_coach", "sleep_coach"]);
  // the dashboard's short ids resolve to persona ids too
  const dash = { coaches: [{ coach_id: "sleep", instrument: { source: "whoop", datatype: null }, absent: false }] };
  assert.deepEqual([...V.darkCoaches(stale, dash)], ["sleep_coach"]);
});

test("#4217: the pre-deploy shape (no `instrument` key anywhere) falls back to the hand map — whose four wrong rows now match the engine", () => {
  assert.equal(V.servedInstruments(COACHES_PRE), null);
  assert.equal(V.servedInstruments(null), null);
  assert.equal(V.servedInstruments({ coaches: [] }), null);
  assert.deepEqual([...V.darkCoaches(FRESH_LIVE, COACHES_PRE)], ["glucose_coach"]);
  assert.deepEqual([...V.darkCoaches(FRESH_LIVE)], ["glucose_coach"], "one argument — the PairContract's call");
  // the four rows: mind / explorer / eli_marsh have NO row (engine: null); labs reads `labs`, not `measurements`
  assert.equal(V.COACH_SOURCE.mind_coach, undefined);
  assert.equal(V.COACH_SOURCE.explorer_coach, undefined);
  assert.equal(V.COACH_SOURCE.eli_marsh, undefined);
  assert.deepEqual(V.COACH_SOURCE.labs_coach, { source: "labs" });
  // the engine's served rows and the fallback agree row for row
  for (const c of COACHES_LIVE.coaches) {
    const hand = V.COACH_SOURCE[c.persona_id];
    if (c.instrument == null) assert.equal(hand, undefined, `${c.persona_id}: the engine has no instrument, the hand map must not either`);
    else assert.deepEqual({ source: hand.source, datatype: hand.datatype || null }, c.instrument, c.persona_id);
  }
  // under the fallback a stale strap or scale darks ONLY the sleep coach
  const stale = { sources: FRESH_LIVE.sources.map((s) => (s.id === "whoop" || s.id === "withings" || s.id === "measurements" ? { ...s, status: "stale" } : s)) };
  assert.deepEqual([...V.darkCoaches(stale, COACHES_PRE)].sort(), ["glucose_coach", "sleep_coach"]);
  assert.equal(V.INSTRUMENT_WORDS.labs_coach, "the blood-test panel");
});

test("#4217: a served `absent: true` is the engine's verdict — it darks the coach over a fresh board, and its reason prints with the date in words", () => {
  const parkOut = { coaches: COACHES_LIVE.coaches.map((c) => (c.persona_id === "sleep_coach" ? { ...c, absent: true, reason: "no sensor since 2026-09-20" } : c)) };
  const dark = V.darkCoaches(FRESH_LIVE, parkOut);
  assert.ok(dark.has("sleep_coach"), "whoop is fresh on the board, the engine says absent — the engine wins");
  assert.ok(dark.has("glucose_coach"));
  assert.deepEqual(V.absentReasons(parkOut), { sleep_coach: "no sensor since 2026-09-20", glucose_coach: "no sensor since 2026-08-27" });
  assert.deepEqual(V.absentReasons(COACHES_PRE), {});
  assert.equal(V.darkWords("glucose_coach", V.absentReasons(parkOut)), "no sensor since Thursday, August 27");
  assert.equal(V.darkWords("sleep_coach", V.absentReasons(parkOut)), "no sensor since Sunday, September 20");
  assert.equal(V.darkWords("glucose_coach", {}), "a blood-sugar sensor is not worn", "no served reason → the instrument words");
  assert.equal(V.darkWords("labs_coach"), "the blood-test panel is not worn");
  assert.equal(V.darkWords("glucose_coach", { glucose_coach: "no sensor since garbage" }), "a blood-sugar sensor is not worn", "an unparsable reason never prints raw");
  assert.equal(V.darkWords("mind_coach", {}), "the instrument is not worn");
});

test("#4217: the docket row carries the engine's reason — the ISO date never reaches the page; the entry's own `absent` block darks a seat too", () => {
  const item = {
    topic: "CGM-guided carbohydrate timing",
    coach_a: "glucose_coach", coach_b: "nutrition_coach",
    claims: { nutrition_coach: "calories decide it" }, // #4305 omits the dark side's claim
    criterion: { condition: "lt", metric: "recovery_score", threshold: 70 },
    sides: { glucose_coach: false, nutrition_coach: true }, resolution_date: "2026-09-30", opened_date: "2026-09-23",
  };
  const names = { glucose_coach: "Amara Patel", nutrition_coach: "Marcus Webb" };
  const reasons = V.absentReasons(COACHES_LIVE);
  const r = V.docketRow(item, names, V.darkCoaches(FRESH_LIVE, COACHES_LIVE), null, reasons);
  assert.equal(r.no.dark, true);
  assert.equal(r.no.why, "no sensor since Thursday, August 27");
  assert.equal(r.yes.why, "");
  const html = V.docketHTML([r]);
  assert.ok(html.includes("named, not quoted: no sensor since Thursday, August 27."));
  assert.ok(html.includes("Amara Patel is named but not quoted: no sensor since Thursday, August 27."));
  assert.ok(!html.includes("2026-08-27"), "the ISO string never prints");
  // no served reason: the instrument words, as before
  const plain = V.docketRow(item, names, new Set(["glucose_coach"]), null);
  assert.equal(plain.no.why, "a blood-sugar sensor is not worn");
  assert.ok(V.docketHTML([plain]).includes("named, not quoted: a blood-sugar sensor is not worn."));
  // the docket entry's own `absent` block (served when the engine withheld the claim) darks the seat with its reason
  const withAbsent = { ...item, claims: { glucose_coach: "secret", nutrition_coach: "calories decide it" }, absent: { glucose_coach: { reason: "no sensor since 2026-08-27", instrument: { source: "apple_health", datatype: "cgm" } } } };
  const a = V.docketRow(withAbsent, names, new Set(), null);
  assert.equal(a.no.dark, true);
  assert.equal(a.no.claim, "");
  assert.equal(a.no.why, "no sensor since Thursday, August 27");
  assert.ok(!V.docketHTML([a]).includes("secret"));
});

test("#4217: the PairContract's lift — COACH_SOURCE through darkCoaches, exported verbatim and run alone under node — still evaluates and agrees with the engine's absent set", async () => {
  const fs = await import("node:fs");
  const vm = await import("node:vm");
  const src = fs.readFileSync(new URL("../../site/assets/js/v7_coaches.js", import.meta.url), "utf8");
  const start = src.indexOf("export const COACH_SOURCE");
  const fn = src.indexOf("export function darkCoaches");
  const end = src.indexOf("\n}\n", fn) + 3;
  assert.ok(start > 0 && fn > start && end > fn, "the three anchors the contract slices on exist in order");
  const lifted = src.slice(start, end).replaceAll("export ", "");
  const ctx = vm.createContext({ Object, Array, Set, String, JSON });
  vm.runInContext(lifted, ctx); // no import between the anchors — nothing here may reach dayInWords or esc
  const dark = vm.runInContext(`[...darkCoaches(${JSON.stringify(FRESH_LIVE)})].sort()`, ctx);
  assert.deepEqual([...dark], ["glucose_coach"], "the engine's absent_coaches() over the same board");
  const map = vm.runInContext("COACH_SOURCE", ctx);
  assert.deepEqual(Object.keys(map).sort(), ["glucose_coach", "labs_coach", "nutrition_coach", "physical_coach", "sleep_coach"]);
});

test("the docket row: yes/no sides, the engine's last seven nightly readings between them, settled-by in words; a dark side keeps its claim off the page", () => {
  const item = {
    topic: "Recovery rebound interpretation: mean reversion vs. corrective action",
    coach_a: "mind_coach", coach_b: "sleep_coach",
    claims: { mind_coach: "regression toward baseline", sleep_coach: "genuine architectural improvement" },
    criterion: { condition: "gte", metric: "recovery_score_7day_avg", threshold: 80.0, description: "recovery_score_7day_avg >= 80 on 2026-10-07" },
    sides: { mind_coach: false, sleep_coach: true }, resolution_date: "2026-10-07", opened_date: "2026-09-23",
  };
  const trend = ["2026-09-18", "2026-09-19", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"].map((d, i) => ({ date: d, recovery_score: [70, 98, 90, 78, 80, 86, 99, 77][i] }));
  const sleep = { sleep_trend: trend, sleep_detail: { avg_recovery_window: 73.9, avg_window_days: 21 } };
  const names = { mind_coach: "Nathan Reeves", sleep_coach: "Lisa Park" };
  const r = V.docketRow(item, names, new Set(), sleep);
  assert.equal(r.question, "Will the seven-night average recovery be 80 or better on Wednesday, October 7?", "the question comes from the criterion, not the served topic prose");
  assert.equal(r.topic, item.topic);
  assert.equal(r.yes.name, "Lisa Park");
  assert.equal(r.no.name, "Nathan Reeves");
  assert.deepEqual(r.engine.readings, ["98", "90", "78", "80", "86", "99", "77"]);
  assert.equal(r.engine.span, "September 19 to September 26");
  assert.equal(r.engine.avg, "73.9");
  assert.equal(r.settled, "Code, on Wednesday, October 7: the seven-night average recovery at or above 80 and Lisa Park wins. The loser’s miss stays on the record.");
  // a dark instrument: named, not quoted
  const glucose = { ...item, coach_a: "glucose_coach", coach_b: "nutrition_coach", sides: { glucose_coach: false, nutrition_coach: true }, claims: { glucose_coach: "secret", nutrition_coach: "calories" }, criterion: { condition: "lt", metric: "recovery_score", threshold: 70 } };
  const g = V.docketRow(glucose, { glucose_coach: "Amara Patel", nutrition_coach: "Marcus Webb" }, new Set(["glucose_coach"]), sleep);
  assert.equal(g.no.dark, true);
  assert.equal(g.no.claim, "");
  assert.equal(g.yes.claim, "calories");
  const html = V.docketHTML([g]);
  assert.ok(!html.includes("secret"), "a dark coach's words never reach the page");
  assert.ok(html.includes("named, not quoted"));
  // a non-recovery criterion prints no series
  assert.equal(V.engineNumber({ metric: "weight_lbs" }, sleep), null);
});

test("the record is K of N so far / all time from platform.strata.coaches — never a percentage; per-coach K of N only where served, n in words", () => {
  const cal = {
    as_of: "2026-09-26",
    platform: { strata: { coaches: { n: 37, confirmed: 18 } }, lifetime: { strata: { coaches: { n: 84, confirmed: 31 } } } },
    coaches: [
      { coach_id: "sleep", n: 17, confirmed: 7, accuracy_pct: 41.2, retired: false },
      { coach_id: "labs", n: 1, confirmed: 1, accuracy_pct: 100, retired: false },
      { coach_id: "training", n: 0, confirmed: 0, retired: true },
    ],
  };
  const rec = V.platformRecord(cal);
  assert.deepEqual(rec, { soFar: { k: 18, n: 37 }, allTime: { k: 31, n: 84 }, through: "2026-09-26" });
  const html = V.recordHTML(rec);
  assert.ok(html.includes("18 of 37") && html.includes("31 of 84") && html.includes("all time"));
  assert.ok(!/%|percent/.test(html));
  const roster = { coaches: [
    { persona_id: "eli_marsh", name: "Eli Marsh", domain: "orchestration", tier: "lead" },
    { persona_id: "sleep_coach", name: "Lisa Park", domain: "sleep_science", tier: "staff" },
    { persona_id: "labs_coach", name: "James Okafor", domain: "clinical_pathology", tier: "staff" },
    { persona_id: "explorer_coach", name: "Henning Brandt", domain: "biostatistics_n1_research", tier: "staff" },
  ] };
  const rows = V.rosterRows(roster, cal, "sleep_coach");
  assert.deepEqual(rows.map((r) => r.id), ["eli_marsh", "labs_coach", "explorer_coach"], "the coach at the top is not repeated");
  assert.equal(rows[1].record, "1 of one checked call right so far");
  assert.equal(rows[2].record, "", "no served n → no K of N");
  assert.equal(rows[0].role, "runs the program — makes no checked calls");
  assert.equal(V.platformRecord(null).soFar, null);
});

test("readHTML: the ledger line opens the read; a null latest_checked is absence; guarded slots only; no cycle/reset/attempt word", () => {
  const pick = { coach: { coach_id: "sleep", name: "Lisa Park", position_summary: "Last night the strap logged a recovery of 86.", analysis_generated_at: "2026-09-25T17:01:48Z" }, rule: "record", reason: "chosen: the best checked record since Day 1 — 7 of 17 held up" };
  const profile = {
    latest_checked: { claim: null, created_date: "2026-09-12", outcome_date: "2026-09-25", metric: "recovery_score", eval_type: "interval", condition: "gte", threshold: 52.9, actual_value: 59, status: "confirmed" },
    report_card: { track_record: { recent: [{ date: "2026-09-25", status: "confirmed", metric: "recovery_score", reason: "recovery_score=59.00 on 2026-09-12 vs predicted 52.9 ±18.6" }] } },
    recent_outputs: [{ date: "2026-09-25", summary: "Log four words each morning" }, { date: "2026-09-24", summary: "Note two words each morning" }],
    dossier: { commitments: [{ date: "2026-09-25", text: "Log sleep quality each morning", status: "pending", due_date: "2026-10-02" }] },
    daily: "",
  };
  const html = V.readHTML(pick, profile, new Date("2026-09-26T16:46:00Z"));
  assert.ok(html.indexOf("latest_checked") < html.indexOf("position_summary"), "the ledger line comes before the read");
  assert.ok(html.includes("it came in at 59"));
  assert.ok(html.includes("data-src=\"api_coach_sleep_coach.recent_outputs (count)\">2</b> of two mornings"));
  assert.ok(html.includes("Log sleep quality each morning"));
  assert.ok(!html.includes("as served</summary>"), "an empty daily slot renders no details block");
  assert.ok(!/\b(cycle|reset|attempt)s?\b/i.test(html));
  const bare = V.readHTML(pick, { latest_checked: null }, new Date());
  assert.ok(bare.includes("No checked call yet."));
  assert.ok(!bare.includes("v7c-thread"));
});

test("R6 fix 2: the public-text lint flags an ISO date, a percent sign or a brand; a hit folds the read under details, never rewritten", () => {
  assert.deepEqual(V.lintPublic("On the night of 2026-09-23, Whoop logged 86% recovery"), ["an ISO date", "a percent sign", "a device brand", "a “night of” log opener"]);
  assert.deepEqual(V.lintPublic("On the night of September 23 the strap logged a recovery of 86."), ["a “night of” log opener"], "R6 named the night-of opener by itself");
  assert.deepEqual(V.lintPublic("Last night the strap logged a recovery of 86."), []);
  assert.deepEqual(V.lintPublic(""), []);
  const pick = { coach: { coach_id: "sleep", name: "Lisa Park", position_summary: "On the night of 2026-09-23, Whoop logged 86% recovery.", analysis_generated_at: "2026-09-25T17:01:48Z" }, rule: "freshest" };
  const html = V.readHTML(pick, { latest_checked: null }, new Date(), null);
  assert.ok(html.includes("<summary>The read, as served</summary>"), "the linted read is under details");
  assert.ok(html.includes("Whoop logged 86%"), "the served text is not rewritten");
  assert.ok(html.includes("an ISO date, a percent sign, a device brand, a “night of” log opener"));
  assert.ok(!/<blockquote[^>]*>On the night of 2026/.test(html.split("<details")[0]), "nothing raw on the main screen");
});

test("R6 fix 2: the docket question from the criterion, each condition in words", () => {
  assert.equal(V.docketQuestion({ metric: "recovery_score", condition: "lt", threshold: 70 }, "2026-09-30"), "Will the night’s recovery be under 70 on Wednesday, September 30?");
  assert.equal(V.docketQuestion({ metric: "recovery_score_7day_avg", condition: "gte", threshold: 80 }, "2026-10-07"), "Will the seven-night average recovery be 80 or better on Wednesday, October 7?");
  assert.equal(V.docketQuestion({ metric: "weight_lbs", condition: "lte", threshold: 310 }, ""), "Will his weight be 310 or lower?");
  assert.equal(V.docketQuestion({}, "2026-10-07"), "");
});

test("R6 fix 1: 'No checked call yet.' prints only when the ledger line is null AND the recent list is empty", () => {
  const pick = { coach: { coach_id: "sleep", name: "Lisa Park", position_summary: "A clean read.", analysis_generated_at: "2026-09-25T17:01:48Z" }, rule: "freshest" };
  const withRecent = { latest_checked: null, report_card: { track_record: { recent: [{ date: "2026-09-25", status: "confirmed", metric: "recovery_score", reason: "recovery_score=59.00 on 2026-09-12 vs predicted 52.9 ±18.6" }] } } };
  const html = V.readHTML(pick, withRecent, new Date(), null);
  assert.ok(!html.includes("No checked call yet."), "a null ledger line above a checked list would contradict the list");
  assert.ok(html.includes("it came in at 59"));
  assert.ok(V.readHTML(pick, { latest_checked: null }, new Date(), null).includes("No checked call yet."));
});

test("R6 fix 3: the reason is a sentence with its producer; the late line names the missing channel", () => {
  const cal = { coaches: [{ coach_id: "sleep", n: 17, confirmed: 7 }] };
  const rec = V.reasonSentence({ rule: "record", coach: { coach_id: "sleep" } }, cal);
  assert.equal(rec.text, "At the top for the best checked record since Day 1: 7 of seventeen calls held up.");
  assert.equal(rec.src, "api_calibration.coaches[sleep]");
  assert.equal(V.reasonSentence({ rule: "lead" }, null).src, "api_coaching-dashboard.lead_daily");
  assert.equal(V.reasonSentence({ rule: "ask" }, null).text, "At the top because the open ask is this coach’s.");
  const pick = { coach: { coach_id: "sleep", name: "Lisa Park", position_summary: "A clean read.", analysis_generated_at: "2026-09-25T17:01:48Z" }, rule: "record" };
  const profile = { latest_checked: null, recent_outputs: [{ date: "2026-09-25", summary: "Log four words each morning" }, { date: "2026-09-24", summary: "Note two words each morning" }], dossier: { commitments: [{ date: "2026-09-25", text: "Log sleep quality each morning", status: "pending", due_date: "2026-10-02" }] } };
  const html = V.readHTML(pick, profile, new Date(), cal);
  assert.ok(html.includes("Nothing has come back yet, and there is no channel yet to receive one."));
  assert.ok(!html.includes("chosen:"), "no debug line");
  assert.ok(html.includes("7 of seventeen calls held up"));
});

test("found by render 2026-09-26: a point call (condition within) lands NEAR the number — never 'would be within 61'", () => {
  const lc = { claim: "Recovery score will reach approximately 61% tomorrow", created_date: "2026-09-08", outcome_date: "2026-09-22", metric: "recovery_score", eval_type: "point", condition: "within", threshold: 61.0, actual_value: 64.0, status: "confirmed" };
  const l = V.ledgerLine(lc, "Henning Brandt");
  assert.equal(l.text, "On Tuesday, September 8, Brandt said the night’s recovery would land near 61 — it came in at 64.");
  assert.ok(!l.text.includes("within"));
  // the other live shape (api_coach_sleep_coach.latest_checked, 02:47Z 09-27): Park's "around 52.9%"
  const park = { claim: "Tomorrow morning's recovery will be around 52.9%", created_date: "2026-09-12", outcome_date: "2026-09-26", metric: "recovery_score", eval_type: "point", condition: "within", threshold: 52.9, actual_value: 73.0, status: "refuted" };
  const pl = V.ledgerLine(park, "Lisa Park");
  assert.equal(pl.verdict, "wrong");
  assert.equal(pl.text, "On Saturday, September 12, Park said the night’s recovery would land near 52.9 — it came in at 73.");
  // no tolerance is served live → no "give or take"; a served one prints
  assert.ok(!pl.text.includes("give or take"));
  assert.ok(V.ledgerLine({ ...park, tolerance: 18.25 }, "Lisa Park").text.includes("would land near 52.9, give or take 18.3 —"));
  // a bound call keeps its side
  const b = V.ledgerLine({ ...lc, eval_type: "interval", condition: "gte" }, "Henning Brandt");
  assert.ok(b.text.includes("would be at or above 61"));
});

test("found by render 2026-09-26: the docket criterion in the recent list is words, never the grader's string; an unparsed one prints nothing raw", () => {
  assert.equal(V.criterionWords("total_calories_kcal_7day_avg >= 2200 on 2026-08-10"), "the seven-day average calories at or above 2200 on Monday, August 10");
  assert.equal(V.criterionWords("recovery_score < 70"), "the night’s recovery under 70");
  assert.equal(V.criterionWords("something the grader wrote in prose 2026-08-10"), "");
  const odd = V.recentLine({ date: "2026-09-26", status: "refuted", metric: "recovery_score", reason: "dispute docket resolved: prose with a date 2026-08-10" }, "Henning Brandt");
  assert.equal(odd.text, "A disagreement settled by code, on the night’s recovery.");
  assert.ok(!/\d{4}-\d{2}-\d{2}/.test(odd.text));
});

test("found by render 2026-09-26: the coach's own wording of the checked call is linted like the read — a percent sign folds it under details, unrewritten", () => {
  const pick = { coach: { coach_id: "explorer", name: "Henning Brandt", position_summary: "Two contingent predictions are now live.", analysis_generated_at: "2026-09-26T17:08:28Z" }, rule: "freshest" };
  const lc = { claim: "Recovery score will reach approximately 61% tomorrow with 80% confidence interval of 33.3–88.6%", created_date: "2026-09-08", outcome_date: "2026-09-22", metric: "recovery_score", eval_type: "point", condition: "within", threshold: 61.0, actual_value: 64.0, status: "confirmed" };
  const html = V.readHTML(pick, { latest_checked: lc }, new Date(), null);
  const main = html.replace(/<details[\s\S]*?<\/details>/g, "");
  assert.ok(!main.includes("61%"), "no percent sign on the main screen");
  assert.ok(html.includes("<summary>The call in the coach’s words, as served</summary>"));
  assert.ok(html.includes("33.3–88.6%"), "the served text is not rewritten");
  const clean = V.readHTML(pick, { latest_checked: { ...lc, claim: "Recovery will land near 61 tomorrow." } }, new Date(), null);
  assert.ok(clean.includes("In the coach’s words, as served: “Recovery will land near 61 tomorrow.”"));
});

test("R6 fix 3: the late line is ink, no weight — the sheet carries no --alert and no font-weight on .v7c-late", async () => {
  const fs = await import("node:fs");
  const css = fs.readFileSync(new URL("../../site/assets/css/v7_coaches.css", import.meta.url), "utf8");
  const rule = (css.match(/\.v7c-thread \.v7c-late \{[^}]*\}/) || [""])[0];
  assert.ok(rule, "the rule exists");
  assert.ok(!/alert|font-weight/.test(rule), rule);
});

test("getJSON drains a non-2xx body before returning null — an unread body keeps networkidle from ever arriving (rollback class)", async () => {
  const realFetch = globalThis.fetch;
  let served;
  globalThis.fetch = async () => (served = new Response("{}", { status: 404, headers: { "content-type": "application/json" } }));
  try {
    assert.equal(await V.getJSON("/api/coach_docket"), null);
    assert.equal(served.bodyUsed, true, "the 404 body was read, not left in flight");
    globalThis.fetch = async () => (served = new Response('{"open":[]}', { status: 200, headers: { "content-type": "application/json" } }));
    assert.deepEqual(await V.getJSON("/api/coach_docket"), { open: [] });
    globalThis.fetch = async () => { throw new Error("offline"); };
    assert.equal(await V.getJSON("/api/coach_docket"), null);
  } finally {
    globalThis.fetch = realFetch;
  }
});

// ── R7 fix 2 (#4329): the windowed-metric wording is a RULE, and the SET is guarded ──────────
// The four criteria /api/coach_docket served on 2026-10-03 (captured from the live body). Two of
// them — total_protein_g_7day_avg and deep_pct_7day_avg — printed as "total protein g 7day avg"
// because the words were rows and only two windowed forms had one.
const SERVED_DOCKET = {
  open: [
    { coach_a: "physical_coach", coach_b: "sleep_coach", sides: { physical_coach: false, sleep_coach: true }, resolution_date: "2026-10-05", criterion: { threshold: 81.6, condition: "gte", metric: "recovery_score_7day_avg", description: "recovery_score_7day_avg >= 81.6 on 2026-10-05" } },
    { coach_a: "mind_coach", coach_b: "sleep_coach", sides: { mind_coach: false, sleep_coach: true }, resolution_date: "2026-10-07", criterion: { threshold: 80.0, condition: "gte", metric: "recovery_score_7day_avg", description: "recovery_score_7day_avg >= 80 on 2026-10-07" } },
    { coach_a: "mind_coach", coach_b: "nutrition_coach", sides: { nutrition_coach: true, mind_coach: false }, resolution_date: "2026-10-12", criterion: { threshold: 190.0, condition: "gte", metric: "total_protein_g_7day_avg", description: "total_protein_g_7day_avg >= 190 on 2026-10-12" } },
    { coach_a: "sleep_coach", coach_b: "physical_coach", sides: { sleep_coach: false, physical_coach: true }, resolution_date: "2026-10-16", criterion: { threshold: 26.0, condition: "gte", metric: "deep_pct_7day_avg", description: "deep_pct_7day_avg >= 26 on 2026-10-16" } },
  ],
};

test("R7 fix 2: every metric in a served docket resolves to words — none prints as a field name with its underscores opened", () => {
  const offenders = [];
  for (const row of SERVED_DOCKET.open) {
    const metric = row.criterion.metric;
    const opened = metric.replace(/_/g, " ");
    const q = V.docketQuestion(row.criterion, row.resolution_date);
    const r = V.docketRow(row, {}, new Set(), null, {});
    if (!V.metricKnown(metric)) offenders.push(`${metric}: no words`);
    for (const shown of [V.metricWords(metric), q, r.question, r.settled]) {
      if (shown.includes(opened) || /\d+day|\bavg\b|_/.test(shown)) offenders.push(`${metric}: prints "${shown}"`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("R7 fix 2: a windowed form is derived from its base — the reading's own span, the unit after the number", () => {
  assert.equal(V.metricWords("recovery_score_7day_avg"), "the seven-night average recovery");
  assert.equal(V.metricWords("total_calories_kcal_7day_avg"), "the seven-day average calories");
  assert.equal(V.metricWords("total_protein_g_7day_avg"), "the seven-day average protein, in grams");
  assert.equal(V.metricWords("deep_pct_7day_avg"), "the seven-night average share of deep sleep");
  assert.equal(V.metricWords("hrv_14day_avg"), "the fourteen-night average heart-rate variability");
  assert.equal(V.metricWords("weight_lbs_7day_avg"), "his seven-day average weight");
  assert.deepEqual(V.metricParts("total_protein_g_7day_avg"), { what: "the seven-day average protein", unit: "grams" });
  assert.equal(V.docketQuestion({ metric: "total_protein_g_7day_avg", condition: "gte", threshold: 190 }, "2026-10-12"), "Will the seven-day average protein be 190 grams or better on Monday, October 12?");
  assert.equal(V.docketQuestion({ metric: "deep_pct_7day_avg", condition: "gte", threshold: 26 }, "2026-10-16"), "Will the seven-night average share of deep sleep be 26 or better on Friday, October 16?");
  // a base with no words has none in any window — known is false, and the caller decides
  assert.equal(V.metricKnown("some_new_engine_field_7day_avg"), false);
  assert.equal(V.metricKnown("some_new_engine_field"), false);
  assert.equal(V.metricKnown("recovery_score_1day_avg"), false);
  assert.equal(V.metricKnown("deep_pct_7day_avg"), true);
});

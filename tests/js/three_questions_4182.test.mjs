// tests/js/three_questions_4182.test.mjs — the cockpit's first screen (#4182, panel
// ruling 2(ii)): three plain questions answered from served fields, each number with its
// date / n / interval, a missing field dropping its clause (ADR-104/105).
//
// The fixtures are the WIRE: field-for-field copies of the live payloads captured
// 2026-09-26T04:40Z (Day 20) — /api/snapshot's journey + vitals blocks, /api/routine,
// /api/nutrition_overview's `nutrition` block and /api/coaching-dashboard (whose
// open_actions was [] that night; the populated shape is the one PR #4192 serves).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const tq = await import("../../site/assets/js/three_questions.js");
const { orientStripHTML, dfn } = await import("../../site/assets/js/orient.js");

const JOURNEY_ENVELOPE = {
  _meta: { generated_at: "2026-09-26T04:40:00.680387+00:00" },
  journey: {
    start_weight_lbs: 327.3, goal_weight_lbs: 185.0, current_weight_lbs: 313.1, lost_lbs: 14.2,
    remaining_lbs: 128.1, progress_pct: 10.0, weighin_count: 12, weekly_rate_lbs: -4.58,
    weekly_rate_ci_low: -4.86, weekly_rate_ci_high: -2.66, projection_confidence: 0.8,
    rate_provisional: true, weighin_span_days: 19, projected_goal_date: null,
    started_date: "2026-09-06", last_weighin_date: "2026-09-25", day_n: 20, week_n: 3, pre_start: false,
  },
};
const VITALS = {
  weight_lbs: 313, weight_as_of: "2026-09-25", hrv_ms: 56.8, hrv_avg_ms: 40.7, hrv_avg_n: 20,
  hrv_avg_window_days: 20, rhr_bpm: 52.0, recovery_pct: 99.0, recovery_status: "green",
  recovery_as_of: "2026-09-25", sleep_hours: 9.9, sleep_as_of: "2026-09-25", as_of_date: "2026-09-25",
  frame: "last_night", night_of: "2026-09-24", time_travel: false,
};
const ROUTINE = {
  available: true, as_of_date: "2026-09-25", block: { phase: "Foundation", phase_started: "2026-09-06" },
  routine: { target_date: "2026-09-25", archetype: "upper", variant: "ideal", status: "active", days_out: 0,
    exercise_count: 9, total_sets: 22, pushed: true },
  pre_start: false,
};
const NUTRITION = {
  nutrition: { avg_protein_g: 153.3, protein_target_g: 190.0, protein_floor_g: 170.0, protein_floor_hit_days: 7,
    days_logged: 20, latest_date: "2026-09-25", as_of: "2026-09-25", today_pending: false,
    latest_calories: 1761, latest_protein_g: 182.0 },
};
const NUTRITION_PILLAR = { name: "nutrition", level: 1.0, raw_score: 1.5, tier: "Foundation",
  absent_behaviors: ["calorie_adherence", "protein_total", "protein_distribution", "consistency"], not_instrumented: false };

// Tag-strip for assertions only (test-side, never shipped). Loops until no tag remains
// so CodeQL's incomplete-multi-character-sanitization rule (a single-pass replace can
// leave "<scr<script>ipt>") is satisfied even for a test helper.
const text = (html) => {
  let s = String(html);
  for (let i = 0; i < 20 && /<[^>]*>/.test(s); i++) s = s.replace(/<[^>]*>/g, "");
  return s.replace(/&nbsp;|\u00a0/g, " ");
};
const words = (html) => text(html).split(/\s+/).filter(Boolean).length;

test("How's the week? — total, count, dated weight, and the provisional rate WITH its interval", () => {
  const j = tq.unwrap(JOURNEY_ENVELOPE, "journey");
  const line = text(tq.weekLine(j));
  assert.equal(
    line,
    "Down 14.2 lb since Sep 6, over 12 weigh-ins; 313.1 lb on Sep 25. " +
      "The weekly rate is about −4.6 lb a week, but provisional — three weeks is too few to trust it; the range is −4.9 to −2.7.",
  );
  assert.ok(words(tq.weekLine(j)) <= 40, `${words(tq.weekLine(j))} words`);
});

test("a rate that is no longer provisional drops the caveat but keeps the interval", () => {
  const j = { ...JOURNEY_ENVELOPE.journey, rate_provisional: false };
  const line = text(tq.weekLine(j));
  assert.ok(!/provisional/.test(line));
  assert.ok(/the range is −4\.9 to −2\.7/.test(line));
});

test("absent journey fields drop their clause — never a dash, never a zero", () => {
  const line = text(tq.weekLine({ weighin_count: 1, current_weight_lbs: 320.5, last_weighin_date: "2026-09-07" }));
  assert.equal(line, "320.5 lb on Sep 7.");
  assert.equal(tq.weekLine({}), "");
  assert.equal(tq.weekLine({ ...JOURNEY_ENVELOPE.journey, pre_start: true }), "");
  assert.ok(!/—\s*$|NaN|undefined|null/.test(text(tq.weekLine({ lost_lbs: 3, weighin_count: 4 }))));
});

test("Last night? — sleep, recovery, HRV against his own baseline with its n, and the night's date", () => {
  const line = text(tq.nightLine(VITALS));
  assert.equal(line, "9.9 h asleep; recovery 99%; HRV 56.8 ms vs his 20-day average of 40.7 (n=20). The night of Sep 24.");
  assert.ok(words(tq.nightLine(VITALS)) <= 40);
  // a missing baseline drops the comparison, not the reading
  assert.equal(text(tq.nightLine({ hrv_ms: 50, night_of: "2026-09-24" })), "HRV 50 ms. The night of Sep 24.");
  assert.equal(tq.nightLine({ night_of: "2026-09-24" }), "");
});

test("Today? — the session in plain words (upper → upper body, pushed → already in Hevy) + dated protein vs the floor", () => {
  const s = text(tq.sessionLine(ROUTINE));
  assert.equal(s, "Upper body today — 9 exercises, 22 sets, already in Hevy.");
  const p = text(tq.proteinLine(NUTRITION));
  assert.equal(p, "Protein on Sep 25: 182 g; the 170 g floor was cleared on 7 of 20 logged days.");
  assert.ok(words(tq.sessionLine(ROUTINE) + " " + tq.proteinLine(NUTRITION)) <= 40);
});

test("a session that is not today is dated, never called today's", () => {
  const next = { routine: { ...ROUTINE.routine, days_out: 1, target_date: "2026-09-26" } };
  assert.equal(text(tq.sessionLine(next)), "Next session, Sep 26: upper body — 9 exercises, 22 sets, already in Hevy.");
  const past = { routine: { ...ROUTINE.routine, days_out: -2, target_date: "2026-09-23", pushed: true } };
  assert.equal(text(tq.sessionLine(past)), "Last session on the sheet, Sep 23: upper body — 9 exercises, 22 sets.");
  assert.equal(tq.sessionLine({ routine: { archetype: "[AI_UNAVAILABLE]" } }), "");
});

test("the one ask: omitted when open_actions is empty (live 2026-09-26) — never invented", () => {
  assert.equal(tq.askLine({ open_actions: [] }), "");
  assert.equal(tq.askLine(null), "");
  const dash = { open_actions: [{ coach_id: "physical_coach", coach_name: "Dr. Max Reyes",
    text: "reach 170 g protein per day for seven consecutive days", asked_on: "2026-09-25", due: "2026-10-02", status: "pending" }] };
  // the coach's own words, quoted verbatim
  assert.equal(text(tq.askLine(dash)), "The one ask: “reach 170 g protein per day for seven consecutive days” — Dr. Max Reyes, Sep 25, due Oct 2.");
});

test("one freshness line, in words: weekday · Day N · data through the latest served data date", () => {
  const now = new Date("2026-09-26T04:40:00Z"); // 21:40 PT on Friday Sep 25
  const j = tq.unwrap(JOURNEY_ENVELOPE, "journey");
  assert.equal(tq.freshLine({ journey: j, vitals: VITALS, nutrition: NUTRITION, now }), "Friday · Day 20 · data through Sep 25");
  // the latest of the dates actually printed — an older food log does not drag it back
  const older = { nutrition: { ...NUTRITION.nutrition, latest_date: "2026-09-23" } };
  assert.equal(tq.freshLine({ journey: j, vitals: VITALS, nutrition: older, now }), "Friday · Day 20 · data through Sep 25");
});

test("the engine-vs-log contradiction is printed beside the nutrition pillar, from served fields only", () => {
  const note = tq.nutritionPillarNote(NUTRITION_PILLAR, NUTRITION);
  assert.equal(note, "The engine scored eating 1.5 of 100, with 4 behaviors marked absent; the food log shows 20 days logged through Sep 25.");
  // a healthy score with nothing absent says nothing
  assert.equal(tq.nutritionPillarNote({ raw_score: 62, absent_behaviors: [] }, NUTRITION), "");
  // no served count → no note (never a comparison against nothing)
  assert.equal(tq.nutritionPillarNote(NUTRITION_PILLAR, { nutrition: { days_logged: 0 } }), "");
});

test("third person throughout — the first screen never says 'you'", () => {
  const j = tq.unwrap(JOURNEY_ENVELOPE, "journey");
  const all = text([tq.weekLine(j), tq.nightLine(VITALS), tq.sessionLine(ROUTINE), tq.proteinLine(NUTRITION)].join(" "));
  assert.ok(!/\byou(r|rs|'re)?\b/i.test(all), all);
});

test("no level name on the first screen — the tier is not a field any builder reads", () => {
  const j = tq.unwrap(JOURNEY_ENVELOPE, "journey");
  const all = [tq.weekLine(j), tq.nightLine(VITALS), tq.sessionLine(ROUTINE), tq.proteinLine(NUTRITION)].join(" ");
  assert.ok(!/Foundation|Momentum|XP/.test(all));
});

test("glosses are <dfn class=gloss title=…> and the strip is one line with a dismiss button", () => {
  assert.match(dfn("HRV", "a \"quoted\" def"), /^<dfn class="gloss" tabindex="0" title="a &quot;quoted&quot; def">HRV<\/dfn>$/);
  const strip = orientStripHTML("today, in one screen");
  assert.equal(text(strip).replace("&times;", "").trim(), "New here? This page is today, in one screen. Terms are explained where they appear.");
  assert.match(strip, /<button class="orient-x" type="button"/);
});

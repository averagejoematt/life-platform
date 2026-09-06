// tests/js/character_zeroed_absence_3522.test.mjs — #3522: /data/character (and the
// cockpit's "WHERE YOU STAND") must not present an unmeasured pillar as a measured zero.
//
// The live state this pins out of existence, measured 2026-09-05 (Day 1 of cycle 16,
// before the first character sheet computes) against
//   curl -s https://averagejoematt.com/api/character
// which returned pre_start false and seven pillars whose only keys were
//   [emoji, level, name, raw_score, tier, xp_delta]  — raw_score 0 on all seven:
//
//   rows   →  "Sleep  Lv 1  0/100  0 xp"  ×7
//   radar  →  aria "SLP 0, MOV 0, NUT 0, MET 0, MIN 0, REL 0, CON 0" + a full polygon
//   copy   →  "The bottlenecks right now: Sleep (0/100 …) and Movement (0/100 …)"
//
// directly under the page's own sentence "Behaviors that didn't happen score zero; a
// missing sensor reading doesn't." None of those seven zeros was a reading. ADR-104:
// a zero that was never measured is an absence and must render as one.
//
// Nothing here asserts the engine is wrong. On a REAL dark day an unlogged behavioral
// component scoring 0 at full coverage is the documented design (#2388) — and the
// "Day N with data" cases below prove that path is untouched.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// share.js wires a document click listener at import time; the character module pulls it
// in transitively. Marking it already-wired keeps this a pure-function test, no DOM.
globalThis.window = globalThis.window || { __shareWired: true };

const { chUnmeasured, chWhy, chStatHtml, chBottlenecks, chBottleneckNote, CH_ABBR } = await import("../../site/assets/js/evidence_character.js");
const { radarChart } = await import("../../site/assets/js/charts.js");

const NAMES = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"];

// The payload lambdas/web/site_api_character._zeroed_pre_experiment now emits: the same
// seven zeros, carrying the engine's own absence flags so every renderer's existing held
// branch engages. Served pre-start AND on the morning after a reset (the #931 Day-1
// window the zeroed branch's own comment names).
const ZEROED = NAMES.map((name) => ({
  name,
  emoji: "",
  level: 1,
  raw_score: 0,
  tier: "Foundation",
  xp_delta: 0,
  data_coverage: 0.0,
  coverage_hold: true,
  not_instrumented: true,
  not_instrumented_note: "No sheet yet — this pillar has no measured day behind it.",
  absent_behaviors: [],
  xp_debt: 0.0,
  score_delta: null,
}));

// The payload BEFORE the fix — flags absent, seven bare zeros. Used as the negative
// control: every assertion below must FAIL against it.
const ZEROED_UNFLAGGED = NAMES.map((name) => ({ name, emoji: "", level: 1, raw_score: 0, tier: "Foundation", xp_delta: 0 }));

// A real running sheet: measured scores, full coverage, no holds.
const LIVE = [
  { name: "sleep", level: 4, raw_score: 71, tier: "Foundation", xp_delta: 1.2, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "movement", level: 3, raw_score: 54, tier: "Foundation", xp_delta: 0.4, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "nutrition", level: 2, raw_score: 1, tier: "Foundation", xp_delta: -0.4, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "metabolic", level: 3, raw_score: 62, tier: "Foundation", xp_delta: 0.1, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "mind", level: 2, raw_score: 38, tier: "Foundation", xp_delta: -0.2, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "relationships", level: 3, raw_score: 49, tier: "Foundation", xp_delta: 0.0, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
  { name: "consistency", level: 3, raw_score: 58, tier: "Foundation", xp_delta: 0.3, data_coverage: 1.0, coverage_hold: false, not_instrumented: false },
];

/* ── the predicate ───────────────────────────────────────────────────────── */

test("#3522 chUnmeasured: no measurement behind the score → absence", () => {
  assert.equal(chUnmeasured(ZEROED[0]), true, "the zeroed pre-sheet pillar is an absence");
  // A coverage hold at literally 0% data is the same state arriving by another route.
  assert.equal(chUnmeasured({ name: "mind", raw_score: 0, coverage_hold: true, data_coverage: 0 }), true);
  // A THIN day is still a measured day — the hold freezes levels, it does not erase the score.
  assert.equal(chUnmeasured({ name: "mind", raw_score: 41, coverage_hold: true, data_coverage: 0.3 }), false);
  // #2388's dark nutrition pillar: a real 0 at FULL coverage. Behaviors that didn't
  // happen score zero — that zero is a measurement and must keep rendering as one.
  assert.equal(chUnmeasured({ name: "nutrition", raw_score: 0, coverage_hold: false, data_coverage: 1.0 }), false);
  for (const p of LIVE) assert.equal(chUnmeasured(p), false, `${p.name} is measured`);
  // Negative control: the pre-fix payload is indistinguishable from a measured zero.
  for (const p of ZEROED_UNFLAGGED) assert.equal(chUnmeasured(p), false, "unflagged zeros cannot be detected — which is why the API had to carry the flags");
});

test("#3522 chWhy names the real reason, not a wrong one", () => {
  // The engine's generic "no data source feeds this pillar" would be a FALSE reason on
  // Day 1 (the sources are live; the sheet just hasn't computed). The API's own note wins.
  assert.match(chWhy(ZEROED[0]), /No sheet yet/);
  assert.doesNotMatch(chWhy(ZEROED[0]), /Levels frozen/);
});

/* ── the stat rows: Day 1 with no data ───────────────────────────────────── */

// The row markup, verbatim: `<span class="ch-rraw num">0<small>/100</small></span>`.
// Matching the RENDERED string (not the reader-visible "0/100", which never appears as
// one token in the HTML) is what makes the control below able to fail.
const scoreCells = (html) => [...html.matchAll(/<span class="ch-rraw num">(-?[\d.]+)<small>/g)].map((m) => m[1]);

test("#3522 chStatHtml: an all-unmeasured sheet emits no score, no bar, no xp number", () => {
  const html = chStatHtml(ZEROED, []);
  assert.deepEqual(scoreCells(html), [], "no pillar may print a score out of 100");
  assert.ok(!html.includes("0 xp"), "no zero XP delta for a day that was never scored");
  assert.equal((html.match(/ch-rraw label/g) || []).length, 7, "all seven raw cells render the absence glyph");
  assert.equal((html.match(/ch-rbar-none/g) || []).length, 7, "the bars render as empty tracks, not 0%-wide fills");
  assert.ok(html.includes("No sheet yet"), "the row says why");
  assert.ok(html.includes(">n/a<"), "and carries the held badge the cockpit rows already use");
});

test("#3522 chStatHtml negative control: the pre-fix payload DOES print a score of 0", () => {
  // If the API stops sending the flags — or a future edit drops them on the way to the
  // renderer — this is exactly what comes back. The guard above must be able to see it.
  const html = chStatHtml(ZEROED_UNFLAGGED, []);
  assert.deepEqual(scoreCells(html), ["0", "0", "0", "0", "0", "0", "0"], "control: seven rows really do print 0/100");
  assert.ok(html.includes("0 xp"), "control: and seven '0 xp' deltas");
});

test("#3522 chStatHtml: a measured sheet is untouched", () => {
  const html = chStatHtml(LIVE, []);
  assert.deepEqual(scoreCells(html), ["71", "54", "1", "62", "38", "49", "58"], "every real score still prints");
  // #2388's dark-but-measured nutrition 1 must still read as the measurement it is.
  assert.ok(!html.includes("ch-rraw label"), "nothing is held on a fully measured sheet");
});

/* ── the radar ───────────────────────────────────────────────────────────── */

const axesOf = (pillars) => pillars.map((p) => ({ key: p.name, label: CH_ABBR[p.name] || p.name, value: p.raw_score, not_instrumented: chUnmeasured(p) }));

test("#3522 radarChart: an unmeasured axis draws no vertex, no dot, and says so", () => {
  const svg = radarChart(axesOf(ZEROED));
  assert.ok(!svg.includes("radar-dot"), "no dots for seven unmeasured axes");
  assert.ok(!svg.includes("<polygon class=\"radar-poly\""), "no polygon: fewer than three measured axes");
  const aria = svg.match(/aria-label="([^"]*)"/)[1];
  assert.equal(aria, "Pillar radar: SLP not yet instrumented, MOV not yet instrumented, NUT not yet instrumented, MET not yet instrumented, MIN not yet instrumented, REL not yet instrumented, CON not yet instrumented");
  assert.ok(!/SLP 0/.test(aria), "the aria must never quote a score of 0 for an unmeasured axis");
  assert.ok(svg.includes("7 of 7 not yet measured"), "the caption states the gap");
  // The frame still renders — held is drawn as absent, not dropped.
  assert.equal((svg.match(/radar-lbl/g) || []).length, 7, "every axis keeps its label");
  assert.ok(svg.includes("radar-grid"));
});

test("#3522 radarChart negative control: the old call site DOES plot the zeros", () => {
  // The pre-fix call — evidence_character.js:204 dropped the flag before the builder.
  const svg = radarChart(ZEROED.map((p) => ({ key: p.name, label: CH_ABBR[p.name], value: p.raw_score })));
  assert.equal((svg.match(/radar-dot/g) || []).length, 7, "control: seven vertices at zero");
  assert.ok(svg.includes("<polygon class=\"radar-poly\""), "control: a full polygon");
  assert.match(svg.match(/aria-label="([^"]*)"/)[1], /SLP 0/, "control: the aria really did read 'SLP 0'");
});

test("#3522 radarChart: partially instrumented — measured axes still plot", () => {
  const mixed = LIVE.map((p, i) => (i >= 5 ? { ...p, not_instrumented: true } : p));
  const svg = radarChart(axesOf(mixed));
  assert.equal((svg.match(/radar-dot/g) || []).length, 5, "five measured axes keep their dots");
  assert.ok(svg.includes("<polygon class=\"radar-poly\""), "five measured axes are still a shape");
  assert.ok(svg.includes("2 of 7 not yet measured"));
  const aria = svg.match(/aria-label="([^"]*)"/)[1];
  assert.match(aria, /SLP 71/);
  assert.match(aria, /REL not yet instrumented/);
});

test("#3522 radarChart: a fully measured sheet is byte-identical to before", () => {
  const withFlags = radarChart(axesOf(LIVE));
  const withoutFlags = radarChart(LIVE.map((p) => ({ key: p.name, label: CH_ABBR[p.name], value: p.raw_score })));
  assert.equal(withFlags, withoutFlags, "no behaviour change when nothing is held");
});

/* ── the bottleneck ranking ──────────────────────────────────────────────── */

test("#3522 the bottleneck copy is suppressed when there is nothing to rank", () => {
  const html = chStatHtml(ZEROED, []);
  assert.ok(!html.includes("bottlenecks right now"), "seven unmeasured pillars are not a ranking");
});

test("#3522 chBottlenecks: an all-unmeasured sheet ranks nobody", () => {
  // This is the rule the mechanics panel calls — the same function, not a copy of it.
  assert.deepEqual(chBottlenecks(ZEROED), []);
  assert.match(chBottleneckNote(ZEROED), /no measured days behind them/);
});

test("#3522 chBottlenecks negative control: the OLD rule ranks the tie", () => {
  // The pre-fix expression, verbatim from evidence_character.js:333. It is here to prove
  // the fixture can produce the defect — a guard whose control cannot fail is not a guard.
  const old = ZEROED_UNFLAGGED.slice().sort((a, b) => (a.raw_score || 0) - (b.raw_score || 0)).slice(0, 2);
  assert.equal(old.length, 2, "control: the old sort really did name two pillars");
  assert.equal(old[0].name, "sleep");
  assert.equal(old[1].name, "movement", "control: exactly the live copy's 'Sleep … and Movement …'");
  // And the new rule refuses the same input.
  assert.deepEqual(chBottlenecks(ZEROED_UNFLAGGED), [], "a 7-way tie is unrankable even without the flags");
});

test("#3522 chBottlenecks names two pillars once the scores separate", () => {
  const b = chBottlenecks(LIVE);
  assert.equal(b.length, 2);
  assert.equal(b[0].name, "nutrition", "the true weakest measured pillar leads");
  assert.equal(b[1].name, "mind");
});

test("#3522 a tie among MEASURED pillars is still unrankable", () => {
  const tied = LIVE.map((p) => ({ ...p, raw_score: 42 }));
  assert.deepEqual(chBottlenecks(tied), []);
  assert.match(chBottleneckNote(tied), /sitting at the same score/);
});

test("#3522 unmeasured pillars never crowd out the measured ranking", () => {
  // Day N with a partially instrumented sheet: the two weakest MEASURED pillars win,
  // and the unmeasured ones are not silently ranked bottom just because they read 0.
  const mixed = LIVE.map((p, i) => (i >= 5 ? { ...p, raw_score: 0, not_instrumented: true } : p));
  const b = chBottlenecks(mixed);
  assert.equal(b.length, 2);
  assert.deepEqual(b.map((p) => p.name), ["nutrition", "mind"]);
});

test("#3522 the seven-pillar section still renders its frame while everything is held", () => {
  // Held is drawn as absent, never dropped: a fresh cycle shows the whole sheet, empty.
  const html = chStatHtml(ZEROED, []);
  for (const n of NAMES) assert.ok(html.includes(`--pillar-${n}`), `${n} keeps its row`);
  assert.ok(html.includes("radar-chart"), "and the radar frame");
});

// tests/js/v7_who.test.mjs — #4182: the v7 "Who he is" page's pure helpers, against the
// live shapes saved 2026-09-26 (scratchpad/b2). Every helper takes its date explicitly, so
// nothing here reads the wall clock. What is pinned is what a reader would believe: the
// photo frame's honest due line, the receipts strip's members in order, the weigh-in line
// drawn to the DAY, the four "how it works" sentences word-for-word with Home's, dates in
// words never ISO, every figure carrying its served field, and the owner's 2026-09-26
// ruling — no earlier starts, attempts, cycles or resets anywhere in the rendered copy.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const W = await import("../../site/assets/js/v7_who.js");

// Tags stripped to a fixpoint (one pass can leave a tag behind when tags nest).
const strip = (html) => {
  let s = String(html);
  for (;;) {
    const n = s.replace(/<[^>]*>/g, "");
    if (n === s) return s;
    s = n;
  }
};

const JOURNEY = {
  start_weight_lbs: 327.3,
  current_weight_lbs: 313.8,
  lost_lbs: 13.5,
  weighin_count: 13,
  started_date: "2026-09-06",
  last_weighin_date: "2026-09-26",
  day_n: 21,
  week_n: 3,
  pre_start: false,
};
const RECEIPTS = { as_of: "2026-09-26T04:30:36+00:00", month_to_date_usd: 102.74 };
const SUBS = { count: 1, available: true };
const PROGRESS = [
  { date: "2026-09-06", weight_lbs: 327.3 },
  { date: "2026-09-12", weight_lbs: 319.7 },
  { date: "2026-09-21", weight_lbs: 315.8 },
  { date: "2026-09-22", weight_lbs: 315.0 },
  { date: "2026-09-26", weight_lbs: 313.8 },
];
const FRESHNESS = { summary: { fresh: 11, stale: 1, paused: 1, total: 13 } };
const COACHES = { count: 8 };
const CAD = { chronicle: { paused: false, next_date: "2026-09-30", display: "Next Chronicle installment drafted Wednesday, September 30 — publishes once Matthew reviews and approves the draft." } };

const RULED = /\b(cycle|cycles|reset|resets|attempt|attempts|seventeenth|earlier start|as of)\b/i;

test("the margin is the served day, split for the column", () => {
  assert.deepEqual(W.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(W.marginParts("nope"), null);
});

test("the photographs' captions: dated in words, the day number computed from the served start (#3761)", () => {
  assert.equal(strip(W.photoCaption(JOURNEY, "2026-09-06")), "Sunday, September 6 — day 1, 327.3 lb");
  assert.equal(strip(W.photoCaption(JOURNEY, "2026-09-24", "in the gym")), "Thursday, September 24 — in the gym, day 19");
  // never hard-coded: move the served start and the day moves with it
  assert.equal(strip(W.photoCaption({ ...JOURNEY, started_date: "2026-09-01" }, "2026-09-24", "in the gym")), "Thursday, September 24 — in the gym, day 24");
  assert.match(W.photoCaption(JOURNEY, "2026-09-24", "in the gym"), /data-src="api_journey\.journey\.started_date → photo date">19</);
  assert.match(W.photoCaption(JOURNEY, "2026-09-06"), /data-src="api_journey\.journey\.start_weight_lbs"/);
  assert.doesNotMatch(W.photoCaption(JOURNEY, "2026-09-24", "in the gym"), /lb/);
  // April 2025 predates the start: no computed caption, the static one stands
  assert.equal(W.photoCaption(JOURNEY, "2025-04"), "");
  assert.equal(W.photoCaption({}, "2026-09-24"), "");
});

test("the next photo's due line: day 30 from the served start, in words", () => {
  assert.equal(strip(W.nextPhotoDue(JOURNEY)), "The next photo is due Monday, October 5 — day 30.");
  assert.equal(strip(W.nextPhotoDue({ ...JOURNEY, day_n: 40 })), "The next photo was due Monday, October 5 — day 30.");
  assert.match(W.nextPhotoDue(JOURNEY), /data-src="api_journey\.journey\.started_date \+ 29 days"/);
  assert.equal(W.nextPhotoDue({}), "");
  assert.equal(W.photoDue, undefined);
});
test("the receipts strip: weight now and since the day it began, the day, data through, the cost for one subscriber, the code", () => {
  const items = W.receiptItems(JOURNEY, RECEIPTS, SUBS).map(strip);
  assert.deepEqual(items, [
    "313.8 lb on Saturday, September 26, down 13.5 lb since Sunday, September 6",
    "Day 21",
    "Data through Saturday, September 26",
    "$102.74 this month, for one subscriber",
    "the code",
  ]);
  const html = W.receiptItems(JOURNEY, RECEIPTS, SUBS).join(" · ");
  for (const f of ["current_weight_lbs", "last_weighin_date", "lost_lbs", "started_date", "day_n", "month_to_date_usd", "sub_count.count"]) assert.match(html, new RegExp(`data-src="[^"]*${f}`), f);
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}(?!")/, "an ISO date leaked into the strip's text");
  assert.doesNotMatch(strip(html), RULED);
});

test("the receipts strip degrades honestly: no served weight → no weight item; the eve → no day count", () => {
  assert.deepEqual(W.receiptItems({}, null, null).map(strip), ["the code"]);
  const eve = W.receiptItems({ ...JOURNEY, day_n: 0, pre_start: true }, RECEIPTS, { available: false }).map(strip);
  assert.ok(!eve.some((s) => /^Day /.test(s)));
  assert.equal(eve[eve.length - 2], "$102.74 this month");
  assert.equal(strip(W.receiptItems({ ...JOURNEY, lost_lbs: -2.0 }, null, null)[0]), "313.8 lb on Saturday, September 26, up 2.0 lb since Sunday, September 6");
});

test("the weigh-in line is drawn to the day — a six-day gap is six days wide, not one point", () => {
  const pts = W.stripPoints(PROGRESS);
  assert.equal(pts.length, 5);
  assert.equal(pts[0].x, 6);
  assert.equal(pts[pts.length - 1].x, 314);
  const perDay = 308 / 20;
  assert.ok(Math.abs(pts[1].x - (6 + 6 * perDay)) < 0.11, "Sep 12 sits six days along");
  assert.ok(Math.abs(pts[3].x - pts[2].x - perDay) < 0.11, "Sep 21 → 22 is one day wide");
  assert.equal(pts[0].y, 6, "the heaviest weigh-in sits at the top");
  assert.deepEqual(W.stripPoints([{ date: "2026-09-06", weight_lbs: 327.3 }]), []);
  assert.deepEqual(W.stripPoints(null), []);
});

test("the sentence under the line: the count, the span, from → to, the skipped days — dates in words", () => {
  const s = strip(W.sinceSentence(PROGRESS, JOURNEY));
  assert.equal(s, "Five weigh-ins in 21 days — down 13.5 lb, from 327.3 on Sunday, September 6 to 313.8 on Saturday, September 26, drawn to the day; the scale was skipped on 16 of the 21 days.");
  assert.doesNotMatch(s, RULED);
  assert.equal(W.sinceSentence([], JOURNEY), "");
  const svg = W.stripSvg(PROGRESS);
  assert.match(svg, /<svg viewBox="0 0 320 60" role="img" aria-label="Five weigh-ins from 327.3 on September 6 to 313.8 on September 26, drawn to the day\."/);
  assert.match(svg, /data-src="api_weight_progress\.weight_progress"/);
  assert.equal((svg.match(/<circle /g) || []).length, 5);
  assert.equal(W.stripSvg([]), "");
});

test("how to check: the four sentences are Home's, word for word, from the same served counts", () => {
  const s = W.howSentences(FRESHNESS, COACHES).map(strip);
  assert.equal(s.length, 4);
  assert.equal(s[0], "13 devices and apps are wired in — a scale, a wrist strap, a bed sensor, a food log, a lifting log, his phone — and 11 reported this week; one is stale and one is paused.");
  assert.equal(s[1], "Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  assert.equal(s[2], "Eight AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record.");
  assert.equal(s[3], "An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
  // nothing served → the two data-free sentences still stand, the coaches line has no count
  const bare = W.howSentences(null, null).map(strip);
  assert.equal(bare.length, 3);
  assert.match(bare[1], /^The AI coaches read/);
  assert.doesNotMatch(s.join(" "), RULED);
});

test("the dated return line, in words, from the served cadence", () => {
  assert.equal(W.returnLine(CAD, null), "Next write-up: Wednesday, September 30.");
  assert.equal(W.returnLine(null, null), "");
  assert.equal(W.returnLine(CAD, { display: "Held for review." }), "Held for review.");
});

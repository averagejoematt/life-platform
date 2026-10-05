// tests/js/ck_built_4586.test.mjs — #4586: the live numbers on "How it's built". Driven
// from the committed live captures in tests/fixtures/kit_pages_4586/ (2026-10-04); no
// builder reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const B = await import("../../site/assets/js/ck_built.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const SRC = { stats: load("platform_stats"), receipts: load("receipts"), predictions: load("predictions"), coaches: load("coaches") };

test("the programs block leads with the timer count and never prints the total as a figure", () => {
  const html = B.programsHTML(SRC.stats, SRC.coaches);
  assert.match(html, /<b>83<\/b>/);
  assert.match(html, /programs run on a timer\. Another 23 run when called\. They read 20 sources of data: devices, apps and lab results\. 8 AI coaches write and predict\./);
  assert.match(html, /As of October 4\./);
  assert.doesNotMatch(html, /106|served/, "the total sat beside '106 checked calls' and read as one number");
  assert.match(B.programsHTML(null, null), /not available right now/);
  assert.doesNotMatch(B.programsHTML({ lambdas: 5 }, null), /Another|AI coaches|sources of data/, "an absent or smaller count is left out, never a zero or a negative");
});

test("the coaches' record never appears without its comparison", () => {
  const html = B.recordHTML(SRC.predictions);
  assert.match(html, /<b>45 right, 61 wrong<\/b>/);
  assert.match(html, /data-coach-comparison[^>]*>Across 106 checked calls, so far they do not beat a simple guess\./);
  assert.match(html, /As of October 4\. Code does the grading/);
  const noCmp = B.recordHTML({ overall: SRC.predictions.overall });
  assert.match(noCmp, /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(B.recordHTML({ overall: { confirmed: 0, refuted: 0 } }), /not available right now/, "no checked calls is not printed as 0 and 0");
});

test("the cost paragraphs reconcile: the daily rate has its window, both forecasts are stated, and the tier is explained", () => {
  const html = B.costHTML(SRC.receipts);
  assert.match(html, /The ceiling is \$215 a month for the whole cloud bill, AI included\. It rises to \$252 when reader traffic is high\. As of October 4, \$60\.84 is spent this month\. Nothing is paused\./);
  assert.match(html, /AI cost \$14\.35 a day over the days of this month so far\. That is a recent rate, not a monthly average\. One day, October 2, was \$42\.70 of the total\. Everything that is not AI costs \$2\.24 a day and never pauses\./);
  assert.match(html, /counting the scheduled programs only, is \$222\.73, above the ceiling\. Counting everything, including AI used to test and build the system, it is \$514\.39, above the ceiling\./);
  assert.match(html, /Nothing is paused yet because in the first 5 days of a month only money actually spent can raise the tier, and \$60\.84 is under the first step of \$157\.67\. After day 5 a forecast this high starts tier 1\. A forecast lifts the tier one step at most, so tier 2 waits for \$157\.67 actually spent and tier 3 for \$186\.33\./);
  assert.match(html, /On these figures the bill passes the ceiling unless the pauses start or the pace drops\. This month has not yet shown which\./);
});

test("the cost paragraphs do not explain away what the figures do not show", () => {
  const later = B.costHTML({ ...SRC.receipts, computed_at: "2026-10-20T16:00:00+00:00" });
  assert.match(later, /over the last 7 days/);
  assert.doesNotMatch(later, /in the first 5 days/, "the early-month reason is given only inside the early-month window");
  const calm = B.costHTML({ ...SRC.receipts, projected_month_end_usd: 150, projected_all_classes_usd: 160 });
  assert.match(calm, /\$150\.00, under the ceiling/);
  assert.doesNotMatch(calm, /passes the ceiling|Nothing is paused yet/);
  assert.match(B.costHTML({ ...SRC.receipts, tier: 2 }), /The system is at tier 2\./);
  assert.match(B.costHTML({ ...SRC.receipts, stale: true }), /This figure is out of date\./);
  assert.match(B.costHTML(null), /not available right now/);
  assert.doesNotMatch(B.costHTML(null), /\$/, "no figure is printed when the route does not answer");
});

test("nothing leaks: no ISO date, no non-value, no machine register", () => {
  const html = B.numbersHTML(SRC) + B.costHTML(SRC.receipts);
  assert.doesNotMatch(html, /\b20\d\d-\d\d-\d\d\b|undefined|NaN|\[object Object\]/);
  assert.doesNotMatch(html, /\bserved\b/, "reader copy says 'as of', never 'served'");
});

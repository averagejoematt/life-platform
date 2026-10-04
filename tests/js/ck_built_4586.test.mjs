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

test("programs, the timer count, sources and coaches are one dated block", () => {
  const html = B.programsHTML(SRC.stats, SRC.coaches);
  assert.match(html, /<b>106<\/b>/);
  assert.match(html, /82 of them run on a timer\. They read 20 data sources: devices, apps and lab results\. 8 AI coaches write and predict\./);
  assert.match(html, /Counts served October 4\. Timer count as of October 4\./);
  assert.match(B.programsHTML(null, null), /not served right now/);
  assert.doesNotMatch(B.programsHTML({ lambdas: 5 }, null), /AI coaches|data sources/, "an unserved count is left out, never a zero");
});

test("spend is the served month-to-date against the served ceiling, with its day", () => {
  const html = B.spendHTML(SRC.receipts);
  assert.match(html, /<b>\$60\.84<\/b>/);
  assert.match(html, /against a ceiling of \$215\. It is the whole cloud bill, AI included\. Over recent days AI has cost \$14\.35 a day and everything else \$2\.24\./);
  assert.match(html, /As of October 4\./);
  assert.match(B.spendHTML({ ...SRC.receipts, stale: true }), /This figure is out of date\./);
  assert.match(B.spendHTML({ ...SRC.receipts, month_to_date_usd: null }), /This month’s spend is not served right now\./);
  assert.match(B.spendHTML(null), /not served right now/);
});

test("the coaches' record never appears without the served comparison", () => {
  const html = B.recordHTML(SRC.predictions);
  assert.match(html, /<b>45 of 106<\/b>/);
  assert.match(html, /data-coach-comparison[^>]*>Across 106 checked calls, so far they do not beat a simple guess\./);
  assert.match(html, /As of October 4\. Code grades each call/);
  const noCmp = B.recordHTML({ overall: SRC.predictions.overall });
  assert.match(noCmp, /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(B.recordHTML({ overall: { confirmed: 0, decided: 0 } }), /not served right now/, "no checked calls is not printed as 0 of 0");
});

test("the cost paragraph states the ceiling, today's tier and the forecast as served", () => {
  const html = B.costHTML(SRC.receipts);
  assert.match(html, /The ceiling is \$215 a month for the whole cloud bill\. It rises to \$252 when reader traffic is high\./);
  assert.match(html, /On October 4 the system is at tier 0\. All AI features active\. Nothing is paused\./);
  assert.match(html, /The forecast for month end is \$222\.73, above the ceiling\./);
  assert.match(B.costHTML({ ...SRC.receipts, projected_month_end_usd: 150 }), /\$150\.00, under the ceiling\./);
  assert.match(B.costHTML(null), /not served right now/);
  assert.doesNotMatch(B.costHTML(null), /\$/, "no figure is printed when the route does not answer");
});

test("nothing leaks: no ISO date, no non-value, and served text is escaped", () => {
  const html = B.numbersHTML(SRC) + B.costHTML(SRC.receipts);
  assert.doesNotMatch(html, /\b20\d\d-\d\d-\d\d\b|undefined|NaN|\[object Object\]/);
  assert.match(B.costHTML({ ...SRC.receipts, tier_semantics: "<b>x</b>" }), /&lt;b&gt;x&lt;\/b&gt;/);
});

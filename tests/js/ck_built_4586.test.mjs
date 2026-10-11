// tests/js/ck_built_4586.test.mjs — #4586: the live numbers on "How it's built". Driven
// from the committed live captures in tests/fixtures/kit_pages_4586/ (one capture, its time in
// _capture.json, #4671: 2026-10-10 02:38 UTC); no builder reads the wall clock. The capture is
// late in the month, past the high days' window; EARLY is the same receipt read on October 4
// with the forecast it served then, so the early-month sentences stay pinned.
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
// The receipt as it read early in the month: every high day inside the rate's window, and the
// forecast above the ceiling (the October 4 figures), so every cost sentence is printed.
const EARLY = { ...SRC.receipts, computed_at: "2026-10-04T12:00:00+00:00", projected_month_end_usd: 221.83, projected_all_classes_usd: 496.08 };

test("the programs block leads with the timer count and never prints the total as a figure", () => {
  const html = B.programsHTML(SRC.stats, SRC.coaches);
  assert.match(html, /<b>83<\/b>/);
  assert.match(html, /programs run on a timer\. Another 24 run when called\. They read 20 sources of data: devices, apps and lab results\. 8 AI coaches write and predict\./);
  assert.match(html, /As of October 4\./);
  assert.doesNotMatch(html, /107|served/, "the total (83 + 24) sat beside the checked calls and read as one number");
  assert.match(B.programsHTML(null, null), /not available right now/);
  assert.doesNotMatch(B.programsHTML({ lambdas: 5 }, null), /Another|AI coaches|sources of data/, "an absent or smaller count is left out, never a zero or a negative");
});

test("the coaches' record never appears without its comparison", () => {
  const html = B.recordHTML(SRC.predictions);
  assert.match(html, /<b>56 right, 75 wrong<\/b>/);
  assert.match(html, /data-coach-comparison[^>]*>Across 131 checked calls, so far they do not beat a simple guess\./);
  assert.match(html, /As of October 9\. Code does the grading/);
  const noCmp = B.recordHTML({ overall: SRC.predictions.overall });
  assert.match(noCmp, /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(B.recordHTML({ overall: { confirmed: 0, refuted: 0 } }), /not available right now/, "no checked calls is not printed as 0 and 0");
});

const at = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
// The receipt with one field gone, or renamed (the value moved to `<name>_v2`).
function without(path, rename = false, base = EARLY) {
  const copy = JSON.parse(JSON.stringify(base));
  const keys = path.split(".");
  const last = keys.pop();
  const holder = keys.reduce((o, k) => o[k], copy);
  if (rename) holder[`${last}_v2`] = holder[last];
  delete holder[last];
  return copy;
}
// One phrase per sentence, and the phrase is how the test knows the sentence is there.
const SENTENCE = {
  spent: /is spent this month/,
  ordinary: /An ordinary day costs/,
  high: /days this month each cost more than/,
  share: /ran on a schedule/,
  forecast: /The forecast that sets the tier/,
  wide: /If building and testing also carried on/,
};

test("the cost paragraphs add up: an ordinary day, the high days with dates, and what each forecast assumes (#4650)", () => {
  const html = B.costHTML(SRC.receipts);
  assert.match(html, /The ceiling is \$215 a month for the whole cloud bill, AI included\. It rises to \$252 when reader traffic is high\. As of October 9, \$75\.99 is spent this month\. Nothing is paused\./);
  assert.match(html, /An ordinary day costs \$4\.38, AI included: the middle day of the 30 days to October 9\. 31 days like it come to \$135\.78, under the ceiling\./);
  assert.match(html, /3 days this month each cost more than twice that: October 1, 2 and 3, \$59\.70 together, \$46\.56 more than 3 ordinary days\.<\/p>/);
  assert.doesNotMatch(html, /ran on a schedule/, "the last 7 days no longer hold the high days, so their AI split says nothing about them");
  assert.match(html, /The forecast that sets the tier is what is spent plus the scheduled programs at their pace over the last 7 days: \$126\.81 by October 31, under the ceiling\. If building and testing also carried on at that pace every day, it would be \$139\.97\./);
  assert.doesNotMatch(html, /Nothing is paused yet|starts tier 1/, "a forecast under tier 1's line needs no reason for the tier");
  // Early in the month (the October 4 forecast): the AI split and why nothing is paused yet.
  const early = B.costHTML(EARLY);
  assert.match(early, /\$46\.56 more than 3 ordinary days\. Of the AI spend this month so far, 66% ran on a schedule\. The rest was building and testing the system\./);
  assert.match(early, /The forecast that sets the tier is what is spent plus the scheduled programs at their pace this month so far: \$221\.83 by October 31, above the ceiling because of the high days already spent\. If building and testing also carried on at that pace every day, it would be \$496\.08\./);
  assert.match(early, /Nothing is paused yet because in the first 5 days of a month only money actually spent can raise the tier, and \$75\.99 is under tier 1’s line of \$157\.67\. After day 5 a forecast this high starts tier 1\. A forecast can lift the tier only one step above what the money actually spent supports: tier 2 needs \$157\.67 actually spent and tier 3 needs \$186\.33\./);
  assert.doesNotMatch(html + early, /\$13\.75|a day over|Counting everything/, "the recent AI rate read as a monthly bill, and the all-in figure was printed without what it assumes");
  // A reader can check the sums: the day times the days is the month, and it is the served figure.
  const t = SRC.receipts.typical_day;
  assert.equal(Math.round(t.usd * t.month_days * 100) / 100, t.month_usd);
  const h = SRC.receipts.high_days;
  assert.equal(Math.round(h.days.reduce((sum, d) => sum + d.usd, 0) * 100) / 100, h.total_usd);
  assert.equal(Math.round((h.total_usd - t.usd * h.days.length) * 100) / 100, h.above_typical_usd);
  assert.ok(h.total_usd <= SRC.receipts.month_to_date_usd, "the high days are part of the month's spend, never more than it");
});

test("each cost sentence is pinned to its served fields: a missing or renamed field removes the sentence (#4650)", () => {
  const full = B.costHTML(EARLY); // the early-month receipt prints every sentence
  const offenders = [];
  for (const [sentence, fields] of Object.entries(B.COST_FIELDS)) {
    if (!SENTENCE[sentence]) offenders.push(`${sentence}: no phrase in this test names the sentence`);
    else if (!SENTENCE[sentence].test(full)) offenders.push(`${sentence}: not printed from the full capture`);
    for (const field of fields) {
      if (at(EARLY, field) == null) offenders.push(`${field}: not in the capture, so the page cannot be printing it from the route`);
      for (const rename of [false, true]) {
        const html = B.costHTML(without(field, rename));
        if (SENTENCE[sentence] && SENTENCE[sentence].test(html)) offenders.push(`${field} ${rename ? "renamed" : "missing"}: the '${sentence}' sentence is still printed`);
        if (/undefined|NaN|null/.test(html)) offenders.push(`${field} ${rename ? "renamed" : "missing"}: a non-value is printed`);
      }
    }
  }
  assert.deepEqual(offenders, []);
  // The sentences that lean on another go with it: no "twice that" without the ordinary day.
  const noDay = B.costHTML(without("typical_day"));
  assert.doesNotMatch(noDay, /ordinary|twice that|because of the high days/);
  assert.match(noDay, /\$221\.83 by October 31, above the ceiling\./, "the forecast still stands, without the reason it cannot show");
});

test("the cost paragraphs do not explain away what the figures do not show", () => {
  const later = B.costHTML({ ...EARLY, computed_at: "2026-10-20T16:00:00+00:00" });
  assert.match(later, /at their pace over the last 7 days/);
  assert.doesNotMatch(later, /in the first 5 days/, "the early-month reason is given only inside the early-month window");
  assert.doesNotMatch(later, /ran on a schedule/, "the last 7 days no longer hold the high days, so their AI split says nothing about them");
  const calm = B.costHTML({ ...EARLY, projected_month_end_usd: 150, projected_all_classes_usd: 160 });
  assert.match(calm, /\$150\.00 by October 31, under the ceiling\./);
  assert.doesNotMatch(calm, /because of the high days|Nothing is paused yet/);
  const stillOver = B.costHTML({ ...EARLY, projected_month_end_usd: 300 });
  assert.match(stillOver, /\$300\.00 by October 31, above the ceiling\./, "the high days are not blamed for a forecast that is over the ceiling without them");
  const none = B.costHTML({ ...EARLY, high_days: { ...EARLY.high_days, days: [], total_usd: 0, above_typical_usd: 0 } });
  assert.match(none, /An ordinary day costs/);
  assert.doesNotMatch(none, /cost more than|ran on a schedule|because of the high days/, "no high day this month: nothing is said about one");
  const one = B.costHTML({ ...SRC.receipts, high_days: { multiple: 3, days: [{ date: "2026-10-02", usd: 24.68 }], total_usd: 24.68, above_typical_usd: 20.11 } });
  assert.match(one, /One day this month cost more than 3 times that: October 2, at \$24\.68, \$20\.11 more than an ordinary day\./);
  const same = B.costHTML({ ...SRC.receipts, projected_all_classes_usd: SRC.receipts.projected_month_end_usd });
  assert.doesNotMatch(same, /If building and testing/, "no wider forecast is printed when the route gives the same figure twice");
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

test("once the forecast counts the checks on each deploy, both sentences that describe it say so (#4652)", () => {
  const before = B.costHTML(EARLY);
  assert.match(before, /what is spent plus the scheduled programs at their pace/);
  assert.match(before, /% ran on a schedule\. The rest/);
  const counted = B.costHTML({ ...EARLY, projected_classes: [...EARLY.projected_classes, "ci"] });
  assert.match(counted, /what is spent plus the scheduled programs and the checks on each deploy at their pace/);
  assert.match(counted, /% ran on a schedule or as a check on a deploy\. The rest/);
  const absent = B.costHTML({ ...EARLY, projected_classes: undefined });
  assert.match(absent, /what is spent plus the scheduled programs at their pace/, "a missing list changes no sentence");
});

test("three plain figures stand in the open; the high days, the forecast and the tier sums sit behind one disclosure (red team, round 7)", () => {
  const html = B.costHTML(SRC.receipts);
  const [open, folded] = html.split("<details>");
  assert.ok(folded, "one disclosure");
  assert.equal((html.match(/<details>/g) || []).length, 1);
  assert.match(open, /\$75\.99 is spent this month/);
  assert.match(open, /An ordinary day costs \$4\.38/);
  assert.ok(open.includes(B.BUILD_CAP), "the limit on building and testing is said in the open");
  assert.doesNotMatch(open, /forecast|tier 2|\$139\.97/, "no forecast arithmetic above the fold");
  assert.doesNotMatch(B.costHTML(EARLY).split("<details>")[0], /forecast|tier 2|\$496/, "nor early in the month");
  assert.match(folded, /The forecast that sets the tier/);
  assert.match(folded, /days this month each cost more than/);
});

// The Coaching Room's instrument (src/lib/calibration.js, CR1): carried numbers only, the headline rule, the
// calibration words, and the stated-confidence chart's contract (data-points in x order, text ≥ 11 px on a phone).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  assessmentWords,
  blendRow,
  calibrationChart,
  coachVerified,
  excludedAccounting,
  methodChangeText,
  qualifyText,
  sameCalls,
  verifiedRecord,
  calibrationDots,
  concentrationText,
  intervalText,
  v2Answers,
  v2MethodText,
  v2Short,
  v2Stratum,
  recordHeadline,
  strataRows,
  versusGuess,
  voidedRows,
  archiveRecord,
  countedCalls,
  signTestText,
  verifiedLead,
  whyChanged,
} from "../src/lib/calibration.js";

// SERVED = the committed fixture as the producer serves it today (with the verified block and verification_summary,
// owner 2026-11-09); FIXTURE = the same file with both removed — the "nothing served yet" case the earlier tests pin.
const SERVED = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "content", "fixtures", "calibration.json"), "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));
const FIXTURE = clone(SERVED);
delete FIXTURE.calibration.verification_summary;
delete FIXTURE.calibration.platform.strata.coaches.verified;

test("headline, no verified split served: as first graded, labelled unverified, interval said to be unpublished", () => {
  const h = recordHeadline(FIXTURE);
  assert.equal(h.mode, "as_graded");
  assert.equal(h.k, 88);
  assert.equal(h.n, 214);
  assert.match(h.h1, /88 of 214 checked calls, as first graded\./);
  assert.match(h.dek, /41\.1%/); // carried from record.accuracy_pct, never 88/214 recomputed
  assert.match(h.dek, /interval for the coaches' record is not published yet/);
  assert.match(h.caveat, /not yet publish which of them were re-verified/);
  assert.match(h.sentence, /^88 of 214 checked calls right as first graded — 41\.1%, no interval published yet — and a guess that every call/);
  assert.equal(h.archive, null);
});

test("headline never computes: a carried percentage that disagrees with K/N is printed as carried", () => {
  const f = clone(FIXTURE);
  f.record.accuracy_pct = 12.3; // deliberately not 88/214
  assert.match(recordHeadline(f).dek, /12\.3%/);
});

test("headline, verified split served: only re-verified grades in the headline, the as-graded record moves to the archive", () => {
  const f = clone(FIXTURE);
  f.calibration.platform.strata.coaches.verified = { n: 40, confirmed: 17, accuracy_pct: 42.5, accuracy_ci95: [28.5, 57.8] };
  const h = recordHeadline(f);
  assert.equal(h.mode, "verified");
  assert.match(h.h1, /17 of 40 re-verified calls\./);
  assert.match(h.dek, /95% interval 28\.5–57\.8%/);
  assert.doesNotMatch(h.h1 + h.dek, /88|214/, "an unverified figure must not reach the headline");
  assert.deepEqual([h.archive.k, h.archive.n], [88, 214]);
});

test("the coaches' stratum interval, once served, is used as served", () => {
  const f = clone(FIXTURE);
  f.calibration.platform.strata.coaches.accuracy_ci95 = [34.6, 48.0];
  assert.match(recordHeadline(f).dek, /the 95% interval 34\.6–48\.0%/);
});

test("absent data file → no headline (the page says so)", () => {
  assert.equal(recordHeadline({ state: "absent" }), null);
  assert.equal(recordHeadline(null), null);
});

test("calibration-v2 (owner 2026-11-09): three answers in the served words, in order; nothing invented", () => {
  const nutrition = FIXTURE.calibration.coaches.find((c) => c.coach_id === "nutrition");
  const xs = v2Answers(nutrition.assessment_v2);
  assert.deepEqual(xs.map((x) => x.key), ["estimability", "confidence_direction", "skill"]);
  assert.match(xs[1].words, /^Over-confident at its 50% calls \(\d+ of \d+ came true, 95% CI \d+%–\d+%; Holm-adjusted p [\d.]+\)/);
  assert.match(xs[1].words, /not about calibration across confidence levels/);
  assert.equal(xs[1].short, "over-confident at its 50% calls");
  assert.match(v2Short(nutrition.assessment_v2), /^not estimable across confidence levels · over-confident at its 50% calls · /);
  assert.deepEqual(v2Answers(null), []);
  assert.deepEqual(v2Answers({ confidence_direction: { label: "over_confident" } }), [], "a bare label is never turned into words");
  assert.equal(v2Short(undefined), null);
  assert.equal(v2Stratum(FIXTURE.calibration, "coaches").method_version, "calibration-v2");
  assert.equal(v2Stratum(FIXTURE.calibration, "nope"), null);
  assert.equal(v2MethodText(FIXTURE.calibration), "calibration-v2, adopted 9 November 2026");
  assert.equal(v2MethodText({}), null);
});

test("no v1 calibration label reaches the words: the served v1 fields are never read (sentinel + mutation control)", () => {
  const SENT = "V1SENTINEL_LABEL";
  const cal = clone(FIXTURE.calibration);
  for (const c of cal.coaches) Object.assign(c, { calibration: SENT, label: SENT });
  for (const s of Object.values(cal.platform.strata)) Object.assign(s, { calibration: SENT, label: SENT });
  Object.assign(cal.platform, { calibration: SENT, label: SENT });
  const file = { ...clone(FIXTURE), calibration: cal };
  const out = JSON.stringify([
    strataRows(file),
    blendRow(file),
    cal.coaches.map((c) => [v2Answers(c.assessment_v2), v2Short(c.assessment_v2)]),
    recordHeadline(file),
  ]);
  assert.ok(!out.includes(SENT), "a v1 label reached a reader-facing value");
  // mutation control: the detector does see the sentinel where it IS present
  assert.ok(JSON.stringify(cal).includes(SENT));
});

test("stated confidence: the largest served band beside the coach's n, both carried", () => {
  assert.equal(concentrationText(FIXTURE.calibration.coaches[0]), "46 of 48 stated at 50%");
  assert.equal(concentrationText({ n: 3, reliability_bins: [] }), "no stated confidence served");
});

test("strata keep the coaches apart from the blend; unserved figures stay unserved", () => {
  const rows = strataRows(FIXTURE);
  assert.deepEqual(rows.map((r) => r.key), ["coaches", "hypotheses", "interval_forecasts", "weekly_prescriptions"]);
  const coaches = rows[0];
  assert.deepEqual([coaches.n, coaches.right, coaches.pct, coaches.ci], [214, 88, "41.1%", null]);
  assert.equal(rows[3].pct, null); // weekly prescriptions: no share served
  const blend = blendRow(FIXTURE);
  assert.deepEqual([blend.n, blend.right, blend.pct], [592, 422, "71.9%"]);
});

test("comparison with the nothing-changes guess and the voided list are carried", () => {
  assert.equal(versusGuess(FIXTURE.calibration.comparison.records, "direction").text, "36 v 33 of 118");
  assert.equal(versusGuess({}, "direction"), null);
  const v = voidedRows(FIXTURE.calibration.voided);
  assert.deepEqual(v.map((r) => r.words), ["6 September 2026", "3 August 2026", "13 July 2026"]);
  assert.equal(intervalText([1, 2, 3]), null);
});

test("the chart: one dot per coach per served band, points in x order, a prewritten label each, no curve", () => {
  const coaches = FIXTURE.calibration.coaches;
  const dots = calibrationDots(coaches);
  const served = coaches.reduce((s, c) => s + c.reliability_bins.length, 0);
  assert.equal(dots.length, served);
  const svg = calibrationChart(coaches);
  assert.doesNotMatch(svg, /<path/, "dots, never a curve");
  const pts = JSON.parse(svg.match(/data-points="([^"]*)"/)[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&"));
  assert.equal(pts.length, served);
  for (let i = 1; i < pts.length; i++) assert.ok(pts[i].x >= pts[i - 1].x, "points ordered on x for the keyboard");
  assert.match(pts[0].label, /stated \d+% · \d+ calls? · \d+% came true/);
});

test("on a phone the viewBox is the container's width, so SVG text stays at or above 11 px", () => {
  const svg = calibrationChart(FIXTURE.calibration.coaches, { mobile: true, width: 342 });
  assert.match(svg, /viewBox="0 0 342 /);
  const sizes = [...svg.matchAll(/font-size="([\d.]+)"/g)].map((m) => Number(m[1]));
  assert.ok(sizes.length && sizes.every((s) => s >= 11), `font sizes ${sizes}`);
});

// ── launch-readiness (2026-11-09): the verified-only headline, same-call baseline, which calls qualify, exclusions ──

test("verified record: read from strata.coaches.verified, else verification_summary.verified; malformed → not served", () => {
  const f = clone(FIXTURE);
  assert.equal(verifiedRecord(f.calibration), null, "the control: nothing served today");
  f.calibration.verification_summary = { verified: { n: 30, right: 12, accuracy_pct: 40.0 } };
  assert.deepEqual([verifiedRecord(f.calibration).n, verifiedRecord(f.calibration).confirmed], [30, 12]);
  f.calibration.platform.strata.coaches.verified = { n: 40, confirmed: 17 };
  assert.equal(verifiedRecord(f.calibration).n, 40, "the stratum's own split wins");
  assert.equal(verifiedRecord({ verification_summary: { verified: { n: "40", confirmed: 17 } } }), null);
});

test("the baseline beside the verified record is over the SAME calls or not shown (control: a mismatched n is refused)", () => {
  assert.deepEqual(sameCalls({ n: 40, text: "x" }, 40), { n: 40, text: "x" });
  assert.deepEqual(sameCalls({ text: "x" }, 40), { text: "x" }, "served on the verified object, no n of its own");
  assert.equal(sameCalls({ n: 214, text: "x" }, 40), null);
  const f = clone(FIXTURE);
  f.calibration.platform.strata.coaches.verified = { n: 40, confirmed: 17, accuracy_pct: 42.5, baseline: { n: 214, text: "A guess on other calls." } };
  const h = recordHeadline(f);
  assert.doesNotMatch(h.dek, /other calls/, "a baseline over other calls never reaches the headline");
  assert.equal(h.baselineSameCalls, false);
  assert.match(h.dek, /No comparison with a simple guess is published for these same calls yet/);
  f.calibration.platform.strata.coaches.verified.baseline = { n: 40, text: "A guess on these calls does about as well." };
  assert.match(recordHeadline(f).dek, /A guess on these calls does about as well\./);
  assert.doesNotMatch(recordHeadline(f).dek, /every call has a/, "the as-graded baseline never stands in");
});

test("the denominator change reads as which calls qualify, never as improvement", () => {
  const f = clone(FIXTURE);
  assert.equal(qualifyText(recordHeadline(f)), null, "the control: no verified split, no sentence");
  f.calibration.platform.strata.coaches.verified = { n: 40, confirmed: 17 };
  const q = qualifyText(recordHeadline(f));
  assert.match(q, /the 40 calls that qualify .* 214 calls were first graded/);
  assert.match(q, /which calls qualify to be evaluated, not a change in how well the coaches called them/);
  for (const s of [q, recordHeadline(f).caveat]) assert.doesNotMatch(s, /improv|better score|more accurate|gain/i);
  assert.match(methodChangeText({ effective: "2026-11-05", history: [{}, {}] }), /^Since 5 November 2026, only calls about publishable data qualify/);
  assert.equal(methodChangeText({ effective: "2026-11-05", history: [{}] }), null, "one method, no change to explain");
});

test("the excluded-calls accounting: nothing until the producer serves it; carried, never summed; private families never shown", () => {
  assert.equal(excludedAccounting(FIXTURE.calibration), null, "the control: not served → the component shows nothing");
  const dict = excludedAccounting({ verification_summary: { excluded_by_category: { unassessed: 120, logging_gap: 4, low_power: 2 } } });
  assert.deepEqual(dict.rows.map((r) => [r.key, r.n]), [["unassessed", 120], ["logging_gap", 4], ["low_power", 2]]);
  assert.equal(dict.total, null, "no total is computed when none is served");
  const list = excludedAccounting({ verification_summary: { excluded: [{ category: "proxy_metric", count: 3 }, { key: "x_y", n: 1, label: "Served words" }], excluded_total: 4 } });
  assert.deepEqual(list.rows.map((r) => r.words), ["graded on a stand-in measure, not the one it named", "Served words"]);
  assert.equal(list.total, 4);
  const priv = excludedAccounting({ verification_summary: { excluded_by_category: { journal_calls: 9, mood: 3, state_of_mind: 1, low_power: 2 } } });
  assert.deepEqual(priv.rows.map((r) => r.key), ["low_power"], "a private family is dropped, fail closed");
  assert.equal(excludedAccounting({ verification_summary: { excluded_by_category: { mood: 3 } } }), null);
  assert.equal(excludedAccounting({ verification_summary: { excluded_by_category: { low_power: "2" } } }), null, "a non-integer count is not served");
});

test("per-coach verification and assessment_v2: shown when served, absent otherwise", () => {
  assert.equal(coachVerified(FIXTURE.calibration.coaches[0]), null);
  assert.deepEqual(coachVerified({ verification: { n: 15, confirmed: 6, accuracy_pct: 40, accuracy_ci95: [19.8, 64.3] } }), { k: 6, n: 15, pct: "40.0%", ci: "95% interval 19.8–64.3%" });
  assert.equal(assessmentWords(null), null);
  assert.equal(assessmentWords({ sentence: "Not the v2 shape." }), null);
  assert.equal(assessmentWords({ label: "insufficient_data" }), null, "a bare label is never rendered");
  assert.equal(assessmentWords({ estimability: { wording: "A." }, skill: { wording: "C." } }), "A. C.");
});

// ── the CR1 launch (owner ruling 2026-11-09): the producer's verified lead, why it changed, uncertainty, exclusions ──

test("the lead is the producer's own sentence, carried verbatim; every figure beside it is carried (control: no sentence → no lead)", () => {
  const lead = verifiedLead(SERVED.calibration);
  assert.equal(lead.sentence, SERVED.calibration.platform.strata.coaches.verified.sentence);
  assert.deepEqual([lead.k, lead.n, lead.pct, lead.ci], [34, 71, "47.9%", "95% interval 37.2–58.6%"]);
  assert.deepEqual([lead.baseline.right, lead.baseline.n, lead.baseline.pct, lead.baseline.ci], [37, 71, "52.1%", "95% interval 40.7–63.4%"]);
  const h = recordHeadline(SERVED);
  assert.equal(h.h1, lead.sentence);
  assert.equal(h.sentence, lead.sentence, "the /system/ entry repeats the producer's sentence, nothing composed");
  // controls: no sentence served → no lead (the page keeps its labelled fallback); a baseline over other calls is refused
  const f = clone(SERVED);
  delete f.calibration.platform.strata.coaches.verified.sentence;
  delete f.calibration.verification_summary.verified.sentence;
  assert.equal(verifiedLead(f.calibration), null);
  assert.equal(verifiedLead(FIXTURE.calibration), null);
  const g = clone(SERVED);
  g.calibration.platform.strata.coaches.verified.baseline.n = 214;
  assert.equal(verifiedLead(g.calibration).baseline, null, "a baseline on a different set of calls never stands beside the lead");
});

test("never hard-coded: a different served verified block changes every figure on the lead (mutation control)", () => {
  const f = clone(SERVED);
  const v = f.calibration.platform.strata.coaches.verified;
  Object.assign(v, { n: 75, confirmed: 38, accuracy_pct: 50.7, sentence: "Of 75 forecasts … 38 right (51%)." });
  const lead = verifiedLead(f.calibration);
  assert.deepEqual([lead.k, lead.n, lead.pct, lead.sentence], [38, 75, "50.7%", "Of 75 forecasts … 38 right (51%)."]);
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "room", "calibration.astro"), "utf8");
  assert.doesNotMatch(src, /\b(38|75|51%|53%)\b/, "the page never writes the launch figures itself");
});

test("the sign test in plain words, carried (control: no sign test served → no sentence)", () => {
  const t = signTestText(verifiedLead(SERVED.calibration));
  assert.equal(t, "The coaches alone were right on 14 of these calls and the simple prediction alone on 17. On those calls an exact two-sided sign test gives p = 0.72: no detectable difference.");
  const f = clone(SERVED);
  delete f.calibration.platform.strata.coaches.verified.sign_test;
  assert.equal(signTestText(verifiedLead(f.calibration)), null);
});

test("why the record changed: the producer's sentence beside the archived original grading; never framed as improvement", () => {
  const w = whyChanged(SERVED.calibration);
  assert.match(w.text, /not because the coaches improved/);
  assert.deepEqual([w.archive.k, w.archive.n, w.archive.pct], [88, 214, "41.1%"]);
  assert.deepEqual([archiveRecord(SERVED.calibration).ci], ["95% interval 34.7–47.8%"]);
  assert.equal(whyChanged(FIXTURE.calibration), null, "the control: not served → nothing");
  assert.deepEqual([recordHeadline(SERVED).archive.k, recordHeadline(SERVED).archive.n], [88, 214]);
});

test("the served accounting reconciles: rows add to the total and eligible = left out + counted (control: a broken sum is not shown)", () => {
  const ex = excludedAccounting(SERVED.calibration);
  assert.equal(ex.reconciles, true);
  assert.equal(ex.rows.reduce((a, r) => a + r.n, 0), ex.total);
  assert.equal(ex.eligible, ex.total + ex.counted);
  assert.equal(ex.rows.length, 11);
  assert.ok(ex.rows.every((r) => r.words === SERVED.calibration.verification_summary.excluded_by_category.find((x) => x.key === r.key).label), "the producer's label, never composed");
  const broken = clone(SERVED);
  broken.calibration.verification_summary.excluded_by_category[0].n += 1;
  assert.equal(excludedAccounting(broken.calibration), null, "a sum that does not reconcile is withheld, not shown");
  const priv = clone(SERVED);
  priv.calibration.verification_summary.excluded_by_category.push({ key: "journal_calls", label: "x", n: 0 });
  assert.equal(excludedAccounting(priv.calibration).rows.some((r) => r.key === "journal_calls"), false, "a private-named category never renders");
});

test("the counted calls: a Set from the producer's list; absent or malformed → null (nothing may stand in)", () => {
  const s = countedCalls(SERVED.calibration);
  assert.ok(s.has("nutrition-20261015-protein01") && !s.has("sleep-20261005-deepsleep01"));
  assert.equal(countedCalls(FIXTURE.calibration), null);
  assert.equal(countedCalls({ verification_summary: { counted_calls: [1, 2] } }), null);
});

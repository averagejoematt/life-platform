// The Coaching Room's instrument (src/lib/calibration.js, CR1): carried numbers only, the headline rule, the
// calibration words, and the stated-confidence chart's contract (data-points in x order, text ≥ 11 px on a phone).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  blendRow,
  calibrationChart,
  calibrationDots,
  concentrationText,
  intervalText,
  labelWords,
  recordHeadline,
  strataRows,
  versusGuess,
  voidedRows,
} from "../src/lib/calibration.js";

const FIXTURE = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "content", "fixtures", "calibration.json"), "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));

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

test("calibration labels: inadequate evidence reads as such; the API's label is rendered, no threshold invented", () => {
  assert.match(labelWords("not_measurable"), /^not measurable/);
  assert.equal(labelWords("insufficient_data"), "insufficient evidence");
  assert.equal(labelWords("nascent"), "insufficient evidence");
  assert.equal(labelWords("over-confident"), "came true less often than stated");
  assert.equal(labelWords("some_new_label"), "some new label");
  assert.equal(labelWords(null), "no label served");
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
  const pts = JSON.parse(svg.match(/data-points="([^"]*)"/)[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/&#39;/g, "'"));
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

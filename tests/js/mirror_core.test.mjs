// mirror_core.test.mjs — the JS half of the Mirror parity gate (#1392).
//
// Runs site/assets/js/mirror-core.js against tests/vectors/mirror_vectors.json —
// the fixture generated FROM the deployed Python scoring modules by
// scripts/gen_mirror_vectors.py. Exact equality, never a tolerance (ADR-105):
// every value both sides report is rounded at the source, so any difference is
// a real drift between what the site scores a reader on and what scores Matthew.
//
// The parser half (parseCsv / extractWhoopExport / buildDays) has no Python twin
// (the platform ingests the Whoop API, not CSVs), so it is covered here directly
// with fixture CSV text.

import "./support/loader.mjs"; // registers the "/assets/js/…" resolver — must precede the module import
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const VECTORS = JSON.parse(readFileSync(path.join(ROOT, "tests", "vectors", "mirror_vectors.json"), "utf8"));

const core = await import(
  "file://" + path.join(ROOT, "site", "assets", "js", "mirror-core.js")
);

// deepStrictEqual with the one impedance mismatch normalised: Python None → JSON
// null, while an absent optional in JS is undefined. The ports return null
// explicitly, so a bare undefined reaching this comparison IS a defect.
function exact(actual, expected, ctx) {
  assert.deepStrictEqual(actual, expected, ctx);
}

test("percentile matches the deployed personal_baselines.percentile", () => {
  for (const c of VECTORS.percentile) {
    exact(core.percentile(c.values, c.p), c.expected, `percentile(${JSON.stringify(c.values)}, ${c.p})`);
  }
});

test("avg matches the deployed scoring_engine.avg", () => {
  for (const c of VECTORS.avg) {
    exact(core.avg(c.values), c.expected, `avg(${JSON.stringify(c.values)})`);
  }
});

test("computeHrvBand matches compute_bands[readiness_hrv_ratio] incl. the MIN_N floor-guard", () => {
  for (const c of VECTORS.hrv_band) {
    exact(core.computeHrvBand(c.ratios), c.expected, `band over n=${c.ratios.length}`);
  }
});

test("readinessHrvScore matches personal_baselines.readiness_hrv_score", () => {
  for (const c of VECTORS.readiness_hrv_score) {
    exact(core.readinessHrvScore(c.ratio, c.baselines), c.expected, `${c.label} ratio=${c.ratio}`);
  }
});

test("normalizeWhoopSleep matches the deployed normalize_whoop_sleep", () => {
  for (const c of VECTORS.normalize_whoop_sleep) {
    exact(core.normalizeWhoopSleep(c.item === null ? null : { ...c.item }), c.expected, JSON.stringify(c.item));
  }
});

test("scoreSleep matches the deployed score_sleep", () => {
  for (const c of VECTORS.score_sleep) {
    exact(core.scoreSleep(c.data, c.profile), c.expected, JSON.stringify(c.data));
  }
});

test("scoreRecovery matches the deployed score_recovery", () => {
  for (const c of VECTORS.score_recovery) {
    exact(core.scoreRecovery(c.data), c.expected, JSON.stringify(c.data));
  }
});

test("computeReadiness matches the deployed compute_readiness", () => {
  for (const c of VECTORS.compute_readiness) {
    exact(core.computeReadiness(c.data, c.baselines), c.expected, c.label);
  }
});

// ── parser half — JS-only, fixture CSVs ──────────────────────────────────

const CYCLES_CSV = [
  '"Cycle start time","Cycle end time","Cycle timezone","Recovery score %","Resting heart rate (bpm)",' +
    '"Heart rate variability (ms)","Day Strain","Sleep performance %","Sleep efficiency %",' +
    '"In bed duration (min)","Awake duration (min)","Asleep duration (min)",' +
    '"Light sleep duration (min)","Deep (SWS) duration (min)","REM duration (min)"',
  '"2026-07-01 06:02:00","2026-07-02 05:58:00","America/Los_Angeles","67","52","48.7231","14.2","84","91.34",' +
    '"482","37","445","245","91","109"',
  '"2026-07-02 05:58:00","2026-07-03 06:11:00","America/Los_Angeles","41","55","39.05","9.8","71","88.9",' +
    '"401","44","357","201","70","86"',
  // a row with no recovery (device off) — sleep still parsed, recovery absent not zero
  '"2026-07-03 06:11:00","2026-07-04 06:40:00","America/Los_Angeles","","","","","65","82.1",' +
    '"390","51","339","198","61","80"',
].join("\n");

test("extractWhoopExport maps a cycles CSV onto the ingestion field shape", () => {
  const { records, meta } = core.extractWhoopExport(CYCLES_CSV);
  assert.equal(meta.kind, "cycles");
  assert.equal(meta.rows, 3);
  const d1 = records["2026-07-01"];
  assert.equal(d1.recovery_score, 67);
  assert.equal(d1.resting_heart_rate, 52);
  assert.equal(d1.hrv, 48.72); // 2dp, matching whoop_lambda's hrv rounding
  assert.equal(d1.strain, 14.2);
  assert.equal(d1.sleep_duration_hours, 7.42); // (482−37)/60 at 2dp — in-bed minus awake
  assert.equal(d1.slow_wave_sleep_hours, 1.52);
  assert.equal(d1.rem_sleep_hours, 1.82);
  assert.equal(d1.light_sleep_hours, 4.08);
  assert.equal(d1.time_awake_hours, 0.62);
  assert.equal(d1.sleep_efficiency_percentage, 91.34);
  assert.equal(d1.sleep_performance_percentage, 84);
  assert.equal(d1.sleep_quality_score, 84);
  // honest absence: the recovery-less day has NO recovery_score key, not a zero
  assert.ok(!("recovery_score" in records["2026-07-03"]));
  assert.equal(records["2026-07-03"].sleep_quality_score, 65);
});

test("extractWhoopExport skips nap rows and unparseable dates", () => {
  const sleeps = [
    '"Sleep onset","Wake onset","Nap","Asleep duration (min)","In bed duration (min)","Awake duration (min)"',
    '"2026-07-01 23:10:00","2026-07-02 06:40:00","false","420","455","35"',
    '"2026-07-02 14:00:00","2026-07-02 14:40:00","true","38","40","2"', // nap — skipped
    '"not-a-date","","false","100","110","10"', // unparseable — skipped, counted
  ].join("\n");
  const { records, meta } = core.extractWhoopExport(sleeps);
  assert.equal(meta.kind, "sleeps");
  assert.equal(meta.rows, 1);
  assert.equal(meta.skipped, 2);
  assert.equal(records["2026-07-01"].sleep_duration_hours, 7);
});

test("extractWhoopExport refuses an unrecognised CSV instead of misreading it", () => {
  const { records, meta } = core.extractWhoopExport("a,b,c\n1,2,3\n");
  assert.deepStrictEqual(records, {});
  assert.equal(meta.kind, "unrecognised");
});

test("buildDays scores each day and derives the reader's own HRV band past MIN_N", () => {
  // 40 synthetic days with drifting HRV — enough history for the personal band.
  const records = {};
  for (let i = 0; i < 40; i++) {
    const date = `2026-06-${String(1 + i).padStart(2, "0")}`;
    const d = i < 30 ? date : `2026-07-${String(i - 29).padStart(2, "0")}`;
    records[d] = {
      recovery_score: 40 + (i % 30),
      hrv: 40 + (i % 9) * 2.5,
      sleep_duration_hours: 7.1,
      sleep_quality_score: 70 + (i % 15),
      sleep_efficiency_percentage: 90.0,
    };
  }
  const { days, baselines, band_n } = core.buildDays(records);
  assert.equal(days.length, 40);
  assert.ok(band_n >= 30, `expected the personal band to engage, n=${band_n}`);
  assert.ok(baselines.readiness_hrv_ratio, "personal band should be present past MIN_N");
  const last = days[days.length - 1];
  assert.ok(Number.isInteger(last.readiness) && last.readiness >= 0 && last.readiness <= 100);
  assert.ok(["green", "yellow", "red"].includes(last.readiness_colour));
  // TSB never appears: a Whoop export has no external training-load series
  assert.ok(last.readiness_breakdown.every((c) => c.key !== "tsb"));
  // sleep pillar present and clamped
  assert.ok(Number.isInteger(last.sleep_pillar));
});

test("buildDays below MIN_N stays on the population fallback — floor-guard honoured", () => {
  const records = {};
  for (let i = 1; i <= 10; i++) {
    records[`2026-07-${String(i).padStart(2, "0")}`] = { recovery_score: 50, hrv: 45 };
  }
  const { baselines } = core.buildDays(records);
  assert.deepStrictEqual(baselines, {}, "no personal band below the floor-guard");
});

test("percentileRank is exact midrank on the sorted sample", () => {
  const sample = [1, 2, 2, 3, 4];
  assert.equal(core.percentileRank(sample, 2), ((1 + 2 / 2) / 5) * 100);
  assert.equal(core.percentileRank(sample, 0), 0);
  assert.equal(core.percentileRank(sample, 9), 100);
  assert.equal(core.percentileRank([], 2), null);
  assert.equal(core.percentileRank(sample, null), null);
});

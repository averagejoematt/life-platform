// #5953: a night still recording when it was read is marked on the data room's tiles and charts — read from the Day
// objects of the same snapshot, never inferred.
import assert from "node:assert/strict";
import { test } from "node:test";

import { svgChart } from "../src/lib/chart.js";
import { NIGHT_METRICS, PROVISIONAL_WORDS, markProvisional, provisionalNights } from "../src/lib/provisional.js";

const dayObj = (date, eightsleep, whoop = null) => ({ date, night: { by_device: { eightsleep, whoop } } });
const DAYS = [
  dayObj("2026-10-14", { provisional: false }),
  dayObj("2026-10-16", { provisional: true }, { provisional: null }),
  dayObj("2026-10-15", { provisional: null }),
  { date: "2026-10-17", night: null },
];
const series = (vals) => vals.map((v, i) => ({ date: `2026-10-${String(13 + i).padStart(2, "0")}`, value: v, present: v != null, gap: false }));

test("only a night the snapshot marks true is provisional, for the series' own device", () => {
  assert.deepEqual(provisionalNights(DAYS, "deep_pct", "eightsleep"), ["2026-10-16"]);
  // the strap's flag on that night is null (Whoop stores a sleep only once scored): its series is not marked
  assert.deepEqual(provisionalNights(DAYS, "sleep_duration_hours", "whoop"), []);
  // false and null are not provisional; a day with no night is not provisional
  assert.equal(provisionalNights(DAYS, "deep_pct", "eightsleep").includes("2026-10-14"), false);
});

test("a series that does not measure a night is never marked, whatever the night says", () => {
  assert.equal(NIGHT_METRICS.has("recovery_score"), false);
  assert.deepEqual(provisionalNights(DAYS, "recovery_score", "eightsleep"), []);
  assert.deepEqual(provisionalNights(DAYS, "deep_pct", null), []);
  assert.deepEqual(provisionalNights(null, "deep_pct", "eightsleep"), []);
});

test("marking copies the days and marks only a reading, never a missing day or a gap", () => {
  const days = series([15, 16, 17, null]);
  const marked = markProvisional(days, ["2026-10-15", "2026-10-16"]);
  assert.notEqual(marked, days);
  assert.equal(days[2].provisional, undefined, "the input is not changed");
  assert.deepEqual(
    marked.map((d) => Boolean(d.provisional)),
    [false, false, true, false],
  );
  assert.equal(markProvisional(days, []), days);
});

test("the chart rings a provisional reading and labels its point; no other point carries the words", () => {
  const days = markProvisional(series([15, 16, 17, 14.5]), ["2026-10-16"]);
  const svg = svgChart({ series: [{ days, color: "#1B3FD6", name: "deep" }], unit: "%", decimals: 1 });
  assert.equal((svg.match(/data-provisional/g) || []).length, 1);
  const points = JSON.parse(svg.match(/data-points="([^"]*)"/)[1].replace(/&quot;/g, '"'));
  const flagged = points.filter((p) => p.label.includes(PROVISIONAL_WORDS)).map((p) => p.date);
  assert.deepEqual(flagged, ["2026-10-16"]);
  // control: the same series unmarked draws no ring and no words
  const plain = svgChart({ series: [{ days: series([15, 16, 17, 14.5]), color: "#1B3FD6", name: "deep" }], unit: "%", decimals: 1 });
  assert.equal(plain.includes("data-provisional"), false);
  assert.equal(plain.includes(PROVISIONAL_WORDS), false);
});

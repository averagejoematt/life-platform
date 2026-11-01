import assert from "node:assert/strict";
import { test } from "node:test";

import { headline, lastDays, niceTicks, presentCount, rollingMean, segments, svgChart, weeklyBars } from "../src/lib/chart.js";

const day = (i, value, extra = {}) => ({ date: `2026-09-${String(6 + i).padStart(2, "0")}`, value, present: value != null, gap: false, ...extra });

test("segments break at a missing reading and at a logging gap, never bridging either", () => {
  const days = [day(0, 1), day(1, 2), day(2, null), day(3, 4), day(4, 5, { gap: true }), day(5, 6)];
  const segs = segments(days);
  assert.deepEqual(
    segs.map((s) => s.map((p) => p.i)),
    [[0, 1], [3], [5]],
  );
});

test("a 7-day mean needs three readings and ignores nulls", () => {
  const m = rollingMean([10, null, 30, 50, 70, 90, 110, 130], 7, 3);
  assert.equal(m[0], null);
  assert.equal(m[1], null);
  assert.equal(m[2], null, "two readings in the window is not enough");
  assert.equal(m[3], (10 + 30 + 50) / 3);
  assert.equal(m[7], (30 + 50 + 70 + 90 + 110 + 130) / 6);
});

test("nice ticks cover the range with round steps", () => {
  const t = niceTicks(233.4, 241.9, 6);
  assert.ok(t[0] <= 233.4 && t[t.length - 1] >= 241.9);
  assert.ok(t.every((v, i) => i === 0 || Math.abs(v - t[i - 1] - (t[1] - t[0])) < 1e-9));
});

test("the svg draws one path per segment, a hollow vermillion mark per gap and a square per missing reading", () => {
  const days = [day(0, 1), day(1, 2), day(2, null), day(3, 4), day(4, null, { gap: true }), day(5, 6)];
  const svg = svgChart({ series: [{ days, color: "#1B3FD6", name: "x" }], aria: "test" });
  assert.equal((svg.match(/<path /g) || []).length, 3);
  assert.equal((svg.match(/stroke="#D9341C"/g) || []).length, 1);
  assert.equal((svg.match(/<rect x=/g) || []).length, 1);
  assert.ok(svg.includes('role="img"') && svg.includes('aria-label="test"'));
  assert.ok(!svg.includes("NaN") && !svg.includes("undefined"));
});

test("a regime marker is drawn only when its date is on the axis", () => {
  const days = [day(0, 1), day(1, 2), day(2, 3)];
  const on = svgChart({ series: [{ days, color: "#000", name: "x" }], markers: [{ date: days[1].date, label: "a change" }] });
  const off = svgChart({ series: [{ days, color: "#000", name: "x" }], markers: [{ date: "2026-12-25", label: "a change" }] });
  assert.ok(on.includes("a change") && !off.includes("a change"));
});

test("an empty series renders an empty, labelled svg", () => {
  const svg = svgChart({ series: [{ days: [], color: "#000", name: "x" }] });
  assert.ok(svg.includes("no readings") && !svg.includes("<path"));
});

test("headline, lastDays, presentCount and weeklyBars read the series without inventing values", () => {
  const days = Array.from({ length: 21 }, (_, i) => day(i, i % 5 === 0 ? null : 100 + i));
  assert.equal(presentCount(days), 21 - 5);
  assert.equal(lastDays(days, 7).length, 7);
  assert.equal(lastDays(days, null).length, 21);
  const h = headline(days);
  assert.equal(h.last, 119, "the last PRESENT reading, not the last day");
  assert.equal(h.first, 101);
  assert.equal(h.n, 16);
  const bars = weeklyBars(days, 8);
  assert.equal(bars.length, 3);
  assert.ok(bars.every((b) => b == null || Number.isFinite(b)));
  assert.deepEqual(weeklyBars([day(0, null), day(1, null)], 8), [null]);
});

// tests/js/projected_year_4780.test.mjs — #4780, the #4766 class on a second page.
//
// The evidence page's Results topic (renderResults) showed its "projected goal (80% range)"
// figure through fmtShort with no year: a 2027 window read "Jul 2–Sep 18" on a 2026 page, i.e.
// as dates already past. renderResults now opts in to fmtShort's { yearIfNotCurrent } spelling
// (the same rule as entry_age.js dayInWords, #4767). `now` is pinned so every assertion here is
// clock-free, and the default fmtShort spelling is pinned year-less at several clocks so the
// opt-in can never become a New-Year time bomb for the year-less fixtures elsewhere.

import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderResults } = await import("../../site/assets/js/evidence_intelligence.js");
const { fmtShort } = await import("../../site/assets/js/evidence_shared.js");

// /api/weight_progress is the only fetch renderResults makes; an empty series is enough.
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ weight_progress: [] }) });

const NOW_2026 = new Date("2026-10-10T20:00:00Z");
const J = { goal_weight_lbs: 185, current_weight_lbs: 290, lost_lbs: 12, progress_pct: 10, projected_goal_date: "2027-08-10" };

test("#4780 a next-year 80% range prints its year at both ends", async () => {
  const html = await renderResults({ journey: { ...J, projected_goal_date_earliest: "2027-07-02", projected_goal_date_latest: "2027-09-18" } }, null, { now: NOW_2026 });
  assert.match(html, /Jul 2, 2027–Sep 18, 2027/);
  assert.match(html, /projected goal \(80% range\)/);
});

test("#4780 a range straddling New Year: only the next-year end carries its year", async () => {
  const html = await renderResults({ journey: { ...J, projected_goal_date_earliest: "2026-12-20", projected_goal_date_latest: "2027-02-11" } }, null, { now: NOW_2026 });
  assert.match(html, /Dec 20–Feb 11, 2027/);
});

test("#4780 a current-year range stays year-less", async () => {
  const html = await renderResults({ journey: { ...J, projected_goal_date_earliest: "2026-11-02", projected_goal_date_latest: "2026-12-18" } }, null, { now: NOW_2026 });
  assert.match(html, /Nov 2–Dec 18</);
});

test("#4780 fmtShort opt-in uses the PACIFIC year, not UTC", () => {
  // 2027-01-01T03:00Z is still Dec 31, 2026 in Pacific time: a 2027 date is out-of-year.
  assert.equal(fmtShort("2027-03-05", { yearIfNotCurrent: true, now: new Date("2027-01-01T03:00:00Z") }), "Mar 5, 2027");
  assert.equal(fmtShort("2026-03-05", { yearIfNotCurrent: true, now: new Date("2027-01-01T03:00:00Z") }), "Mar 5");
  assert.equal(fmtShort("garbage", { yearIfNotCurrent: true, now: NOW_2026 }), "");
});

test("#4780 the DEFAULT fmtShort spelling is year-less at every clock (no New-Year time bomb)", () => {
  for (const iso of ["2026-03-05", "2027-07-02", "2031-01-01"]) {
    const md = fmtShort(iso);
    assert.doesNotMatch(md, /, \d{4}$/, `${iso} default spelling carried a year: ${md}`);
  }
});

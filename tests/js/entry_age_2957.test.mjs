// tests/js/entry_age_2957.test.mjs — #2957: an installment's age is a PACIFIC
// calendar count, and "archive entry" is a claim that has to be earned.
//
// The chronicle reader opens on the newest installment; in a weekly serial that is
// routinely days old. On Day 7 of cycle 14 the Day-2 piece was the featured read with
// nothing but its ISO date, and the reader-truth judge called it a temporal
// contradiction. The frame is the fix — but a frame that reports the WRONG number is
// worse than none, and the first draft of it did:
//
//   Math.round((Date.now() - Date.parse("YYYY-MM-DD")) / 86400000)
//
// mixes a UTC-midnight parse with an absolute instant, so it tips at 12:00 UTC and
// every Pacific reader past ~05:00 local saw one day too many — this morning's post
// announced as "yesterday", a 28-day-old one as 29. Same defect class as #2941.
//
// The contract pinned here: the age depends ONLY on the instant, through the PT
// calendar date. Every case is an absolute UTC instant, so these assertions hold
// identically on a Pacific laptop, a UTC CI runner, and a reader's browser in London.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { ptDaysAgo, entryAgeSuffix } = await import("../../site/assets/js/entry_age.js");

// 2026-08-23 in Pacific runs from 07:00Z on the 23rd to 07:00Z on the 24th (PDT, UTC-7).
const PT_MORNING = new Date("2026-08-23T16:00:00Z"); // 09:00 PDT — past the old 12:00Z tip
const PT_EVENING = new Date("2026-08-24T02:00:00Z"); // 19:00 PDT on the 23rd
const PT_JUST_AFTER_MIDNIGHT = new Date("2026-08-23T07:30:00Z"); // 00:30 PDT on the 23rd

test("today's entry reads today at every hour of the Pacific day", () => {
  for (const now of [PT_JUST_AFTER_MIDNIGHT, PT_MORNING, PT_EVENING]) {
    assert.equal(ptDaysAgo("2026-08-23", now), 0, `at ${now.toISOString()}`);
    assert.equal(entryAgeSuffix("2026-08-23", now), " · today", `at ${now.toISOString()}`);
  }
});

test("the old UTC-instant arithmetic's off-by-one is gone", () => {
  // The exact live symptom: 09:00 PDT, an entry dated today, previously " · yesterday".
  assert.equal(entryAgeSuffix("2026-08-23", PT_MORNING), " · today");
  // And the 28-vs-29 day report on the lab-notes-era diary date.
  assert.equal(ptDaysAgo("2026-07-26", PT_MORNING), 28);
});

test("yesterday is dated, not archived — the archive clause is earned", () => {
  assert.equal(entryAgeSuffix("2026-08-22", PT_MORNING), " · yesterday");
  assert.ok(!entryAgeSuffix("2026-08-22", PT_MORNING).includes("archive"));
  const older = entryAgeSuffix("2026-08-18", PT_MORNING);
  assert.equal(older, " · written 5 days ago — an archive entry, not today's");
});

test("an unusable or future date renders no frame at all", () => {
  // A frame we cannot substantiate is worse than no frame.
  for (const bad of ["", null, undefined, "not-a-date", "2026-13-45"]) {
    assert.equal(entryAgeSuffix(bad, PT_MORNING), "", String(bad));
  }
  assert.equal(ptDaysAgo("nope", PT_MORNING), null);
  // A future-dated installment (a staged genesis, #931) is not "0 days ago".
  assert.equal(entryAgeSuffix("2026-09-01", PT_MORNING), "");
});

test("an ISO timestamp is accepted by its date half", () => {
  assert.equal(ptDaysAgo("2026-08-18T14:03:00Z", PT_MORNING), 5);
});

test("the answer does not depend on the host timezone", () => {
  // The #2941 lesson, restated: two runs at the same instant must agree regardless of
  // where the code runs. TZ is read by Intl at format time, and entry_age pins the zone
  // explicitly, so the only way this can drift is if someone reintroduces a local parse.
  const before = process.env.TZ;
  try {
    process.env.TZ = "Europe/London";
    assert.equal(ptDaysAgo("2026-08-23", PT_EVENING), 0);
    process.env.TZ = "Pacific/Auckland";
    assert.equal(ptDaysAgo("2026-08-23", PT_EVENING), 0);
  } finally {
    if (before === undefined) delete process.env.TZ;
    else process.env.TZ = before;
  }
});

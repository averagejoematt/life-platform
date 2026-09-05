// tests/js/timeline_chronicle_pending_3525.test.mjs — #3525: the story timeline's
// milestone→chronicle link must point at the week that narrates the milestone, or say
// there isn't one yet. It must never fall through to "the newest post".
//
// The live state on 2026-09-04 (/story/timeline/): under
//     "2026-09-05 · Day 1 · Starting weight: 325 lbs. Goal: 185."
// the link read "Read Week 1 →" and pointed at /story/chronicle/#2026-09-01 — cycle
// 15's "328.1" installment. Still live on 2026-09-05 with a different wrong target:
//     /journal/posts.json  → [{date: 2026-09-04, week: 0, label: "Prologue · Part II"},
//                             {date: 2026-08-30, week: 0, label: "Prologue · Part I"}]
//     /api/journey_timeline → [{date: 2026-09-05, type: milestone, title: "Day 1"}]
// nothing is dated on/after 2026-09-05, so `postFor` returned `posts[0]` — the Prologue
// — and offered it as the week that narrates Day 1.
//
// dispatches.js:293 ended `return best || posts[0] || null;`. The honest-absence branch
// downstream ("see more" / no link) already existed and was structurally unreachable
// while `posts` was non-empty. This is not an edge case: it is the state of the Day-1
// milestone in EVERY cycle, plus any milestone in the days before a Wednesday publish.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { postForDate } = await import("../../site/assets/js/chronicle_order.js");

// The live manifest, verbatim (2026-09-05). Both installments predate genesis: they are
// the ADR-077 `--keep-chronicle` lead-ins carried across the cycle-16 reset.
const LIVE_POSTS = [
  { date: "2026-09-04", week: 0, sequence: 2, label: "Prologue · Part II" },
  { date: "2026-08-30", week: 0, sequence: 1, label: "Prologue · Part I" },
];
const GENESIS = "2026-09-05";

// The pre-fix rule, verbatim from dispatches.js:293 — the negative control.
const postForOld = (posts, date) => {
  let best = null;
  for (const p of posts) {
    if (!p.date) continue;
    if (p.date >= date && (!best || p.date < best.date)) best = p;
  }
  return best || posts[0] || null;
};

/* ── Day 1 of a cycle: the reported state ────────────────────────────────── */

test("#3525 the Day-1 milestone has no installment yet → null, not the newest post", () => {
  assert.equal(postForDate(LIVE_POSTS, "2026-09-05", GENESIS), null);
});

test("#3525 negative control: the OLD rule returns the prior cycle's Prologue", () => {
  const p = postForOld(LIVE_POSTS, "2026-09-05");
  assert.ok(p, "control: the old rule always returned something");
  assert.equal(p.date, "2026-09-04");
  assert.equal(p.label, "Prologue · Part II", "control: exactly the wrong link the live page rendered");
  // And on 2026-09-04, with cycle 15's manifest, the same fallback produced the
  // #2026-09-01 target the issue quotes.
  const cycle15 = [{ date: "2026-09-01", week: 15, label: "Week 15" }];
  assert.equal(postForOld(cycle15, "2026-09-05").date, "2026-09-01", "control: the originally reported target");
  assert.equal(postForDate(cycle15, "2026-09-05", GENESIS), null, "and the new rule refuses it");
});

test("#3525 no post from before genesis may narrate a milestone on/after genesis", () => {
  // The whole of the first week of a cycle, every day: nothing published yet, so nothing
  // links. Guard the SET, not the one reported instance.
  for (const d of ["2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]) {
    assert.equal(postForDate(LIVE_POSTS, d, GENESIS), null, `${d} must not link a pre-genesis installment`);
  }
});

/* ── once Week 1 exists ──────────────────────────────────────────────────── */

const WITH_WEEK_1 = [{ date: "2026-09-11", week: 1, label: "Week 1" }, ...LIVE_POSTS];

test("#3525 'Read Week 1' links the post that IS Week 1", () => {
  const p = postForDate(WITH_WEEK_1, "2026-09-05", GENESIS);
  assert.equal(p.date, "2026-09-11");
  assert.equal(p.label, "Week 1", "the week that ENDS on/after Day 1 is the one that narrates it");
});

test("#3525 the SOONEST qualifying week wins, never the newest", () => {
  const posts = [
    { date: "2026-10-02", week: 4, label: "Week 4" },
    { date: "2026-09-25", week: 3, label: "Week 3" },
    { date: "2026-09-18", week: 2, label: "Week 2" },
    { date: "2026-09-11", week: 1, label: "Week 1" },
    ...LIVE_POSTS,
  ];
  assert.equal(postForDate(posts, "2026-09-05", GENESIS).label, "Week 1");
  assert.equal(postForDate(posts, "2026-09-12", GENESIS).label, "Week 2");
  assert.equal(postForDate(posts, "2026-09-25", GENESIS).label, "Week 3", "an exact match on the publish date");
  // A milestone AFTER the newest installment is still pending — the pre-Wednesday case.
  assert.equal(postForDate(posts, "2026-10-03", GENESIS), null);
  assert.equal(postForOld(posts, "2026-10-03").label, "Week 4", "control: the old rule linked the newest");
});

/* ── the genesis line cuts BOTH ways ─────────────────────────────────────── */

test("#3525 a carried-forward pre-genesis milestone links its own side of the line", () => {
  const posts = [{ date: "2026-09-11", week: 1, label: "Week 1" }, ...LIVE_POSTS];
  // A lead-in moment dated 2026-08-28 is narrated by Prologue Part I, not by this
  // cycle's Week 1 — an installment cannot narrate a moment from before its cycle began.
  const p = postForDate(posts, "2026-08-28", GENESIS);
  assert.equal(p.label, "Prologue · Part I");
  assert.equal(postForDate(posts, "2026-09-01", GENESIS).label, "Prologue · Part II");
  // And once the pre-genesis side is exhausted, pending — never a jump across the line.
  assert.equal(postForDate([{ date: "2026-09-11", week: 1, label: "Week 1" }], "2026-08-28", GENESIS), null);
});

/* ── degenerate inputs ───────────────────────────────────────────────────── */

test("#3525 an empty manifest is pending, not a crash", () => {
  assert.equal(postForDate([], "2026-09-05", GENESIS), null);
  assert.equal(postForDate(null, "2026-09-05", GENESIS), null);
  assert.equal(postForDate(undefined, "2026-09-05", GENESIS), null);
});

test("#3525 without a known genesis the rule still refuses the newest-post fallback", () => {
  // /api/journey can fail; the timeline still renders. Losing the genesis floor must
  // degrade to "the soonest week on/after the date", never back to `posts[0]`.
  assert.equal(postForDate(LIVE_POSTS, "2026-09-05", null), null, "the fallback is gone unconditionally");
  assert.equal(postForDate(LIVE_POSTS, "2026-08-31", null).date, "2026-09-04");
});

test("#3525 timestamped dates are compared by their date part", () => {
  const posts = [{ date: "2026-09-11T07:00:00Z", week: 1, label: "Week 1" }];
  assert.equal(postForDate(posts, "2026-09-05T00:00:00Z", GENESIS).label, "Week 1");
});

test("#3525 a milestone with no date is pending", () => {
  assert.equal(postForDate(WITH_WEEK_1, "", GENESIS), null);
  assert.equal(postForDate(WITH_WEEK_1, null, GENESIS), null);
});

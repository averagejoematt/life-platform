// tests/js/coaching_prestart_3517.test.mjs — #3517: one door, one story.
//
// THE DEFECT (live, Day 0 of cycle 16). coaching.js applied `preStart()` PER TAB. The
// Read tab rendered the honest "their first take lands here once Day 1's numbers exist";
// the By-Coach and Team tabs called `enrichCoachLive()` outside every pre-start gate and
// rendered each coach's live `position_summary` as the card subtitle. The subtitle
// readers actually got was "…No weight reading has arrived since the September 5th
// reset" — a past-tense claim about a genesis that had not happened yet.
//
// Two properties pinned here:
//
//   1. rosterEntries(coaches, {preStart:true})  -> every entry's `sub` is exactly "".
//      POSITIVE CONTROL: {preStart:false} -> the live read is present. Without that
//      control the assertion would pass on a function that returned "" unconditionally.
//   2. A SOURCE set-guard (the daily_line.test.mjs / coach_asof.test.mjs idiom): the
//      `enrichCoachLive` CALL in coaching.js must itself be pre-start-gated. Property 1
//      alone would still let the page fetch and ship the wiped cycle's read in the
//      payload; gating only the render is the shape of fix that leaks.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { rosterEntries } = await import("../../site/assets/js/coach_roster.js");

const SITE_JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "assets", "js");

const ROSTER = [
  { persona_id: "physical_coach", name: "Dr. Nathan Reeves", domain: "physical_health", tier: "member", _live: "No weight reading has arrived since the September 6th reset." },
  { persona_id: "nutrition_coach", name: "Dr. Amara Chen", domain: "nutrition", tier: "member", _live: "MacroFactor isn't syncing yet." },
  { persona_id: "head_coach", name: "Elena Voss", domain: "integrator", tier: "lead" },
];

test("pre-start: every roster subtitle is empty — no live Day-0 read reaches a card", () => {
  const entries = rosterEntries(ROSTER, { preStart: true });
  assert.equal(entries.length, 3);
  for (const e of entries) {
    assert.equal(e.sub, "", `${e.id} must carry an empty subtitle pre-start, got ${JSON.stringify(e.sub)}`);
  }
});

test("POSITIVE CONTROL — not pre-start: the live read IS the subtitle", () => {
  const entries = rosterEntries(ROSTER, { preStart: false });
  assert.equal(entries[0].sub, "No weight reading has arrived since the September 6th reset.");
  assert.equal(entries[1].sub, "MacroFactor isn't syncing yet.");
  // A coach with no live read still gets a string, never `undefined` (the old shape).
  assert.equal(entries[2].sub, "");
});

test("the rest of the card is unchanged by the gate (title / domain / tier survive)", () => {
  for (const pre of [true, false]) {
    const e = rosterEntries(ROSTER, { preStart: pre })[2];
    assert.equal(e.id, "head_coach");
    assert.equal(e.title, "Elena Voss");
    assert.equal(e.date, "integrator");
    assert.equal(e.tier, "lead");
  }
});

test("missing / empty roster degrades to an empty list, never a throw", () => {
  assert.deepEqual(rosterEntries(undefined, { preStart: true }), []);
  assert.deepEqual(rosterEntries([], {}), []);
  assert.deepEqual(rosterEntries(null, undefined), []);
});

/* ── the source set-guard: the FETCH is gated, not only the render ─────────── */

test("coaching.js gates the enrichCoachLive call on preStart()", () => {
  const src = readFileSync(join(SITE_JS, "coaching.js"), "utf8");
  const call = src.split("\n").find((l) => l.includes("await enrichCoachLive("));
  assert.ok(call, "the enrichCoachLive call site must still exist");
  assert.match(
    call,
    /!preStart\(\)/,
    `the live-read fetch must be pre-start-gated at its call site, not only at render time; got: ${call.trim()}`
  );
});

test("coaching.js maps the roster through rosterEntries, not a second inline copy", () => {
  const src = readFileSync(join(SITE_JS, "coaching.js"), "utf8");
  assert.ok(src.includes("rosterEntries("), "coaching.js must build the roster through the gated helper");
  assert.ok(
    !/sub:\s*c\._live\b/.test(src),
    "the ungated `sub: c._live` mapping must be gone, not merely supplemented — a second copy is how this drifts back"
  );
});

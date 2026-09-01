// tests/js/genesis_pt_2941.test.mjs — #2941: the Day/Week stamp is a PACIFIC
// calendar count, never a browser-local/UTC hybrid.
//
// The defect: genesisCount() computed
//   Math.floor((Date.now() - GENESIS.getTime()) / 86400000) + 1
// where GENESIS was parsed as browser-LOCAL midnight and Date.now() is a UTC
// instant — two clocks in one expression. A Pacific reader saw the right Day N;
// every reader east of Pacific saw a day ahead during their evening/our night.
// The newly-armed reader-truth gate caught it on its first live run (77 of 93
// pages carry the stamp) and the site deploy path auto-rolled-back.
//
// The contract pinned here: Day N depends ONLY on the instant, via the PT
// calendar date — never on the host machine's timezone. Every case below is an
// absolute UTC instant, so these assertions hold identically on a laptop in
// Pacific, a CI runner in UTC, or a reader's browser in London.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { genesisCount, GENESIS_ISO } = await import("../../site/assets/js/coach_popover.js");

const POPOVER_SRC = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "assets", "js", "coach_popover.js"),
  "utf8",
);

// Cycle-15 genesis. If a reset re-anchors this literal, the boundary instants
// below are wrong on purpose — regenerate them with the sweep, don't loosen.
test("this test's instants are anchored to the current genesis", () => {
  assert.equal(GENESIS_ISO, "2026-09-01");
});

test("the incident instant shape: 18:32 PT on Sep 5 is Day 5 everywhere (UTC already reads Sep 6)", () => {
  const { dayN, weekN, base } = genesisCount(new Date("2026-09-06T01:32:00Z"));
  assert.equal(dayN, 5); // the old code returned 6 on any UTC-clock host
  assert.equal(weekN, 1);
  assert.equal(base, "Day 5 · Week 1, since September 1 2026");
});

test("the day flips at PT midnight, not at the viewer's midnight", () => {
  assert.equal(genesisCount(new Date("2026-09-06T06:59:00Z")).dayN, 5); // 23:59 PT Sep 5
  assert.equal(genesisCount(new Date("2026-09-06T07:01:00Z")).dayN, 6); // 00:01 PT Sep 6
});

test("genesis day is Day 1 from PT midnight; before it is pre-start (dayN < 1)", () => {
  assert.equal(genesisCount(new Date("2026-09-01T07:01:00Z")).dayN, 1); // 00:01 PT genesis day
  assert.equal(genesisCount(new Date("2026-09-01T06:59:00Z")).dayN, 0); // 23:59 PT the night before
});

test("week arithmetic: Day 7 is Week 1, Day 8 is Week 2", () => {
  const d7 = genesisCount(new Date("2026-09-07T12:00:00Z")); // PT Sep 7
  assert.deepEqual([d7.dayN, d7.weekN], [7, 1]);
  const d8 = genesisCount(new Date("2026-09-08T12:00:00Z")); // PT Sep 8
  assert.deepEqual([d8.dayN, d8.weekN], [8, 2]);
});

test("crossing the DST fall-back boundary does not gain or lose a day", () => {
  // PDT→PST is Nov 1 2026. Nov 5 is 65 calendar days after Sep 1 → Day 66.
  // Instant-subtraction math would see an extra hour and drift here; the
  // UTC-noon date-only diff cannot.
  const { dayN } = genesisCount(new Date("2026-11-05T12:00:00Z"));
  assert.equal(dayN, 66);
});

test("set-guard: the two-clock expression may not return", () => {
  // The exact defect shape: an instant subtraction against the local-midnight
  // GENESIS Date. The PT calendar path has no business touching Date.now().
  assert.doesNotMatch(POPOVER_SRC, /Date\.now\(\)\s*-\s*GENESIS/);
});

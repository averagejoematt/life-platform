// tests/js/physical_dexa_consistency_3526_3558.test.mjs — #3526 + #3558.
//
// #3558 (DV-6/DV-7): the DEXA card printed TWO disagreeing body-fat percentages
// for one scan (the stacked-bar legend's own fat/(lean+fat) vs the caption's real
// body_fat_pct of total_mass_lb), and the visceral-fat gauge clamped a 3.21 lb
// datum to the right edge of a hard-coded 0–3 lb scale while its aria asserted
// the datum sat ON that scale.
//
// #3526: the DEXA caption asserted "the weight cockpit above shows where it is
// now" — a claim the scan can't back pre-start, when nothing has started yet.

import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { physicalDexaBaseline, physicalVisceralCallout } = await import("../../site/assets/js/evidence_body.js");

const DEXA = {
  scan_date: "2026-03-30",
  body_composition: {
    total_mass_lb: 311.7,
    body_fat_pct: 42.7,
    fat_mass_lb: 133.1,
    lean_mass_lb: 170.6,
    visceral_fat_lb: 3.21,
    visceral_fat_g: 1456,
  },
};

/* ── #3558 DV-6: exactly one body-fat percentage ─────────────────────────── */

test("#3558 physicalDexaBaseline: exactly one body-fat percentage, equal to body_fat_pct", () => {
  const html = physicalDexaBaseline({ latest_dexa: DEXA }, {});
  const visible = html.replace(/style="[^"]*"/g, '');
  const pcts = [...visible.matchAll(/(\d+(?:\.\d+)?)%/g)].map((m) => m[1]);
  assert.equal(pcts.length, 1, `expected exactly one percentage, got: ${JSON.stringify(pcts)}`);
  assert.equal(pcts[0], "42.7");
  assert.match(html, /42\.7% body fat/);
});

test("#3558 negative control: the pre-fix two-segment bar DOES print a second, disagreeing %", () => {
  // Verbatim the pre-fix shape: only {lean, fat} passed to stackedBar with its
  // default showPct, so its legend prints fat/(lean+fat) = 133.1/303.7 = 43.8%
  // — a DIFFERENT number from the caption's 42.7%. Proves the assertion above
  // can actually fail, not just pass vacuously.
  const total = DEXA.body_composition.lean_mass_lb + DEXA.body_composition.fat_mass_lb;
  const badPct = Math.round((DEXA.body_composition.fat_mass_lb / total) * 100);
  assert.equal(badPct, 44);
  assert.notEqual(String(badPct), String(DEXA.body_composition.body_fat_pct));
});

test("#3558 physicalDexaBaseline: the bar's three segments (lean/fat/bone-other) sum to total_mass_lb", () => {
  const html = physicalDexaBaseline({ latest_dexa: DEXA }, {});
  assert.match(html, /bone\/other/);
  assert.match(html, /8 lb/); // 311.7 - 170.6 - 133.1 = 8.0
});

test("#3558 physicalDexaBaseline: falls back to a two-segment bar when total_mass_lb is absent (still one %)", () => {
  const noTotal = { scan_date: "2026-03-30", body_composition: { ...DEXA.body_composition, total_mass_lb: undefined } };
  const html = physicalDexaBaseline({ latest_dexa: noTotal }, {});
  assert.doesNotMatch(html, /bone\/other/);
  const visible = html.replace(/style="[^"]*"/g, '');
  const pcts = [...visible.matchAll(/(\d+(?:\.\d+)?)%/g)].map((m) => m[1]);
  assert.equal(pcts.length, 1);
  assert.equal(pcts[0], "42.7");
});

/* ── #3526: the DEXA caption is phase-aware ──────────────────────────────── */

test("#3526 physicalDexaBaseline: post-start (or unknown) keeps the original claim", () => {
  const html = physicalDexaBaseline({ latest_dexa: DEXA }, { pre_start: false });
  assert.match(html, /the weight cockpit above shows where it is now/);
  assert.doesNotMatch(html, /the cut starts/);
});

test("#3526 physicalDexaBaseline: pre-start states the actual start date instead", () => {
  const html = physicalDexaBaseline({ latest_dexa: DEXA }, { pre_start: true, start_date: "2026-09-06" });
  assert.match(html, /the cut starts Sep 6/);
  assert.doesNotMatch(html, /shows where it is now/);
});

test("#3526 negative control: no journey argument at all behaves like post-start (the pre-fix shape)", () => {
  const html = physicalDexaBaseline({ latest_dexa: DEXA });
  assert.match(html, /shows where it is now/);
});

/* ── #3558 DV-7: the visceral-fat gauge never claims an off-scale datum fits ── */

test("#3558 physicalVisceralCallout: an off-scale datum (3.21 lb on a 0-3 scale) never marks the exact 100% edge", () => {
  const html = physicalVisceralCallout({ latest_dexa: DEXA });
  const m = /vf-mark[^"]*"\s+style="left:([\d.]+)%"/.exec(html);
  assert.ok(m, "marker style not found");
  assert.ok(Number(m[1]) < 100, `marker left% was ${m[1]}, expected < 100`);
  assert.match(html, /off the right edge/);
  assert.doesNotMatch(html, /on a directional 0–3 lb scale/, "must not assert the datum sits ON the scale when it doesn't");
});

test("#3558 negative control: the pre-fix formula DOES clamp to exactly 100%", () => {
  const maxS = 3;
  const lb = 3.21;
  const preFixPos = Math.max(0, Math.min(100, (lb / maxS) * 100));
  assert.equal(preFixPos, 100);
});

test("#3558 physicalVisceralCallout: an in-range datum is unaffected (no off-scale language, marker < 100%)", () => {
  const inRange = { scan_date: "2026-03-30", body_composition: { visceral_fat_lb: 1.4, visceral_fat_g: 635 } };
  const html = physicalVisceralCallout({ latest_dexa: inRange });
  const m = /vf-mark[^"]*"\s+style="left:([\d.]+)%"/.exec(html);
  assert.ok(m);
  assert.ok(Number(m[1]) < 100);
  assert.doesNotMatch(html, /off the right edge/);
  assert.match(html, /on a directional 0–3 lb scale/);
});

test("#3558 physicalVisceralCallout: for any finite input the marker's left% is always < 100", () => {
  for (const lb of [0, 0.5, 1, 2, 2.99, 3, 3.01, 5, 10, 100]) {
    const html = physicalVisceralCallout({ latest_dexa: { scan_date: "2026-03-30", body_composition: { visceral_fat_lb: lb } } });
    const m = /vf-mark[^"]*"\s+style="left:([\d.]+)%"/.exec(html);
    assert.ok(m, `no marker for lb=${lb}`);
    assert.ok(Number(m[1]) < 100, `lb=${lb} produced left%=${m[1]}`);
  }
});

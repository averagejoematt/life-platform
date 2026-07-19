// tests/js/evidence_character_receipts.test.mjs — the #1373 progression-receipt
// drill-down renderer (rcptHtml/rcptRule in evidence_receipts.js — a DOM-free
// module split out precisely so this harness can import it). The receipt is an
// HONESTY surface: an absent receipt must say so (never fabricate, ADR-104), a
// replay mismatch must be SHOWN, and drift must be labeled as "rules changed
// since" rather than silently re-rendered under today's rules.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { rcptHtml, rcptRule } = await import("../../site/assets/js/evidence_receipts.js");

const PAYLOAD = {
  available: true,
  receipt: {
    engine_version: "1.7.0",
    config_hash: "abc123def4567890",
    digest: "d1gest0000000000",
    input_rows: [
      { pk: "USER#matthew#SOURCE#whoop", sks: ["DATE#2026-07-17", "DATE#2026-07-18"] },
      { derived: "hevy_workout_days_7d", values: ["2026-07-16"] },
    ],
    transitions: {
      pillars: {
        movement: {
          inputs: { prev: { level: 4, xp_total: 10 }, raw_score: 71.2, level_score: 68.4, data_coverage: 0.9, bonus_xp: 0 },
          outputs: {
            level: 5, xp_delta: 1, xp_debt: 0, streak_above: 0, streak_below: 0, coverage_hold: false,
            events: [{ type: "level_up", old_level: 4, new_level: 5 }],
          },
        },
      },
      headline: { inputs: { prev_character_level: 3 }, outputs: { character_level: 4, events: [] } },
    },
  },
  replay: { digest_match: true },
};

test("rcptHtml — absent receipt renders the honest ADR-104 line, never a fabricated panel", () => {
  const html = rcptHtml({ available: false }, "2026-07-01");
  assert.match(html, /No receipt recorded/);
  assert.match(html, /back-fabricated/);
  assert.doesNotMatch(html, /Replay verified/);
});

test("rcptHtml — full receipt renders delta, rule, provenance, and the identity line", () => {
  const html = rcptHtml(PAYLOAD, "2026-07-18");
  assert.match(html, /Replay verified/);
  assert.match(html, /Movement/);
  assert.match(html, /4 → 5/); // the level delta
  assert.match(html, /rule: /);
  assert.match(html, /contributing input rows \(keys, not copies\)/);
  assert.match(html, /engine v1\.7\.0/);
  assert.match(html, /config abc123def456/); // truncated hash
  assert.match(html, /headline: Lv 3 → 4/);
});

test("rcptHtml — config/engine drift is labeled 'rules changed', not rewritten or hidden", () => {
  const drifted = { ...PAYLOAD, replay: { digest_match: false, config_drift: true, engine_drift: false } };
  const html = rcptHtml(drifted, "2026-07-18");
  assert.match(html, /Rules have changed since/);
  assert.match(html, /not rewritten/);
});

test("rcptHtml — a true mismatch (no drift) is surfaced as the alarm case", () => {
  const bad = { ...PAYLOAD, replay: { digest_match: false, config_drift: false, engine_drift: false } };
  const html = rcptHtml(bad, "2026-07-18");
  assert.match(html, /Replay mismatch/);
  assert.match(html, /flagged/);
});

test("rcptRule — labels the fired rule from outputs, holds included", () => {
  assert.match(rcptRule(PAYLOAD.receipt.transitions.pillars.movement), /Level Up/);
  assert.match(rcptRule({ inputs: {}, outputs: { coverage_hold: true, events: [] } }), /no-signal hold/);
  assert.match(rcptRule({ inputs: { not_instrumented: true }, outputs: { events: [] } }), /not instrumented/);
  assert.match(rcptRule({ inputs: {}, outputs: { events: [], streak_above: 3 } }), /up-streak building \(day 3\)/);
  assert.match(rcptRule({ inputs: {}, outputs: { events: [] } }), /steady/);
});

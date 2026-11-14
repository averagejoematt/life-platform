// tests/js/keystone_sign_5956.test.mjs — #5956 item 2: the keystone sentence follows the sign its own card shows.
//
// The accuracy review (2026-11-14, calibrated) found the habits page calling Nutrition the group "most pulling the day
// up" while its card read r = −0.57, "moves against the day grade". The sentence was fixed text; the sign was ignored.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { habitsKeystone } = await import("../../site/assets/js/evidence_habits.js");

test("a negative keystone says the grade tends to be LOWER on days the group is held more — never 'pulling the day up'", () => {
  const html = habitsKeystone([{ group: "nutrition", correlation_r: -0.57, n_days: 30 }]);
  assert.match(html, /moves against the day grade/);
  assert.match(html, /the day grade tends to be lower/);
  assert.doesNotMatch(html, /pulling the day up/);
  assert.doesNotMatch(html, /tends to be higher/);
});

test("a positive keystone says higher, and both say correlation, not cause", () => {
  const up = habitsKeystone([{ group: "movement", correlation_r: 0.44, n_days: 20 }]);
  assert.match(up, /moves up with the day grade/);
  assert.match(up, /the day grade tends to be higher/);
  for (const r of [0.44, -0.57]) assert.match(habitsKeystone([{ group: "g", correlation_r: r, n_days: 20 }]), /a correlation, not a cause/);
});

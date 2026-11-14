// The permanence panel's formatters (#5920): the build time is stated in words, never ISO; an unreadable value is
// null (the panel then says "not available"), never a guess.
import assert from "node:assert/strict";
import { test } from "node:test";

import { mib, stampInWords } from "../src/islands/permanence.js";

test("the archive's build time reads in words, in UTC", () => {
  assert.equal(stampInWords("2026-11-14T09:05:00Z"), "14 November 2026, 09:05 UTC");
  assert.doesNotMatch(stampInWords("2026-01-02T23:59:00+00:00"), /\d{4}-\d{2}-\d{2}/);
});

test("an unreadable time or size is absent, not guessed", () => {
  for (const bad of [null, "", "not a date", 42]) assert.equal(stampInWords(bad), null);
  for (const bad of [null, -1, Number.NaN, "12"]) assert.equal(mib(bad), null);
  assert.equal(mib(512), "512 bytes");
  assert.equal(mib(3 * 1024 * 1024), "3.0 MB");
});

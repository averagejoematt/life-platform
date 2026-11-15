// A week of The Line for a chapter row (2026-11-14, sprint II): placement only — real readings, nothing invented.
import assert from "node:assert/strict";
import { test } from "node:test";

import { weekStrip } from "../src/lib/theline.js";

const days = [
  { date: "2026-09-06", value: 327.3 },
  { date: "2026-09-07", value: null },
  { date: "2026-09-08", value: 325.1 },
  { date: "2026-09-09", value: 324.0 },
];

test("a week of the line: only real readings, a missing morning bridged dashed and ticked, the journey's latest morning the one cobalt dot", () => {
  const s = weekStrip({ days, from: "2026-09-06", to: "2026-09-09", lo: 320, hi: 330, latest: "2026-09-09" });
  assert.equal(s.n, 3);
  assert.equal(s.missing, 1);
  assert.equal(s.first.value, 327.3);
  assert.equal(s.last.value, 324.0);
  assert.match(s.svg, /stroke-dasharray="2 3"/);
  assert.equal((s.svg.match(/#1B3FD6/g) || []).length, 1, "one cobalt dot");
  assert.doesNotMatch(s.svg, /\d{4}-\d{2}-\d{2}/, "no ISO date reaches the markup");
});

test("a week with no reading draws nothing; a week with no chapter is muted and never cobalt", () => {
  assert.equal(weekStrip({ days, from: "2026-09-07", to: "2026-09-07", lo: 320, hi: 330 }), null);
  const muted = weekStrip({ days, from: "2026-09-06", to: "2026-09-08", lo: 320, hi: 330, muted: true, latest: "2026-09-09" });
  assert.doesNotMatch(muted.svg, /#1B3FD6/);
});

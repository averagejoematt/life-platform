// #5456 — /data/labs/: the panel is one draw that predates Day 1; the table must say so at the
// table, derived from the served payload (never a hard-coded date).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderLabs, labsDrawFrame, labsDrawShort } = await import("../../site/assets/js/evidence_body.js");

// Clock pinned: dayInWords prints the year once the draw is not in the current year.
const NOW = new Date("2026-10-27T20:00:00Z");
const bm = (n, flag) => ({ name: "Ldl C", value: String(n), unit: "mg/dL", range: "<100", flag, category: "Lipids" });
const L = (date, arch) => ({
  latest_draw_date: date, total_draws: 8, total_draws_scope: "all cycles", draws_this_cycle: 0,
  biomarkers: [bm(130, "H"), bm(90, null)], latest_draw_archival: arch,
});

test("#5456 a pre-cycle draw is dated and tied to Day 1, from the payload", () => {
  const a = L("2026-04-03", { pre_cycle: true, days_before: 156, genesis: "2026-09-06" });
  assert.match(labsDrawFrame(a, NOW), /^From the April 3 draw — 156 days before Day 1, not a result from this experiment\.$/);
  const h = renderLabs(a, NOW);
  assert.match(h, /Outside the reference range — 1 of 2<\/h2><p class="rd-meta label" data-labs-frame>From the April 3 draw/);
  assert.match(h, /The full panel — 2 rows · April 3 draw, before Day 1</);
});

test("#5456 the date is DERIVED — a different draw date prints a different label", () => {
  const a = L("2026-05-19", { pre_cycle: true, days_before: 110 });
  assert.match(labsDrawFrame(a, NOW), /From the May 19 draw — 110 days before Day 1/);
  assert.doesNotMatch(renderLabs(a, NOW), /April 3/);
});

test("#5456 an in-cycle draw carries its date but never a before-Day-1 claim", () => {
  const a = L("2026-10-02", null);
  assert.equal(labsDrawFrame(a, NOW), "From the October 2 draw.");
  assert.doesNotMatch(renderLabs(a, NOW), /before Day 1/);
});

test("#5456 pre-cycle with no day count still says before Day 1; no date prints nothing", () => {
  assert.match(labsDrawFrame(L("2026-04-03", { pre_cycle: true }), NOW), /April 3 draw — before Day 1/);
  assert.equal(labsDrawFrame({ biomarkers: [bm(1)] }), "");
  assert.equal(labsDrawShort({}), "");
  assert.doesNotMatch(renderLabs({ biomarkers: [bm(1, "H")] }, NOW), /data-labs-frame/);
});

// tests/js/vitals_glyph_asof_3287.test.mjs — #3287: the vitals glyph row renders the
// provenance the API computes.
//
// The API side is fixed in lambdas/web/vitals_resolver.py + site_api_pulse.py (tests/
// test_vitals_today_frame_3287.py): a record naming a day the Pacific calendar has not
// reached can no longer win "today, so far".
//
// This is the half the reader sees. The resolver's own contract is "Provenance is the
// *_as_of date — consumers surface staleness, they don't zero it", and the page did not:
// the chip rendered `gl.label || gl.delta_label` and NOTHING else, under a caption reading
// "A glyph lights only when its signal actually fires today". So /api/pulse could serve
// movement.as_of = 2026-08-28 on a page stamped 2026-08-27 — a partial next-UTC-day step
// count, coloured red — with the one field that would expose it computed, returned, and
// dropped. Fixing the selection without fixing this leaves the API's honesty invisible for
// every OTHER way a glyph can be a different day's (a stale source, a sync gap).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { vitalsGlyphs, glyphAsOfNote } = await import("../../site/assets/js/evidence_vitals.js");

const TODAY = "2026-08-27";

function pulse(glyphs, date = TODAY) {
  return { date, glyphs };
}

// The exact wire shape /api/pulse served at 21:01 PDT on 2026-08-27 — the state that filed
// the issue, kept as a fixture so the page's behaviour under it is pinned even though the
// API can no longer produce it.
const FILED = pulse({
  movement: { state: "red", value: 41, target: 8000, label: "41 steps", source: "apple_health", as_of: "2026-08-28", as_of_frame: "utc" },
  recovery: { state: "green", value: 71, label: "71%", as_of: TODAY },
});

const HEALTHY = pulse({
  movement: { state: "green", value: 9310, target: 8000, label: "9,310 steps", source: "apple_health", as_of: TODAY, as_of_frame: "utc" },
  recovery: { state: "green", value: 71, label: "71%", as_of: TODAY },
});

const STALE = pulse({
  movement: { state: "amber", value: 4200, target: 8000, label: "4,200 steps", source: "garmin", as_of: "2026-08-25", as_of_frame: "pacific" },
  recovery: { state: "green", value: 71, label: "71%", as_of: TODAY },
});

test("a glyph dated other than the page's own day wears that date", () => {
  const html = vitalsGlyphs(FILED, null);
  assert.match(html, /as of 2026-08-28/, "the as_of the API computed was dropped — the defect this fixes");
  assert.match(html, /vg-otherday/, "the mismatched chip must be visually distinguishable, not only textually");
});

test("the UTC frame is named, because the date alone reads as Pacific", () => {
  // apple_health's DATE# key names a UTC day (TD-19 Phase 2). "as of 2026-08-28" on a
  // Pacific page is not merely a different day — it is a different CALENDAR, and a reader
  // cannot infer that from the digits.
  assert.equal(glyphAsOfNote(FILED.glyphs.movement, TODAY), '<span class="vg-asof label">as of 2026-08-28 UTC</span>');
  assert.equal(glyphAsOfNote(STALE.glyphs.movement, TODAY), '<span class="vg-asof label">as of 2026-08-25</span>');
});

test("the caption stops claiming 'fires today' for a chip that does not", () => {
  const html = vitalsGlyphs(FILED, null);
  assert.match(html, /One signal is stamped with the day the reading belongs to/);
  assert.match(html, /<strong>not<\/strong> today's/);
});

test("a matching day renders NO date — an always-on stamp is noise", () => {
  // If every chip carried a date the reader would learn to skip the line that matters.
  const html = vitalsGlyphs(HEALTHY, null);
  assert.ok(!/as of /.test(html), "a glyph whose as_of IS the page date must not be stamped");
  assert.ok(!/vg-otherday/.test(html));
  assert.ok(!/stamped with the day/.test(html));
  assert.equal(glyphAsOfNote(HEALTHY.glyphs.movement, TODAY), "");
});

test("a stale source is disclosed too — not only the UTC-frame case", () => {
  // The selection fix removes the next-UTC-day case at the source. This is why the page
  // fix is still load-bearing: a garmin gap produces the same "today, so far" lie with no
  // frame involved at all.
  const html = vitalsGlyphs(STALE, null);
  assert.match(html, /as of 2026-08-25/);
  assert.ok(!/UTC/.test(html), "a Pacific-keyed source must not be labelled UTC");
});

test("more than one mismatched glyph is counted, not just announced", () => {
  const html = vitalsGlyphs(pulse({
    movement: { state: "red", label: "41 steps", as_of: "2026-08-28", as_of_frame: "utc" },
    water: { state: "amber", label: "1.2L", as_of: "2026-08-26" },
  }), null);
  assert.match(html, /2 signals are stamped with the day the reading belongs to/);
});

test("a missing as_of or page date degrades quietly (absent ⇒ unknown, never 'today')", () => {
  assert.equal(glyphAsOfNote({ label: "x" }, TODAY), "");
  assert.equal(glyphAsOfNote({ as_of: "2026-08-28" }, ""), "");
  assert.equal(glyphAsOfNote(null, TODAY), "");
  const html = vitalsGlyphs(pulse({ lift: { state: "gray", label: "No training logged" } }), null);
  assert.ok(!/as of /.test(html));
});

test("the existing chip contract is untouched", () => {
  const html = vitalsGlyphs(HEALTHY, { done: 3, total: 5 });
  assert.match(html, /9,310 steps/);
  assert.match(html, /3 of 5/);
  assert.match(html, /vg-lit/);
  assert.match(html, /Today, so far/);
});

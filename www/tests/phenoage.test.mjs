// PhenoAge on the Journey is markers-only (owner ruling 2026-11-14): the page helpers take the reference line and
// nothing else — no figure of his own exists in the snapshot for them to draw.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { offsetWords, referenceFigure, spanWords } from "../src/lib/phenoage.js";

const ref = {
  points: [
    { at_years: 30, reads_years: 27.9, offset_years: -2.1 },
    { at_years: 40, reads_years: 36.8, offset_years: -3.2 },
    { at_years: 50, reads_years: 45.7, offset_years: -4.3 },
    { at_years: 60, reads_years: 54.6, offset_years: -5.4 },
  ],
  offset_low: -5.4,
  offset_high: -2.1,
  slope: 0.892,
};

test("the offsets read in words, whichever side of the calendar they fall", () => {
  assert.equal(offsetWords(ref), "2.1 to 5.4 years younger than the calendar");
  assert.equal(offsetWords({ offset_low: 1.2, offset_high: 4 }), "1.2 to 4.0 years older than the calendar");
  assert.equal(offsetWords({ offset_low: -1.5, offset_high: 1.7 }), "between 1.5 years younger and 1.7 years older than the calendar");
  assert.equal(offsetWords(null), null);
  assert.equal(spanWords(ref), "30 to 60");
});

test("the figure draws every reference point and the calendar, and says his own point is not shown", () => {
  const svg = referenceFigure(ref);
  assert.equal((svg.match(/<circle/g) || []).length, 4);
  assert.match(svg, /stroke-dasharray="4 4"/);
  assert.match(svg, /His own position on the line is not shown/);
  assert.match(svg, /−2\.1/);
  assert.equal(referenceFigure({ points: [ref.points[0]] }), null);
});

test("the Journey page reads no figure of his own", () => {
  const page = readFileSync(new URL("../src/pages/data/journey/index.astro", import.meta.url), "utf8");
  assert.doesNotMatch(page, /PA\.years|PA\.phenoage|PA\.band|PA\.gap/);
  const fixture = JSON.parse(readFileSync(new URL("../content/fixtures/journey.json", import.meta.url), "utf8"));
  assert.deepEqual(Object.keys(fixture.phenoage).sort(), ["as_of", "drivers", "reference"]);
});

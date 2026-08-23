// tests/js/evidence_nutrition_meal_table_2329.test.mjs — #2329: the glucose door's
// meal table prints a real value in every column it prints a header for.
//
// The live defect: the table's headers were `meal | peak | Δ rise`, but
// /api/meal_glucose (the only arm — /api/meal_responses was retired by #2327 as a
// dead partition) publishes `meal, category, calories, protein, carbs,
// spike, grade, curve`. `m.peak ?? m.peak_mgdl` and `m.delta ?? m.rise` were
// undefined on every row, so the reader got meal names next to two columns of
// em-dashes the moment nutrition data returned (#2326).
//
// The fix binds the table to the keys the endpoint actually serves. These tests
// render renderGlucose end-to-end with a stubbed fetch — the exact payload shape
// meal_glucose publishes — and assert no cell is blank, no header is unbacked,
// and the ADR-104 absent state ("—" / "?") survives for an unmeasured meal.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderGlucose } = await import("../../site/assets/js/evidence_nutrition.js");

// The row shape meal_glucose really publishes (see site_api_meals.meal_glucose's
// results.append block) — one measured meal, one ADR-104 absent meal.
const MEASURED = { meal: "Chicken Burrito Bowl", category: "lunch", calories: 650, protein: 45, carbs: 55, spike: 22, grade: "B", curve: "gentle" };
const UNMEASURED = { meal: "Overnight Oats", category: "breakfast", calories: 420, protein: 18, carbs: 60, spike: null, grade: "?", curve: "unknown" };

function stubFetch(payloads) {
  globalThis.fetch = async (path) => {
    const body = payloads[path];
    if (body === undefined) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => body };
  };
}

async function renderWithFixtures() {
  stubFetch({
    // #2327: /api/meal_responses is retired — meal_glucose is the only arm.
    "/api/meal_glucose": { meals: [MEASURED, UNMEASURED], period_days: 30, has_cgm: true },
  });
  return renderGlucose({ glucose: { avg: 104, tir: 91 }, glucose_trend: [] });
}

test("with meal_glucose populated, no numeric cell is blank", async () => {
  const html = await renderWithFixtures();
  assert.match(html, /Meal glucose response/, "the meal section must render when the fallback arm has rows");
  // Every <td> carries visible content — never an empty cell, never JS stringified absence.
  assert.doesNotMatch(html, /<td[^>]*>\s*<\/td>/, "a rendered cell is blank");
  assert.doesNotMatch(html, /undefined|NaN/, "a binding reached a key the payload does not carry");
});

test("every column header has a backing value in every row", async () => {
  const html = await renderWithFixtures();
  const table = /<table class="rd-tbl"><thead>(.*?)<\/table>/s.exec(html);
  assert.ok(table, "meal table not found");
  const headers = [...table[1].matchAll(/<th>(.*?)<\/th>/g)].map((m) => m[1]);
  const rows = [...table[1].matchAll(/<tr>(.*?)<\/tr>/gs)]
    .map((m) => [...m[1].matchAll(/<td[^>]*>(.*?)<\/td>/g)].map((c) => c[1]))
    .filter((cells) => cells.length > 0);
  assert.equal(rows.length, 2, "both fixture meals must render");
  for (const cells of rows) {
    assert.equal(cells.length, headers.length, "a row must print exactly one cell per header");
    for (const c of cells) assert.notEqual(c.trim(), "", "a printed column may not be blank");
  }
});

test("the measured meal shows its spike estimate and grade", async () => {
  const html = await renderWithFixtures();
  assert.match(html, /<td class="rd-name">Chicken Burrito Bowl<\/td><td class="num">22<\/td><td class="num">B · gentle<\/td>/);
});

test("an unmeasured meal renders the ADR-104 absent markers, not zeros or blanks", async () => {
  const html = await renderWithFixtures();
  assert.match(html, /<td class="rd-name">Overnight Oats<\/td><td class="num">—<\/td><td class="num">\?<\/td>/);
});

test("the unbacked headers are gone — no column claims a per-meal peak the data cannot support", async () => {
  const html = await renderWithFixtures();
  assert.doesNotMatch(html, /<th>peak<\/th>/, "peak is not derivable from daily CGM aggregates (ADR-105)");
  assert.doesNotMatch(html, /<th>Δ rise<\/th>/);
});

test("with zero meals everywhere the section is skipped entirely, not rendered empty", async () => {
  stubFetch({
    "/api/meal_glucose": { meals: [], period_days: 6, has_cgm: true },
  });
  const html = await renderGlucose({ glucose: null, glucose_trend: [] });
  assert.doesNotMatch(html, /Meal glucose response/, "an empty cycle (#2326) must not print an empty table");
});

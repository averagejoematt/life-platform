// tests/js/evidence_wrong.test.mjs — The Wrong Feed (#1377).
//
// renderWrong turns the /api/wrong payload into a feed of obituary cards, one per
// graded failure. The load-bearing property (AC4) is that the headline "graded
// failures" count is DERIVED from the cards actually rendered — never a separate
// server literal that can drift from the feed (the historic "4 caught over 2 rows"
// self-contradiction class). These are pure string assertions, so they run offline.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderWrong } = await import("../../site/assets/js/evidence_intelligence.js");

// Pull the numeric value rendered under a given figure label out of the HTML.
function figValue(htmlStr, label) {
  const re = new RegExp(
    `<span class="fig-v num">([^<]*)</span><span class="fig-k label">${label}</span>`,
  );
  const m = htmlStr.match(re);
  return m ? m[1] : null;
}

function cardCount(htmlStr) {
  return (htmlStr.match(/class="wrong-ob"/g) || []).length;
}

function obit(i) {
  return {
    id: `id${i}`,
    date: `2026-07-${String(10 + i).padStart(2, "0")}`,
    coach: "sleep",
    believed: `sleep hours would come in at or above ${7 + i}`,
    number: `sleep hours measured ${6 + i} — the call was at or above ${7 + i}`,
    what_changed: "sleep_hours trend=down, predicted=up",
    permalink: `/moments/wrong/id${i}/`,
    og_image: `/moments/assets/wrong-id${i}.png`,
  };
}

test("headline count equals the number of obituary cards rendered (AC4)", () => {
  for (const n of [0, 1, 3, 7]) {
    const payload = {
      validator: { claims_checked: 99, caught_detailed: 2, caught_undetailed: 1, recent: [] },
      predictions: { by_coach: [], refuted_recent: [] },
      obituaries: Array.from({ length: n }, (_, i) => obit(i)),
      obituary_count: n,
      note: "uncurated",
    };
    const out = renderWrong(payload);
    assert.equal(cardCount(out), n, `rendered ${cardCount(out)} cards for n=${n}`);
    assert.equal(
      figValue(out, "graded failures"),
      String(n),
      `header 'graded failures' must equal the ${n} cards rendered`,
    );
  }
});

test("the headline count ignores a mismatched server scalar — it counts the rendered cards", () => {
  // A poisoned obituary_count must NOT win: the count derives from the card list.
  const payload = {
    validator: {},
    predictions: {},
    obituaries: [obit(0), obit(1)],
    obituary_count: 999, // deliberately wrong
    note: "",
  };
  const out = renderWrong(payload);
  assert.equal(cardCount(out), 2);
  assert.equal(figValue(out, "graded failures"), "2");
});

test("each card renders believed / number / what-changed + an anchor id + permalink", () => {
  const out = renderWrong({ obituaries: [obit(0)], validator: {}, predictions: {} });
  assert.match(out, /id="obit-id0"/);
  assert.match(out, /We believed:/);
  assert.match(out, /The number that killed it:/);
  assert.match(out, /What changed:/);
  assert.match(out, /href="\/moments\/wrong\/id0\/"/);
});

test("an empty feed is an honest empty-state, not a broken render", () => {
  const out = renderWrong({ obituaries: [], validator: {}, predictions: {} });
  assert.equal(cardCount(out), 0);
  assert.equal(figValue(out, "graded failures"), "0");
  assert.match(out, /No graded failures on the board yet/);
});

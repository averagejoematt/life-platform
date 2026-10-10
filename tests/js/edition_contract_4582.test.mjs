// tests/js/edition_contract_4582.test.mjs — #4582: the page's half of the contract with
// GET /api/edition.
//
// The documents are the route's own: tests/fixtures/edition_contract_4582/editions.json is
// compose() over the live wire with each upstream failing in turn (and all at once), held
// equal to the route by tests/test_edition_page_contract_4582.py. Here the front page's real
// block-to-slot wiring (frontSlots, the same map mount() fills the page from) renders each
// one. The rule: a block the route serves as `unavailable` or `absent` leaves its slot
// printing exactly that block's own sentence — never a blank, never the green figure.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const P = await import("../../site/assets/js/ck_pages.js");
const { esc } = await import("../../site/assets/js/evidence_shared.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "edition_contract_4582", "editions.json");
const { green, cases } = JSON.parse(readFileSync(FIX, "utf8"));

// The edition as the route serves it when that case's upstream fails.
const editionFor = (name) => ({ ...green, blocks: { ...green.blocks, ...cases[name].blocks } });
const failed = (b) => !!b && (b.state === "unavailable" || b.state === "absent");
// A slot that prints a sentence and nothing else: the sentence, escaped, bare or in the
// kit's one soft/small paragraph. Compared as markup — never stripped or unescaped.
const prints = (html, sentence) => [esc(sentence), `<p class="ck-soft">${esc(sentence)}</p>`, `<p class="ck-small">${esc(sentence)}</p>`].includes(html);

// Each front-page slot -> the block whose sentence it must print when that block failed.
// `next` prints its bet part's sentence, or the whole block's when the block is unserved.
const SLOT_BLOCK = {
  "ck-record": (b) => b.record,
  "ck-mark-caption": (b) => b.today,
  "ck-bet": (b) => (b.next && b.next.data && b.next.data.bet) || b.next,
  "ck-today": (b) => b.week,
  "ck-coach-lines": (b) => b.coach_lines,
  "ck-week": (b) => b.week,
  "ck-quotes": (b) => b.chapter,
};

test("the contract carries the green edition and every upstream failing", () => {
  assert.ok(Object.keys(cases).length >= 19, `only ${Object.keys(cases).length} cases`);
  assert.ok(cases.all && cases.journey && cases.dashboard && cases.predictions && cases.journal && cases.decisions);
  assert.equal(green.order.join(), Object.keys(green.blocks).join());
});

test("with one upstream failing, each front-page slot prints its block's own sentence, not a blank or a figure", () => {
  const offences = [];
  const seenFailing = new Set();
  const greenSlots = P.frontSlots(green, green.blocks, "/");
  for (const name of Object.keys(cases)) {
    const ed = editionFor(name);
    const slots = P.frontSlots(ed, ed.blocks, "/");
    for (const [slot, pick] of Object.entries(SLOT_BLOCK)) {
      const block = pick(ed.blocks);
      if (!failed(block)) continue;
      seenFailing.add(slot);
      const got = slots[slot];
      if (!got) offences.push(`${name}: ${slot} is blank`);
      else if (!prints(got, block.absent_text)) offences.push(`${name}: ${slot} printed ${JSON.stringify(got)}, not ${JSON.stringify(block.absent_text)}`);
      if (got === greenSlots[slot] && !prints(greenSlots[slot], block.absent_text)) offences.push(`${name}: ${slot} still shows the green content`);
    }
    // His words: a failed block is never quoted; its sentence sits at the foot of the week.
    if (failed(ed.blocks.his_words)) {
      seenFailing.add("ck-words-absent");
      if (slots["ck-words"] !== null) offences.push(`${name}: ck-words kept for a ${ed.blocks.his_words.state} block`);
      if (!prints(slots["ck-words-absent"], ed.blocks.his_words.absent_text)) offences.push(`${name}: ck-words-absent is not the block's sentence`);
    }
    for (const [slot, html] of Object.entries(slots)) {
      if (/undefined|NaN|>null</.test(String(html))) offences.push(`${name}: ${slot} leaks ${JSON.stringify(html)}`);
    }
  }
  assert.deepEqual(offences, []);
  // Every slot was exercised failing by at least one case — the loop cannot go vacuous.
  assert.deepEqual([...seenFailing].sort(), [...Object.keys(SLOT_BLOCK), "ck-words-absent"].sort());
});

test("today's weight fails to its sentence and the green weight leaves the mark and its caption", () => {
  const ed = editionFor("journey");
  assert.equal(ed.blocks.today.state, "unavailable");
  const weight = green.blocks.today.data.weight_lbs.toFixed(1);
  assert.match(P.frontSlots(green, green.blocks)["ck-mark-caption"], new RegExp(weight.replace(".", "\\.")));
  const slots = P.frontSlots(ed, ed.blocks);
  assert.equal(slots["ck-mark-caption"], esc("Today's weight is not served right now."));
  assert.equal(slots["ck-mark"], "");
});

test("with every upstream failing, the page still has one day, and the bet slot does not claim there is no bet", () => {
  const ed = editionFor("all");
  assert.equal(P.headerDay(ed), P.headerDay(green));
  assert.ok(P.headerDay(ed));
  assert.equal(ed.blocks.next.state, "unavailable");
  const bet = P.frontSlots(ed, ed.blocks)["ck-bet"];
  assert.ok(prints(bet, "What comes next is not served right now."), bet);
  assert.doesNotMatch(bet, /No coach bet is waiting/);
});

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
// Round 8 (#4586): the week band and the chapter quote moved to the week page (weekSlots);
// the front page's chapter is one row in "Go deeper".
const SLOT_BLOCK = {
  "ck-record": (b) => b.record,
  "ck-mark-caption": (b) => b.today,
  "ck-bet": (b) => (b.next && b.next.data && b.next.data.bet) || b.next,
  "ck-today": (b) => b.week,
  "ck-coach-lines": (b) => b.coach_lines,
  "ck-chapter-row": (b) => b.chapter,
};
const WEEK_SLOT_BLOCK = {
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
    // The week page's slots, the same rule.
    const week = P.weekSlots(ed, ed.blocks, "/");
    for (const [slot, pick] of Object.entries(WEEK_SLOT_BLOCK)) {
      const block = pick(ed.blocks);
      if (!failed(block)) continue;
      seenFailing.add(`week:${slot}`);
      if (!prints(week[slot], block.absent_text)) offences.push(`${name}: week ${slot} printed ${JSON.stringify(week[slot])}, not ${JSON.stringify(block.absent_text)}`);
    }
  }
  assert.deepEqual(offences, []);
  // Every slot was exercised failing by at least one case — the loop cannot go vacuous.
  assert.deepEqual([...seenFailing].sort(), [...Object.keys(SLOT_BLOCK), "ck-words-absent", ...Object.keys(WEEK_SLOT_BLOCK).map((k) => `week:${k}`)].sort());
});

// #4582 box 1: what the front page used to read from its own routes is now in the edition, so
// the slots it fills from those blocks are held to the same rule over the same documents.
// `ck-argument` prints the moves' sentence only when no open bet stands in for the argument.
const READ_SLOT_BLOCK = {
  "ck-call": (b) => b.calls,
  // No bet and no exchange: the label is "The AI" (site-to-A round 1) — before it, "The coaches".
  "ck-argument": (b) => (["The coaches", "The AI"].includes(P.frontReadSlots({ as_of: green.as_of }, b, "/")["ck-argue-label"]) ? b.moves : null),
};
const unserved = (b) => !!b && b.state === "unavailable";

test("the front page's other reads are the edition's blocks, and a failed one prints its own sentence", () => {
  assert.ok(green.blocks.calls && green.blocks.moves && green.blocks.sheet && green.blocks.lead_read);
  assert.equal(green.blocks.calls.state, "ok");
  const greenRead = P.frontReadSlots(green, green.blocks, "/");
  assert.match(greenRead["ck-call"], /The whole call/);
  assert.match(greenRead["ck-sheet-span"], /^Level \d+/);
  const offences = [];
  const seen = new Set();
  for (const name of Object.keys(cases)) {
    const ed = editionFor(name);
    const slots = P.frontReadSlots(ed, ed.blocks, "/");
    for (const [slot, pick] of Object.entries(READ_SLOT_BLOCK)) {
      const block = pick(ed.blocks);
      if (!unserved(block)) continue;
      seen.add(slot);
      if (!prints(slots[slot], block.absent_text)) offences.push(`${name}: ${slot} printed ${JSON.stringify(slots[slot])}, not ${JSON.stringify(block.absent_text)}`);
    }
    // A failed week of lines is never "nothing in dispute".
    if (unserved(ed.blocks.moves) && /Nothing is in dispute/.test(slots["ck-argue-heading"] || "")) offences.push(`${name}: a failed read claims nothing is in dispute`);
    // A failed sheet leaves the shell's own words, never a level from nowhere.
    if (unserved(ed.blocks.sheet) && "ck-sheet-span" in slots) offences.push(`${name}: ck-sheet-span filled from a failed sheet`);
    // The day's coach lines failing never removes their sentence.
    if (unserved(ed.blocks.coach_lines) && slots["ck-coach-lines"] === null) offences.push(`${name}: ck-coach-lines removed for a failed read`);
    for (const [slot, html] of Object.entries(slots)) {
      if (/undefined|NaN|>null</.test(String(html))) offences.push(`${name}: ${slot} leaks ${JSON.stringify(html)}`);
    }
  }
  assert.deepEqual(offences, []);
  assert.deepEqual([...seen].sort(), Object.keys(READ_SLOT_BLOCK).sort());
});

test("today's weight fails to its sentence and the green weight leaves the mark and its caption", () => {
  const ed = editionFor("journey");
  assert.equal(ed.blocks.today.state, "unavailable");
  const weight = green.blocks.today.data.weight_lbs.toFixed(1);
  assert.match(P.frontSlots(green, green.blocks)["ck-mark-caption"], new RegExp(weight.replace(".", "\\.")));
  const slots = P.frontSlots(ed, ed.blocks);
  assert.equal(slots["ck-mark-caption"], esc("Today's weight is not served right now."));
  // #4586 box 2: a picture with nothing to draw says so, not a blank.
  assert.equal(slots["ck-mark"], '<p class="ck-soft">No weigh-in since the start.</p>');
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

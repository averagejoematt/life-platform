// #6088 — "your call beside the coaches", built dark: the switch, the self-gating rule and the words.
// The master proof (a recursive diff of dist/ against main from the same snapshot) is run by hand and recorded in the
// PR; the deploy-side refusal is tests/test_www_readercall_dark_6088.py (scripts/check_www_build.py::readercall_leaks).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { READERCALL_ENV, READERCALL_ISLAND, readerCallEnabled, readerCallFor, readerCallIntegration } from "../src/lib/readercall.js";
import { COPY, gradedSentence, splitRows, splitSentence } from "../src/lib/readercall_view.js";

const injected = (env) => {
  const calls = [];
  readerCallIntegration(env).hooks["astro:config:setup"]({ injectScript: (stage, src) => calls.push([stage, src]) });
  return calls;
};

test("only the literal 1 turns the private switch on", () => {
  assert.equal(readerCallEnabled({}), false);
  for (const v of ["0", "true", "yes", "", " 1", "1 "]) assert.equal(readerCallEnabled({ [READERCALL_ENV]: v }), false, v);
  assert.equal(readerCallEnabled({ [READERCALL_ENV]: "1" }), true);
});

test("off injects nothing; on injects exactly the island", () => {
  assert.deepEqual(injected({}), []);
  const on = injected({ [READERCALL_ENV]: "1" });
  assert.equal(on.length, 1);
  assert.equal(on[0][0], "page");
  assert.ok(on[0][1].includes(JSON.stringify(READERCALL_ISLAND)));
});

test("the control appears only beside a one-tap, published, undisputed call", () => {
  const base = { kind: "direction", status: "pending", sealed: false, claim_withheld: null, classification_review: false };
  assert.equal(readerCallFor(base), true);
  assert.equal(readerCallFor({ ...base, kind: "number", status: "confirmed" }), true);
  for (const bad of [{ kind: "yes_no" }, { kind: "sealed" }, { sealed: true }, { claim_withheld: "unsourced" }, { claim_withheld: "no_words" }, { status: "expired" }, { classification_review: true }])
    assert.equal(readerCallFor({ ...base, ...bad }), false, JSON.stringify(bad));
});

test("the component gates on the switch before it renders anything, and carries no style or script", () => {
  const src = readFileSync(new URL("../src/components/ReaderCall.astro", import.meta.url), "utf8");
  assert.match(src, /const on = readerCallEnabled\(\) && readerCallFor\(p\);/);
  assert.match(src, /^\{\s*on && \(/m);
  assert.doesNotMatch(src, /<script|<style/);
});

test("the copy says what it is, and the split never reads as evidence", () => {
  assert.equal(COPY, "Make your own call. It is counted with other readers', apart from the coach's record.");
  const choices = [
    { id: "up", label: "Up" },
    { id: "down", label: "Down" },
    { id: "same", label: "About the same" },
  ];
  assert.deepEqual(
    splitRows(choices, { counts: { up: 1, down: 3 }, total: 4 }).map((r) => [r.id, r.count, r.pct]),
    [
      ["up", 1, 25],
      ["down", 3, 75],
      ["same", 0, 0],
    ],
  );
  assert.equal(splitSentence(choices, { counts: {}, total: 0 }), "No reader has made a call on this one yet.");
  assert.equal(splitSentence(choices, null), "Readers' calls could not be read just now.");
  assert.equal(splitSentence(choices, { counts: { up: 1 }, total: 1 }), "1 reader: Up 1 · Down 0 · About the same 0");
  const view = { choices, tally: { counts: { up: 2, down: 5, same: 1 }, total: 8 }, graded: { coach_status: "confirmed", reading_side: "down" } };
  assert.equal(gradedSentence(view), "Most readers called Down (5 of 8). The reading: Down — 5 readers called that.");
  assert.equal(gradedSentence({ ...view, graded: { reading_side: null } }), "Most readers called Down (5 of 8). The grade names no side for the reading.");
  assert.equal(gradedSentence({ ...view, tally: { counts: {}, total: 0 } }), "The reading: Down. No reader made a call before the due day.");
  for (const s of [gradedSentence(view), splitSentence(choices, view.tally)]) assert.doesNotMatch(s, /right|wrong|evidence|proves?/i);
});

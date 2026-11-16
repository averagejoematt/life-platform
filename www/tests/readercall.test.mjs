// #6088 / #6114 — "your call beside the coaches", built dark: the switch, the self-gating rule and the words.
// The master proof (a recursive diff of dist/ against main from the same snapshot) is run by hand and recorded in the
// PR; the deploy-side refusal is tests/test_www_readercall_dark_6088.py (scripts/check_www_build.py::readercall_leaks).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { READERCALL_ENV, READERCALL_ISLAND, READERCALL_LIVE, itemIdOf, readerCallEnabled, readerCallFor, readerCallIntegration, readerCallPrivate } from "../src/lib/readercall.js";
import { COPY, LIST_EMPTY, LIST_INTRO, afterSentence, closedSentence, coachLine, gradedSentence, listRow, openSentence, splitRows, splitSentence, viewState } from "../src/lib/readercall_view.js";

const injected = (env, live = false) => {
  const calls = [];
  readerCallIntegration(env, live).hooks["astro:config:setup"]({ injectScript: (stage, src) => calls.push([stage, src]) });
  return calls;
};

const choices = [
  { id: "up", label: "Up" },
  { id: "down", label: "Down" },
  { id: "same", label: "About the same" },
];

test("committed live (#6114); with live off only the literal 1 turns the private switch on", () => {
  assert.equal(READERCALL_LIVE, true);
  assert.equal(readerCallEnabled({}), true);
  assert.equal(readerCallPrivate({ [READERCALL_ENV]: "1" }), false, "a live build is not private");
  assert.equal(readerCallEnabled({}, false), false);
  for (const v of ["0", "true", "yes", "", " 1", "1 "]) assert.equal(readerCallEnabled({ [READERCALL_ENV]: v }, false), false, v);
  assert.equal(readerCallEnabled({ [READERCALL_ENV]: "1" }, false), true);
  assert.equal(readerCallPrivate({ [READERCALL_ENV]: "1" }, false), true);
});

test("only a private build injects the island; live builds carry it in the two components", () => {
  assert.deepEqual(injected({}), []);
  assert.deepEqual(injected({}, true), [], "live: the island ships with the components, never injected on every page");
  assert.deepEqual(injected({ [READERCALL_ENV]: "1" }, true), []);
  const on = injected({ [READERCALL_ENV]: "1" });
  assert.equal(on.length, 1);
  assert.equal(on[0][0], "page");
  assert.ok(on[0][1].includes(JSON.stringify(READERCALL_ISLAND)));
});

test("the control appears beside a one-tap, unsealed, undisputed call — words published or not", () => {
  const base = { kind: "direction", status: "pending", sealed: false, retired: false, claim_withheld: "no_words", classification_review: false };
  assert.equal(readerCallFor(base), true);
  assert.equal(readerCallFor({ ...base, kind: "number", status: "confirmed", claim_withheld: null }), true);
  for (const bad of [{ kind: "yes_no" }, { kind: "sealed" }, { sealed: true }, { retired: true }, { status: "expired" }, { classification_review: true }])
    assert.equal(readerCallFor({ ...base, ...bad }), false, JSON.stringify(bad));
});

test("the page id maps to the public item id the API keys on", () => {
  assert.equal(itemIdOf("sleep-20261109-ttsbic8"), "sleep:20261109-ttsbic8");
  assert.equal(itemIdOf("nutrition-20261029-s7sctvq"), "nutrition:20261029-s7sctvq");
  assert.equal(itemIdOf("nohyphen"), null);
});

test("both components gate on the switch before they render anything, and carry only the island import", () => {
  for (const name of ["ReaderCall.astro", "ReaderCallList.astro"]) {
    const src = readFileSync(new URL(`../src/components/${name}`, import.meta.url), "utf8");
    assert.match(src, /const on = readerCallEnabled\(\)/, name);
    assert.match(src, /^\{\s*on && \(/m, name);
    assert.doesNotMatch(src, /<style/, name);
    // counted by plain string search (no tag-matching regex): exactly one script block, the island import
    assert.equal(src.toLowerCase().split("<script").length - 1, 1, name);
    assert.ok(src.includes('<script>\n  import "../islands/readercall.js";\n</script>'), name);
  }
});

test("the words count reader calls, never readers, and never read as evidence", () => {
  assert.equal(COPY, "Make your own call. It is counted with the other reader calls, apart from the coach's record.");
  assert.deepEqual(
    splitRows(choices, { counts: { up: 1, down: 3 }, total: 4 }).map((r) => [r.id, r.count, r.pct]),
    [
      ["up", 1, 25],
      ["down", 3, 75],
      ["same", 0, 0],
    ],
  );
  assert.equal(splitSentence(choices, { counts: {}, total: 0 }), "No reader call was made on this one.");
  assert.equal(splitSentence(choices, { counts: { up: 1 }, total: 1 }), "1 reader call: Up 1 · Down 0 · About the same 0");
  const graded = { choices, reader_calls: { counts: { up: 2, down: 5, same: 1 }, total: 8 }, graded: { coach_status: "confirmed", coach_choice: "down", reading_side: "down" } };
  assert.equal(gradedSentence(graded), "Most reader calls said Down (5 of 8). The reading: Down — 5 reader calls said that.");
  assert.equal(coachLine(graded), "Down · right");
  const open = { choices, your_call: null, called_on_words: "14 November", open_until_words: "21 November", result_due_words: "12 December" };
  assert.equal(
    openSentence(open),
    "The coach called this on 14 November, before any of it happened; reader calls are open until the end of 21 November. Reader calls stay hidden until then, so no one's call steers yours.",
  );
  assert.equal(
    afterSentence({ ...open, your_call: "up" }),
    "You called: Up. Reader calls stay hidden until they close at the end of 21 November. The result arrives from 12 December: come back then to see your call beside the coach's.",
  );
  assert.equal(closedSentence({ ...open, your_call: "up" }), "You called: Up. Reader calls are closed; the call is graded from 12 December.");
  assert.equal(
    listRow("Lisa Park", { short_question: "weight — up, down or about the same by 28 November", open_until_words: "21 November" }),
    "Lisa Park · weight — up, down or about the same by 28 November · open until 21 November",
  );
  // a cold landing on a graded call (no stored choice anywhere): the comparison stands alone
  assert.equal(gradedSentence({ ...graded, your_call: null }), "Most reader calls said Down (5 of 8). The reading: Down — 5 reader calls said that.");
  assert.match(LIST_INTRO, /not as equivalent scientific evidence/);
  assert.match(LIST_EMPTY, /^No coach call is open right now\./);
  for (const s of [gradedSentence(graded), splitSentence(choices, graded.reader_calls), openSentence(open), closedSentence(open), LIST_INTRO, LIST_EMPTY]) {
    assert.doesNotMatch(s, /\breaders?\b(?! call)/i, s);
    assert.doesNotMatch(s.replace("not as equivalent scientific evidence", ""), /evidence|proves?/i, s);
  }
});

test("the page state for every API answer — a shut door or an ineligible call shows nothing, never an error", () => {
  const ok = (body) => ({ ok: true, status: 200, body: { available: true, choices, ...body } });
  assert.equal(viewState(null), "hidden");
  assert.equal(viewState({ ok: false, status: 404, body: { error: "Reader calls are not available." } }), "hidden"); // switch off
  assert.equal(viewState({ ok: false, status: 409, body: { error: "This call is not open for reader calls." } }), "hidden");
  assert.equal(viewState({ ok: true, status: 200, body: { available: true } }), "hidden"); // the bare probe
  assert.equal(viewState(ok({ open: true })), "open");
  assert.equal(viewState(ok({ open: false })), "closed");
  assert.equal(viewState(ok({ open: false, graded: { coach_status: "refuted" } })), "graded");
});

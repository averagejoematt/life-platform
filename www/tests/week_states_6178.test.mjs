// #6178 (owner ruling 2026-11-22 §4): a retired week is its own state — said in words, never given a page, never
// folded into "skipped" — and the narrator is named the same way on every byline.
import { test } from "node:test";
import assert from "node:assert/strict";
import { gapWords } from "../src/lib/format.js";
import { hasPage } from "../src/lib/url.js";
import { CHAPTER_BYLINE, INDEX_BYLINE, NARRATOR_BYLINE, NARRATOR_WHO } from "../src/lib/narrator.js";

const ch = (week, status) => ({ id: `program-week-${week}`, week, status });

test("the weeks between two chapters name a retired week as retired", () => {
  const chapters = [ch(7, "skipped"), ch(8, "held"), ch(9, "retired"), ch(11, "retired")];
  assert.equal(gapWords(chapters, 7, 9), "Week 7 was skipped; week 8 is held; week 9 was retired.");
  assert.equal(gapWords([ch(8, "retired"), ch(9, "retired")], 8, 9), "Weeks 8 and 9 were retired.");
});

test("a retired week, like a held one, has no page; skipped and published do", () => {
  assert.equal(hasPage("chapter", ch(9, "retired")), false);
  assert.equal(hasPage("chapter", ch(8, "held")), false);
  assert.equal(hasPage("chapter", ch(7, "skipped")), true);
  assert.equal(hasPage("chapter", ch(10, "published")), true);
});

test("every byline names Elena Voss as an AI editorial persona", () => {
  assert.match(NARRATOR_WHO, /^Elena Voss, an AI editorial persona \(a language model/);
  for (const line of [NARRATOR_BYLINE, CHAPTER_BYLINE, INDEX_BYLINE]) assert.ok(line.includes(NARRATOR_WHO), line);
  assert.ok(!/\bI\b/.test(NARRATOR_BYLINE + CHAPTER_BYLINE + INDEX_BYLINE), "no byline is written in the owner's first person");
});

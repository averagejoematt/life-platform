// #6177 (owner rulings 2026-11-22 §6 and §9): the chrome beside a published chapter says only what the record shows.
// Synthetic chapters only. Off (the committed default) returns exactly what the pages printed before; the recursive
// dist diff against main is the build-level proof (PR body).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BYLINE_APPROVAL,
  BYLINE_RULE,
  CHAPTER_TRUTH_LIVE,
  INDEX_BYLINE_TRUE,
  applyDerivedCovers,
  cardCorrection,
  cardQuote,
  chapterByline,
  derivedCovers,
  entryVerb,
  indexByline,
  momentsQuoteWho,
  quotesThreshold,
  recordAsOf,
  rewriteOf,
} from "../src/lib/chapter_truth.js";
import { CHAPTER_BYLINE, INDEX_BYLINE, NARRATOR_BYLINE } from "../src/lib/narrator.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const NOTE = `<p class="signature"><em>Editor&#39;s note, October 2026 — A. Persona: this installment was rewritten after a review.</em></p><p>Body.</p>`;
const ch = (extra = {}) => ({
  id: "week-30",
  status: "published",
  week: 3,
  date: "2030-01-22",
  week_start: "2030-01-20",
  week_end: "2030-01-26",
  published_at: "2030-01-25",
  published_via: null,
  covers_start: null,
  covers_end: null,
  body_html: "<p>Body.</p>",
  ...extra,
});

test("the switch is committed OFF, as one line the Python reader can parse", () => {
  assert.equal(CHAPTER_TRUTH_LIVE, false);
  const src = readFileSync(join(HERE, "..", "src", "lib", "chapter_truth.js"), "utf8");
  assert.equal((src.match(/^export const CHAPTER_TRUTH_LIVE = (true|false);$/gm) || []).length, 1);
});

test("off: every line is exactly what the pages printed before #6177", () => {
  for (const via of ["approval", "rule", null]) assert.equal(chapterByline(ch({ published_via: via, body_html: NOTE }), false), CHAPTER_BYLINE);
  assert.equal(indexByline(false), INDEX_BYLINE);
  assert.equal(recordAsOf(ch({ body_html: NOTE }), false), "Coach records quoted in this chapter are as published on 25 January 2030.");
  assert.equal(recordAsOf(ch({ published_at: null }), false), null);
  assert.equal(momentsQuoteWho(false), "an approved");
  assert.equal(entryVerb(false), "approved");
  const q = { text: "a rate more than twice its threshold", cite: "T" };
  assert.deepEqual(cardQuote(q, false), { ...q, citeWords: "T, as published" });
  assert.equal(cardCorrection([{ kind: "correction", dated_on: "2030-02-01" }], false), null);
  const list = [ch()];
  assert.deepEqual(applyDerivedCovers(list, false), []);
  assert.equal(list[0].covers_start, null);
});

test("on: the byline says how the chapter was published, and never claims an approval without a record", () => {
  assert.equal(chapterByline(ch({ published_via: "approval" }), true), BYLINE_APPROVAL);
  assert.equal(chapterByline(ch({ published_via: "rule" }), true), BYLINE_RULE);
  assert.equal(chapterByline(ch({ published_via: null }), true), NARRATOR_BYLINE);
  assert.equal(chapterByline(ch({ published_via: "something-else" }), true), NARRATOR_BYLINE);
  assert.match(chapterByline(ch({ published_via: "rule", body_html: NOTE }), true), /First published automatically under the platform's 48-hour rule/);
  assert.match(chapterByline(ch({ published_via: "approval", body_html: NOTE }), true), /First published after Matthew's recorded approval\.$/);
  assert.ok(!/approved it/.test(chapterByline(ch({ published_via: "rule" }), true)));
  assert.ok(!/approv/i.test(chapterByline(ch({ published_via: null }), true)), "unknown says nothing about approval");
  assert.equal(indexByline(true), INDEX_BYLINE_TRUE);
  assert.ok(!/published only after Matthew approves it/.test(INDEX_BYLINE_TRUE));
});

test("on: a rewritten chapter's records are dated to the rewrite, or to 'a later revision' when the note names no month", () => {
  assert.deepEqual(rewriteOf(NOTE), { month: "October 2026" });
  assert.equal(rewriteOf("<p>Editor's note: this installment was rewritten.</p>").month, null);
  assert.equal(rewriteOf("<p>No note here.</p>"), null);
  assert.equal(rewriteOf("<p>Editor's note, October 2026 — X: a sample note.</p>"), null, "a note that is not a rewrite");
  assert.equal(recordAsOf(ch({ body_html: NOTE }), true), "Coach records quoted in this chapter are as of its rewrite in October 2026, not its first publication on 25 January 2030.");
  assert.equal(
    recordAsOf(ch({ body_html: "<p>Editor's note: this installment was rewritten.</p>" }), true),
    "Coach records quoted in this chapter are as of a later revision of this chapter, not its first publication on 25 January 2030.",
  );
  assert.equal(recordAsOf(ch(), true), "Coach records quoted in this chapter are as published on 25 January 2030.");
  assert.equal(recordAsOf(ch({ published_at: null, body_html: NOTE }), true), "Coach records quoted in this chapter are as of its rewrite in October 2026.");
  assert.equal(recordAsOf(ch({ status: "held" }), true), null);
});

test("on: a published chapter with no stored days reads the seven days ending on its data date, from Day 1, never overlapping", () => {
  // the rule reproduces stored spans: genesis 2030-01-06 (week 3 starts the 20th); Day 1–3 for a chapter dated Day 3
  assert.deepEqual(derivedCovers(ch()), { covers_start: "2030-01-16", covers_end: "2030-01-22" });
  assert.deepEqual(derivedCovers(ch({ week: 1, week_start: "2030-01-06", week_end: "2030-01-12", date: "2030-01-08" })), { covers_start: "2030-01-06", covers_end: "2030-01-08" });
  assert.equal(derivedCovers(ch({ covers_start: "2030-01-15", covers_end: "2030-01-21" })), null, "a stored span is never replaced");
  assert.equal(derivedCovers(ch({ status: "held" })), null);
  assert.equal(derivedCovers(ch({ week: 0 })), null, "the prologue has no covered days");
  assert.equal(derivedCovers(ch({ date: "2030-01-01" })), null, "a data date before Day 1");
  const prev = ch({ id: "week-29", week: 2, covers_start: "2030-01-13", covers_end: "2030-01-17" });
  assert.equal(derivedCovers(ch(), [prev, ch()]), null, "overlapping another chapter's stored days: nothing is guessed");
  const list = [ch({ id: "a" }), ch({ id: "b", covers_start: "2030-01-09", covers_end: "2030-01-15" })];
  assert.deepEqual(applyDerivedCovers(list, true), ["a"]);
  assert.equal(list[0].covers_start, "2030-01-16");
  assert.equal(list[1].covers_start, "2030-01-09");
});

test("on: a card never quotes a ratio to, or the value of, a threshold, and cites the quotation as the chapter now reads", () => {
  for (const t of ["a rate the platform flags as more than twice its lean-mass threshold", "pace at 3x the line", "against a threshold of 2.5", "half the cap"]) assert.ok(quotesThreshold(t), t);
  for (const t of ["A 5.2-pound week tripped the platform's rate flag", "the line through the weeks", "twice in a row", "Recovery hit 98% twice."]) assert.ok(!quotesThreshold(t), t);
  assert.equal(cardQuote({ text: "a rate more than twice its threshold", cite: "T" }, true), null);
  assert.deepEqual(cardQuote({ text: "Monday read 292.6.", cite: "T" }, true), { text: "Monday read 292.6.", cite: "T", citeWords: "T, as the chapter now reads" });
  assert.equal(cardQuote(null, true), null);
  assert.equal(cardQuote({ text: "", cite: "T" }, true), null);
});

test("on: a card under a chapter with standing corrections says so; replaced ones are not counted", () => {
  const c = (kind, d, extra = {}) => ({ kind, dated_on: d, superseded_by: null, ...extra });
  assert.equal(cardCorrection([], true), null);
  assert.equal(cardCorrection([c("correction", "2030-02-01", { superseded_by: "x" })], true), null);
  assert.equal(cardCorrection([c("qualification", "2030-02-01")], true), "This chapter carries a dated qualification of 1 February 2030.");
  assert.equal(cardCorrection([c("correction", "2030-02-01"), c("qualification", "2030-02-01")], true), "This chapter carries 2 dated corrections and qualifications of 1 February 2030.");
  assert.equal(cardCorrection([c("correction", "2030-02-01"), c("correction", "2030-02-03")], true), "This chapter carries 2 dated corrections, the newest of 3 February 2030.");
  assert.equal(momentsQuoteWho(true), "a published");
  assert.equal(entryVerb(true), "published");
});

// tests/js/chronicle_text_4191.test.mjs — #4191: the chronicle opens on its first
// sentence, never on the quoted title or the bracketed card-engine stat line that
// posts.json re-embeds at the head of `excerpt`. Fixture = the live 2026-09-25 excerpt.
import "./support/loader.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const { cleanExcerpt, statsRow } = await import("../../site/assets/js/chronicle_text.js");

const LIVE = '"The Silence and the Signal"\n\n[Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days]\n\nOn Monday afternoon, Matthew logged what the platform’s daily brief called the biggest training day of the experiment.';

test("the live excerpt opens on its first sentence", () => {
  const out = cleanExcerpt(LIVE, "The Silence and the Signal");
  assert.ok(out.startsWith("On Monday afternoon"), out.slice(0, 40));
  assert.ok(!out.includes("[Weight:"));
  assert.ok(!out.includes("Silence and the Signal"));
});

test("a quoted first line that is NOT the title is prose and stays", () => {
  const out = cleanExcerpt('"Not the title"\n\nBody.', "The Silence and the Signal");
  assert.equal(out, '"Not the title"\n\nBody.');
});

test("a stat line alone is stripped even without a title match; smart quotes count", () => {
  assert.equal(cleanExcerpt("[Weight: 300 lbs | Week Grade: avg 57 | T0 Streak: 3 days]\nBody.", null), "Body.");
  assert.equal(cleanExcerpt("“The Silence and the Signal”\nBody.", "the silence and the signal"), "Body.");
});

test("mutation control — the raw excerpt (no cleaning) DOES carry the bracket, so the helper is load-bearing", () => {
  assert.ok(LIVE.includes("[Weight:"));
  assert.ok(!cleanExcerpt(LIVE, "The Silence and the Signal").includes("[Weight:"));
});

test("statsRow reads as words, drops the builder-only segment, keeps unknown segments verbatim", () => {
  assert.equal(statsRow("Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days"), "315.0 lb that week · the engine's week score 74");
  assert.equal(statsRow("[Weight: 300 lbs | Sleep: 7.1 h]"), "300 lb that week · Sleep: 7.1 h");
  assert.equal(statsRow(""), "");
  assert.equal(statsRow(null), "");
});

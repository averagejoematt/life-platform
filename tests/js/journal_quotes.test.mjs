// tests/js/journal_quotes.test.mjs — unit tests for the consent-per-line
// pull-quote renderers (#1568, site/assets/js/journal_quotes.js). The honesty
// contract is load-bearing: absent/empty data ⇒ BOTH renderers return "" (the
// surfaces stay dormant — never an empty shell), and a rendered quote is
// verbatim-escaped, dated, labeled as his words, with a receipts link into
// that day's data.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
// Dynamic import (not static): the module lives behind the "/assets/js/…"
// resolver that support/loader.mjs registers — a static import would link
// before registration runs.
const { quotesArchiveHTML, featuredQuoteHTML } = await import("../../site/assets/js/journal_quotes.js");

const Q = { date: "2026-07-21", quote: "I kept the promise today.", marked_at: "2026-07-21T20:00:00Z", receipts: "/cockpit/?date=2026-07-21" };

test("no payload / empty quotes ⇒ the archive renders NOTHING (dormant, no shell)", () => {
  assert.equal(quotesArchiveHTML(null), "");
  assert.equal(quotesArchiveHTML(undefined), "");
  assert.equal(quotesArchiveHTML({}), "");
  assert.equal(quotesArchiveHTML({ quotes: [] }), "");
  assert.equal(quotesArchiveHTML({ quotes: [{ date: "2026-07-21", quote: "   " }] }), "");
});

test("no featured quote ⇒ the home slot renders NOTHING", () => {
  assert.equal(featuredQuoteHTML(null), "");
  assert.equal(featuredQuoteHTML({}), "");
  assert.equal(featuredQuoteHTML({ featured: null }), "");
  assert.equal(featuredQuoteHTML({ featured: { quote: "", date: "2026-07-21" } }), "");
});

test("a quote renders verbatim, dated, labeled, with the receipts link", () => {
  const html = quotesArchiveHTML({ quotes: [Q] });
  assert.match(html, /from the journal, in his words/);
  assert.match(html, /I kept the promise today\./);
  assert.match(html, /July 21, 2026/);
  assert.match(html, /href="\/cockpit\/\?date=2026-07-21"/);
  assert.match(html, /his words, verbatim/);
});

test("quote text is HTML-escaped — a marked line can never inject markup", () => {
  const html = quotesArchiveHTML({ quotes: [{ ...Q, quote: '<script>alert("x")</script> & so on' }] });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&amp; so on/);
});

test("featured renders exactly one card with the weekly framing", () => {
  const html = featuredQuoteHTML({ featured: Q });
  assert.match(html, /from the journal this week, in his words/);
  assert.equal((html.match(/jq-card/g) || []).length, 1);
});

test("a quote missing its date is dropped (no undated verbatim lines)", () => {
  assert.equal(quotesArchiveHTML({ quotes: [{ quote: "no date" }] }), "");
});

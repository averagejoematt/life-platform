// #6193: second editions. The page-level properties (switch off = no edition and no first-edition page; on = only the
// edited chapter page changes and only the approved archival page is added, noindex, canonical, out of the sitemap) are
// held by scripts/check_www_build.py (editions mutation); this file holds the module's own rules.
import { test } from "node:test";
import assert from "node:assert/strict";
import { archivalChapterIds, archivalFor, editionFor, editionReading, notArchivalPage } from "../src/lib/chapter_editions.js";
import { correctionHtml } from "../src/lib/chapter_corrections.js";

const SIG = "Average Joe Matt editorial record";
const edition = (extra = {}) => ({
  chapter_id: "week-04",
  edition: 2,
  edition_line: "Second edition, revised 23 November 2026. First published 11 September 2026.",
  signature: `Second edition, revised 23 November 2026 — ${SIG}`,
  approvals: [{ by: "owner", on: "2026-11-23", via: "x" }],
  carries: ["walk"],
  word_count: 460,
  body_html: "<p>The later text.</p>",
  archival: null,
  ...extra,
});
const archival = { archival_id: 1, approved_on: "2026-11-23", note: "A fixed note.", signature: `Archival rendering, approved 23 November 2026 — ${SIG}`, body_html: "<p>Archived.</p>" };

test("no file, another state, another chapter or anything unsigned: no edition", () => {
  assert.equal(editionFor(null, "week-04"), null);
  assert.equal(editionFor({ state: "absent", editions: [edition()] }, "week-04"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition()] }, "week-05"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition({ signature: "Second edition — Margaret Calloway" })] }, "week-04"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition({ approvals: [] })] }, "week-04"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition({ body_html: " " })] }, "week-04"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition()] }, "week-04").edition, 2);
});

test("an archival page exists only for an approved, platform-signed rendering", () => {
  assert.deepEqual(archivalChapterIds({ state: "ok", editions: [edition()] }), []);
  const doc = { state: "ok", editions: [edition({ archival })] };
  assert.deepEqual(archivalChapterIds(doc), ["week-04"]);
  assert.equal(archivalFor(doc, "week-04").archival_id, 1);
  assert.equal(archivalFor({ state: "ok", editions: [edition({ archival: { ...archival, signature: "Margaret Calloway" } })] }, "week-04"), null);
});

test("the sitemap never lists an archival page; the reading time follows the served text", () => {
  assert.equal(notArchivalPage("https://averagejoematt.com/story/week-04/first-edition/"), false);
  assert.equal(notArchivalPage("https://averagejoematt.com/story/week-04/"), true);
  assert.deepEqual(editionReading(edition()), { word_count: 460, read_minutes: 2 });
});

test("a correction's foot is #6177's sentence without an edition, and says where the edition stands with one", () => {
  const c = { id: "walk", chapter_id: "week-04", kind: "correction", dated_on: "2026-11-20", signature: `Correction, 20 November 2026 — ${SIG}`, published_said: "a", record_shows: "b", evidence: "c", approvals: [{ by: "owner", on: "2026-11-20" }], superseded_by: null };
  assert.match(correctionHtml(c), /This note does not change the chapter's text\./); // committed ON (#6177 activation; off = footLine(false))
  assert.match(correctionHtml(c, [c], edition()), /a later edition, and it makes this correction\./);
  assert.match(correctionHtml({ ...c, id: "other" }, [c], edition()), /made to the first edition; the text below is a later edition\./);
});

test("an approved quotation the body already carries is not placed beside it again (final approval §4)", async () => {
  const { bodyCarriesQuote } = await import("../src/lib/own_words.js");
  const quote = "A sample approved line, for a test, about the pace.";
  assert.equal(bodyCarriesQuote(`<p>He wrote: “A sample approved line, for a test, about the pace.”</p>`, quote), true);
  assert.equal(bodyCarriesQuote(`<p>He wrote: <em>A sample approved line,</em> for a test, about the pace.</p>`, quote), true);
  assert.equal(bodyCarriesQuote(`<p>A sample approved line, for a test, about the speed.</p>`, quote), false); // not word for word
  assert.equal(bodyCarriesQuote(`<p>Anything.</p>`, ""), false);
});

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
  title: "A Sample Chapter",
  summary: "The edition's own summary.",
  revised_on: "2026-11-23",
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

test("#6193 B4: an edition without its own title and summary is not served at all", () => {
  assert.equal(editionFor({ state: "ok", editions: [edition({ summary: "" })] }, "week-04"), null);
  assert.equal(editionFor({ state: "ok", editions: [edition({ title: undefined })] }, "week-04"), null);
});

test("#6193 B4: ONE rule for which summary every surface shows — the edition's, then #6177's, then the served one", async () => {
  const { applyChapterSummaries, cardQuote } = await import("../src/lib/chapter_truth.js");
  const { editionOrdinal } = await import("../src/lib/chapter_editions.js");
  const doc = { state: "ok", editions: [edition()] };
  const table = { revised_on: "2026-11-22", headers: { "week-04": { replaces: "First", text: "A replacement." }, "week-05": { replaces: "First", text: "A replacement." } } };
  const chapters = [
    { id: "week-04", status: "published", excerpt: "First edition summary.", title: "A Sample Chapter" },
    { id: "week-05", status: "published", excerpt: "First edition summary.", title: "Another" },
    { id: "week-06", status: "published", excerpt: "Untouched.", title: "Third" },
  ];
  const done = applyChapterSummaries(chapters, (id) => editionFor(doc, id), true, table, editionOrdinal);
  assert.deepEqual(done.sort(), ["week-04", "week-05"]);
  assert.equal(chapters[0].excerpt, "The edition's own summary.");
  assert.equal(chapters[0].summary, "The edition's own summary.");
  assert.equal(chapters[0].excerpt_first, "First edition summary.");
  assert.equal(chapters[0].header_revised_on, undefined); // never the replacement over an edition
  assert.equal(chapters[1].excerpt, "A replacement.");
  assert.equal(chapters[2].excerpt, "Untouched.");
  // switch-off identity: no edition file and #6177 off = nothing changes
  const off = [{ id: "week-04", status: "published", excerpt: "First edition summary." }];
  assert.deepEqual(applyChapterSummaries(off, () => null, false, table, editionOrdinal), []);
  assert.deepEqual(off, [{ id: "week-04", status: "published", excerpt: "First edition summary." }]);
  // a Moments card quoting it says which edition, never "as published"
  const q = cardQuote({ text: chapters[0].excerpt, cite: "A Sample Chapter" }, false, chapters[0]);
  assert.equal(q.citeWords, "A Sample Chapter, second edition, revised 23 November 2026");
});

test("#6193 B6: the archival page's correction foot says the text below is the superseded rendering", async () => {
  const { ARCHIVAL_PAGE } = await import("../src/lib/chapter_corrections.js");
  const c = { id: "walk", chapter_id: "week-04", kind: "correction", dated_on: "2026-11-20", signature: `Correction, 20 November 2026 — ${SIG}`, published_said: "a", record_shows: "b", evidence: "c", approvals: [{ by: "owner", on: "2026-11-20" }], superseded_by: null };
  assert.match(correctionHtml(c, [c], ARCHIVAL_PAGE), /an archival rendering of it, superseded by the current edition\./);
  assert.match(correctionHtml(c, [c], ARCHIVAL_PAGE), /correction-signature">Correction, 20 November 2026 — Average Joe Matt editorial record/);
});

test("#6193 B6: the archival page names a later rewrite's day, never 'first edition'", async () => {
  const { archivalWhat } = await import("../src/lib/chapter_editions.js");
  assert.equal(archivalWhat({ as_of: "2026-10-25" }), "as it stood on 25 October 2026");
  assert.equal(archivalWhat({ as_of: null }), "first edition");
});

test("the body printer is shared by the chapter and archival pages, unchanged", async () => {
  const { bodyForPage } = await import("../src/lib/chapter_body.js");
  const html = `<p class="signature"><em>Editor's note, October 2026 — x</em></p>\n<p class="signature"><em>Day 3 · 1 lb</em></p>\n<p>Prose.</p>`;
  assert.equal(bodyForPage(html, null), `<p class="signature note"><em>Editor's note, October 2026 — x</em></p>\n<p class="signature filed"><em>Day 3 · 1 lb</em></p>\n<p>Prose.</p>`);
  assert.equal(bodyForPage("<p>The dek.</p>\n<p>Prose.</p>", "The dek."), "\n<p>Prose.</p>");
});

test("#6193 rehearsal §4: an anchored correction stands directly after its passage, signed by the platform; the rest stay above", async () => {
  const { ARCHIVAL_PAGE, placeBeside } = await import("../src/lib/chapter_corrections.js");
  const c = (id) => ({ id, chapter_id: "week-04", kind: "correction", dated_on: "2026-11-22", signature: `Correction, 22 November 2026 — ${SIG}`, published_said: "a", record_shows: "b", evidence: "c", approvals: [{ by: "owner", on: "2026-11-22" }], superseded_by: null });
  const body = "<p>A first paragraph of a synthetic archive.</p>\n<p>Day 9 was a sample day of the test. More words.</p>\n<p>A last paragraph.</p>";
  const out = placeBeside(body, [{ correction_id: "one", passage: "Day 9 was a sample day" }, { correction_id: "two", passage: "not in the text anywhere" }], [c("one"), c("two")], ARCHIVAL_PAGE);
  assert.deepEqual(out.placed, ["one"]);
  const at = out.html.indexOf("data-anchored");
  assert.ok(at > out.html.indexOf("More words.</p>") && at < out.html.indexOf("A last paragraph"));
  assert.match(out.html, /correction-signature">Correction, 22 November 2026 — Average Joe Matt editorial record/);
  assert.match(out.html, /concerns the passage above, beginning “Day 9 was a sample day”/);
  // a passage in two paragraphs is ambiguous: not placed
  const twice = placeBeside(body + "\n<p>Day 9 was a sample day again.</p>", [{ correction_id: "one", passage: "Day 9 was a sample day" }], [c("one")]);
  assert.deepEqual(twice.placed, []);
});

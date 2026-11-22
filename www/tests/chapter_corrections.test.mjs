// #6177: dated public corrections sit BESIDE a chapter, platform-signed and approved; a Margaret-signed historical note
// renders with the one disclosure line. The byte-identical-body property of the built pages is held by
// scripts/check_www_build.py (corrections mutation); this file holds the module and the built fixture pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PERSONA_DISCLOSURE, correctionHtml, correctionsFor, correctionsHtml, namesLegacyPersona, rowMark } from "../src/lib/chapter_corrections.js";

const sig = (kind, day) => `${kind === "qualification" ? "Qualification" : "Correction"}, ${day} — Average Joe Matt editorial record`;
const c = (id, dated_on, extra = {}) => ({
  id,
  chapter_id: "week-09",
  kind: "correction",
  dated_on,
  signature: sig("correction", "a day"),
  published_said: "It said <seven> miles.",
  record_shows: "Five miles.",
  evidence: "The walking log.",
  approvals: [{ by: "owner", on: dated_on, via: "x" }],
  supersedes: null,
  superseded_by: null,
  ...extra,
});
const doc = (rows) => ({ state: "ok", corrections: rows });

test("a chapter's corrections: standing ones newest first, then the replaced; other chapters and unsigned ones never", () => {
  const rows = [
    c("a", "2026-11-20", { superseded_by: "b" }),
    c("b", "2026-11-22", { supersedes: "a" }),
    c("x", "2026-11-23", { chapter_id: "week-08" }),
    c("persona", "2026-11-24", { signature: "Correction, 24 November 2026 — Margaret Calloway" }),
    c("unapproved", "2026-11-25", { approvals: [] }),
  ];
  assert.deepEqual(
    correctionsFor(doc(rows), "week-09").map((r) => r.id),
    ["b", "a"],
  );
  assert.deepEqual(correctionsFor({ state: "absent", corrections: rows }, "week-09"), []);
  assert.deepEqual(correctionsFor(null, "week-09"), []);
});

test("the story row's mark names the newest standing correction, in words", () => {
  assert.equal(rowMark([c("b", "2026-11-22")]), "corrected 22 Nov");
  assert.equal(rowMark([c("q", "2026-11-03", { kind: "qualification" })]), "qualified 3 Nov");
  assert.equal(rowMark([c("a", "2026-11-20", { superseded_by: "b" })]), null);
  assert.equal(rowMark([]), null);
});

test("a correction block escapes every value, names its approval and, when replaced, what replaced it", () => {
  const b = c("b", "2026-11-22", { kind: "qualification", signature: sig("qualification", "22 November 2026") });
  const a = c("a", "2026-11-20", { superseded_by: "b" });
  const html = correctionHtml(a, [b, a]);
  assert.ok(html.includes("It said &lt;seven&gt; miles."));
  assert.ok(!html.includes("<seven>"));
  assert.ok(html.includes("Approved by Matthew on 20 November 2026"));
  assert.ok(html.includes("Replaced by the qualification of 22 November 2026"));
  assert.ok(!/\d{4}-\d{2}-\d{2}/.test(correctionsHtml([b, a])), "dates in words only");
});

test("the disclosure is one plain line and is triggered only by the legacy signer", () => {
  assert.equal(PERSONA_DISCLOSURE, "Margaret Calloway is an AI editorial persona of the platform, not a person.");
  assert.ok(namesLegacyPersona("<p class=\"signature\"><em>Editor's note, October 2026 — Margaret Calloway: …</em></p>"));
  assert.ok(!namesLegacyPersona("<p>Elena Voss wrote this.</p>"));
  assert.ok(!namesLegacyPersona(null));
});

// ── the built fixture pages (CI: the fixture build scripts/check_www_build.py leaves in www/dist) ─────────────────
const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.CORRECTIONS_DIST || join(WWW, "dist"));
const page = (rel) => {
  for (const base of ["", "next/v9"]) {
    const p = join(DIST, base, rel, "index.html");
    if (existsSync(p)) return readFileSync(p, "utf8");
  }
  return null;
};
const HAVE = page("story/week-06") !== null;

test("built pages: the corrections sit outside the published body, the disclosure beside the note, the row marked", { skip: HAVE ? false : `no built dist at ${DIST}` }, () => {
  const ch = page("story/week-06");
  const body = ch.indexOf("<div data-published-body>");
  const block = ch.indexOf("data-chapter-corrections");
  const disclosure = ch.indexOf("data-persona-disclosure");
  assert.ok(block > 0 && block < body, "the corrections render before the body, not in it");
  assert.ok(disclosure > block && disclosure < body, "the disclosure sits directly above the body that carries the note");
  assert.ok(ch.includes(PERSONA_DISCLOSURE));
  assert.ok(!ch.includes("SENTINEL-UNAPPROVED"), "an unapproved proposal never renders");
  const story = page("story");
  assert.ok(story.includes("data-corrected"), "the story list marks the corrected chapter");
  assert.ok(story.includes(PERSONA_DISCLOSURE), "the page that says who writes the chapters carries the disclosure");
});

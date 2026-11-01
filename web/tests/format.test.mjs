import assert from "node:assert/strict";
import { test } from "node:test";

import { clip, dayInWords, kOfN, num } from "../src/lib/format.js";
import { href, pathOf, PATH_OF } from "../src/lib/url.js";
import { COLLECTION_OF } from "../src/lib/edges.js";

test("dates are written in words, never ISO", () => {
  assert.equal(dayInWords("2026-10-31"), "31 October 2026");
  assert.equal(dayInWords("2026-10-31", { short: true }), "31 Oct");
  assert.equal(dayInWords("2026-10-31", { short: true, weekday: true }), "Saturday 31 Oct");
  assert.equal(dayInWords(null), null);
  assert.equal(dayInWords("not a date"), null);
});

test("numbers: fixed decimals, en-GB grouping, a dash for nothing", () => {
  assert.equal(num(19730), "19,730");
  assert.equal(num(296.64, 1), "296.6");
  assert.equal(num(null), "—");
  assert.equal(num(Number.NaN), "—");
});

test("the record is K of N, and never a bare percentage", () => {
  assert.equal(kOfN(19, 48), "19 of 48 right");
  assert.equal(kOfN(null, 48), "48 checked");
  assert.equal(kOfN(0, 0), "no checked call yet");
  assert.doesNotMatch(kOfN(19, 48), /%/);
});

test("clip cuts on a word and marks the cut", () => {
  const s = "Deep sleep percentage would rise as zone-2 training volume built, driven by adenosine";
  const c = clip(s, 40);
  assert.ok(c.length <= 40);
  assert.ok(c.endsWith("…"));
  assert.ok(!c.includes("  "));
  assert.equal(clip("short", 40), "short");
});

test("href joins the base path without doubling slashes", () => {
  assert.equal(href("/story/", "/"), "/story/");
  assert.equal(href("/story/", "/next/v9/"), "/next/v9/story/");
  assert.equal(href("story/", "/next/v9"), "/next/v9/story/");
});

test("every object type has a canonical path, directory-style, and episodes resolve to their chapter", () => {
  for (const t of Object.keys(COLLECTION_OF)) {
    assert.ok(PATH_OF[t], `no path for ${t}`);
    const p = pathOf(t, "x1");
    assert.ok(p.startsWith("/") && p.endsWith("/"), `${t}: ${p}`);
  }
  assert.equal(pathOf("episode", "wk8", { chapter_id: "week-08" }), "/story/week-08/#listen");
  assert.throws(() => pathOf("nope", "x"), /no canonical path/);
});

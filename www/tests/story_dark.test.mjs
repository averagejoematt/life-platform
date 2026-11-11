// The Human Story is built dark (HS1, src/lib/story_dark.js): with WEB_STORY off it is ABSENT from the artifact, not
// merely unlinked. Two halves, the same as the Coaching Room's (tests/room.test.mjs):
//   * the switch itself — the helper, the route injection, where the story's files live, the sitemap filter;
//   * the flag-off dist — six checks from scripts/story_audit.mjs, each run on the real build (CI: the fixture build
//     scripts/check_www_build.py leaves in www/dist; elsewhere STORY_AUDIT_DIST) AND on a planted copy, where it must
//     find the leak it exists to find (the mutation control: a check that cannot fail is not a check).
// The master proof stays the byte-identical recursive diff of this tree's flag-off dist against main's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { STORY_DATA_FILE, STORY_ENV, STORY_LIVE, STORY_MARKER, STORY_ROUTES, notStoryPage, storyEnabled, storyIntegration, storyPrivate } from "../src/lib/story_dark.js";
import { ROOM_ENV, roomEnabled } from "../src/lib/room.js";
import { feeds, gatedPaths, jsonFiles, orphanChunks, ownedPaths, sitemaps } from "../scripts/story_audit.mjs";
import { walk } from "../scripts/room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.STORY_AUDIT_DIST || join(WWW, "dist"));
const HAVE_DIST = existsSync(join(DIST, "index.html"));
const STORY_PATH = STORY_ROUTES[0].path; // "/story/so-far/" (never /story/timeline/: the kept v8 page)

function plantedCopy() {
  const dir = mkdtempSync(join(tmpdir(), "story-audit-"));
  cpSync(DIST, dir, { recursive: true });
  return dir;
}

// ── the switch ──────────────────────────────────────────────────────────────────────────────────────────────────
test("only the literal WEB_STORY=1 turns the story on, and it is a separate switch from the room", () => {
  assert.equal(STORY_ENV, "WEB_STORY");
  assert.notEqual(STORY_ENV, ROOM_ENV);
  assert.equal(storyEnabled({}, false), false);
  for (const v of ["", "0", "true", "yes", " 1", "1 "]) assert.equal(storyEnabled({ WEB_STORY: v }, false), false, `WEB_STORY=${JSON.stringify(v)}`);
  assert.equal(storyEnabled({ WEB_STORY: "1" }, false), true);
  assert.equal(storyEnabled({ WEB_ROOM: "1" }, false), false, "the room's switch does not turn the story on");
  assert.equal(roomEnabled({ WEB_STORY: "1" }, "off"), false, "the story's switch does not turn the room on");
});

test("switch off: the integration injects no route (control: switch on injects every story route)", () => {
  const off = [];
  storyIntegration({}, false).hooks["astro:config:setup"]({ injectRoute: (r) => off.push(r) });
  assert.deepEqual(off, []);
  const on = [];
  storyIntegration({ WEB_STORY: "1" }, false).hooks["astro:config:setup"]({ injectRoute: (r) => on.push(r) });
  assert.deepEqual(
    on.map((r) => r.pattern),
    STORY_ROUTES.map((r) => r.pattern),
    "the control: with the switch on the integration must inject — otherwise the off case proves nothing"
  );
});

test("the story's pages live outside src/pages (no static route, no page imports one); the one entry on /story/ is self-gating", () => {
  const pages = walk(join(WWW, "src", "pages")).map((p) => readFileSync(p, "utf8"));
  for (const r of STORY_ROUTES) {
    assert.ok(existsSync(join(WWW, r.entrypoint)), `${r.entrypoint} exists`);
    assert.ok(!r.entrypoint.includes("src/pages/"), `${r.entrypoint} must not sit under src/pages/`);
    assert.ok(!existsSync(join(WWW, "src", "pages", r.path, "index.astro")) && !existsSync(join(WWW, "src", "pages", `${r.path.slice(0, -1)}.astro`)));
  }
  assert.ok(!pages.some((t) => /from\s+["'][./]*\.\.\/story\//.test(t) || t.includes("src/story/")), "no page imports a story page");
  const entry = readFileSync(join(WWW, "src", "components", "StoryEntry.astro"), "utf8");
  assert.match(entry, /const on = storyEnabled\(\);/);
  assert.match(entry, /on \? soFar\(await loadStory\(\)/, "the data file is read only when the switch is on");
  assert.match(entry, /on && \(/);
  const markup = entry.split(/^---$/m).slice(2).join("---"); // the template after the frontmatter
  assert.ok(markup.length > 0 && !/<\s*(style|script)\b/i.test(markup), "the entry adds no asset");
});

test("the sitemap filter drops every story path and keeps everything else", () => {
  for (const r of STORY_ROUTES) {
    assert.equal(notStoryPage(`https://averagejoematt.com${r.path}`, false), false);
    assert.equal(notStoryPage(`https://averagejoematt.com/next/v9${r.path}`, false), false);
  }
  for (const u of ["https://averagejoematt.com/", "https://averagejoematt.com/story/", "https://averagejoematt.com/story/week-04/", "https://averagejoematt.com/story/essays/x/"])
    assert.equal(notStoryPage(u, false), true, u);
});

// ── the flag-off dist: six checks, each with its own planted control ──────────────────────────────────────────────
const distTest = (name, fn) =>
  test(name, { skip: STORY_LIVE ? "the story is committed live (STORY_LIVE): the flag-off proofs do not apply" : HAVE_DIST ? false : `no built dist at ${DIST} — run the flag-off build first (CI: check_www_build.py)` }, fn);

distTest("1 · every story path and the data file is a 404 on direct request (control: a planted page answers 200)", async () => {
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    mkdirSync(join(dir, STORY_PATH), { recursive: true });
    writeFileSync(join(dir, STORY_PATH, "index.html"), "<!doctype html><p>planted</p>");
    writeFileSync(join(dir, STORY_DATA_FILE), "{}");
    const leaks = await gatedPaths(dir);
    assert.ok(leaks.some((l) => l.startsWith(STORY_PATH) && l.includes("200")), `the planted page must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.startsWith(`/${STORY_DATA_FILE}`)), `the planted data file must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("2 · no new JSON or API-shaped file, no story-only key (control: a planted story.json and a planted key)", () => {
  assert.deepEqual(jsonFiles(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "story", STORY_DATA_FILE), JSON.stringify({ ok: true }));
    const pairs = join(dir, "data", "pairs.json");
    const declaredOne = existsSync(pairs);
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, '{"installments_index":[],'));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l.startsWith(`story/${STORY_DATA_FILE}: a JSON file`)), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) assert.ok(leaks.some((l) => l.includes('"installments_index"')), `a story key in a declared file must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("3 · no sitemap lists a story path (control: a planted <loc>)", () => {
  assert.deepEqual(sitemaps(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>https://averagejoematt.com${STORY_PATH}</loc></url></urlset>`);
    assert.ok(sitemaps(dir).length > 0, "the control must red");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("4 · no feed or search index, and nothing machine-readable names a story path (control: a planted feed)", () => {
  assert.deepEqual(feeds(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "feed.xml"), `<rss><item><link>https://averagejoematt.com${STORY_PATH}</link></item></rss>`);
    const leaks = feeds(dir);
    assert.ok(leaks.some((l) => l.startsWith("feed.xml: a feed")) && leaks.some((l) => l.includes("names a story path")), `the control must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("5 · the committed owned_paths.json names no story path (control: a planted route and data file)", { skip: STORY_LIVE ? "the story is committed live" : false }, () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.deepEqual(ownedPaths(owned), []);
  const planted = { ...owned, routes: [...owned.routes, STORY_PATH], static_routes: [...owned.static_routes, STORY_PATH], files: [...owned.files, STORY_DATA_FILE] };
  assert.ok(ownedPaths(planted).length >= 3, `the control must red: ${ownedPaths(planted)}`);
});

distTest("6 · no CSS/JS chunk exists only for a gated page, no story-named asset, no marker (control: an orphan chunk + a marker)", () => {
  assert.deepEqual(orphanChunks(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "_astro", "timeline.Zz9PLANT.js"), "export const x = 1;");
    const page = join(dir, "story", "index.html");
    writeFileSync(page, readFileSync(page, "utf8").replace("<main", `<main ${STORY_MARKER}="entry"`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes("no built page reaches")), `an orphan chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("named for the story")), `a story-named asset must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("story marker")), `the story marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("the flag-off dist holds no story route directory and no story data file at all", () => {
  for (const r of STORY_ROUTES) assert.ok(!existsSync(join(DIST, r.path)), `${r.path} must not exist in a flag-off dist (was this dist built with WEB_STORY=1?)`);
  assert.ok(!walk(DIST).some((p) => p.endsWith(`/${STORY_DATA_FILE}`)));
});

// ── the route collision (2026-11-09) and the go-live switch ─────────────────────────────────────────────────────────
test("no story route is the established /story/timeline/ (the kept v8 page, deployed from site/) — nor any kept site/ page", () => {
  const SITE = join(WWW, "..", "site");
  assert.ok(existsSync(join(SITE, "story", "timeline", "index.html")), "the control: the kept page this guards is still in site/");
  for (const r of STORY_ROUTES) {
    assert.notEqual(r.path, "/story/timeline/");
    assert.ok(!existsSync(join(SITE, r.path, "index.html")), `${r.path} would land on site${r.path}index.html`);
  }
  assert.ok(!STORY_ROUTES.some((r) => r.path === "/story/episodes/"), "the episode index is folded into the timeline");
});

test("the go-live constant is one literal line, false until the owner's go (feat/story-go-live flips it)", () => {
  const src = readFileSync(join(WWW, "src", "lib", "story_dark.js"), "utf8");
  assert.equal((src.match(/^export const STORY_LIVE = (true|false);$/gm) || []).length, 1, "scripts/www_launch_switch.py reads exactly this one line");
  assert.equal(typeof STORY_LIVE, "boolean");
});

test("live: the story is on with no env, kept in the sitemap, never a private build (control: dark)", () => {
  assert.equal(storyEnabled({}, true), true);
  assert.equal(storyPrivate({ WEB_STORY: "1" }, true), false);
  assert.equal(storyPrivate({ WEB_STORY: "1" }, false), true, "the control: dark + env switch IS the private build");
  for (const r of STORY_ROUTES) assert.equal(notStoryPage(`https://averagejoematt.com${r.path}`, true), true);
  const on = [];
  storyIntegration({}, true).hooks["astro:config:setup"]({ injectRoute: (r) => on.push(r.pattern) });
  assert.deepEqual(on, STORY_ROUTES.map((r) => r.pattern));
});

test("live dist: the timeline is built, owned and public — no private label", { skip: !STORY_LIVE ? "the story is dark (STORY_LIVE false)" : !HAVE_DIST ? "no built dist" : false }, () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.ok(owned.routes.includes(STORY_PATH) && owned.static_routes.includes(STORY_PATH), "owned_paths.json owns the timeline");
  const html = readFileSync(join(DIST, STORY_PATH, "index.html"), "utf8");
  assert.ok(!html.includes("private build"));
  assert.ok(!readFileSync(join(DIST, "story", "index.html"), "utf8").includes("private build"));
});

// The Coaching Room is built dark (CR1, src/lib/room.js): with WEB_ROOM off it is ABSENT from the artifact, not
// merely unlinked. Two halves:
//   * the switch itself — the helper, the route injection, where the room's files live, the sitemap filter;
//   * the flag-off dist — six checks from scripts/room_audit.mjs, each run on the real build (CI: the fixture build
//     scripts/check_www_build.py leaves in www/dist; elsewhere ROOM_AUDIT_DIST) AND on a planted copy, where it must
//     find the leak it exists to find (the mutation control: a check that cannot fail is not a check).
// The master proof stays the byte-identical recursive diff of this tree's flag-off dist against main's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ROOM_ENV, ROOM_MARKER, ROOM_ROUTES, notRoomPage, roomEnabled, roomIntegration } from "../src/lib/room.js";
import { feeds, gatedPaths, jsonFiles, orphanChunks, ownedPaths, sitemaps, walk } from "../scripts/room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.ROOM_AUDIT_DIST || join(WWW, "dist"));
const HAVE_DIST = existsSync(join(DIST, "index.html"));
const ROOM_PATH = ROOM_ROUTES[0].path; // "/system/calibration/"

/** A throwaway copy of the dist to plant a leak in. */
function plantedCopy() {
  const dir = mkdtempSync(join(tmpdir(), "room-audit-"));
  cpSync(DIST, dir, { recursive: true });
  return dir;
}

// ── the switch ──────────────────────────────────────────────────────────────────────────────────────────────────
test("only the literal WEB_ROOM=1 turns the room on", () => {
  assert.equal(ROOM_ENV, "WEB_ROOM");
  assert.equal(roomEnabled({}), false);
  for (const v of ["", "0", "true", "yes", " 1", "1 "]) assert.equal(roomEnabled({ WEB_ROOM: v }), false, `WEB_ROOM=${JSON.stringify(v)}`);
  assert.equal(roomEnabled({ WEB_ROOM: "1" }), true);
});

test("switch off: the integration injects no route (control: switch on injects every room route)", () => {
  const off = [];
  roomIntegration({}).hooks["astro:config:setup"]({ injectRoute: (r) => off.push(r) });
  assert.deepEqual(off, []);
  const on = [];
  roomIntegration({ WEB_ROOM: "1" }).hooks["astro:config:setup"]({ injectRoute: (r) => on.push(r) });
  assert.deepEqual(
    on.map((r) => r.pattern),
    ROOM_ROUTES.map((r) => r.pattern),
    "the control: with the switch on the integration must inject — otherwise the off case proves nothing"
  );
});

test("the room's pages live outside src/pages (no static route, no route pattern, no postbuild census entry)", () => {
  const pages = walk(join(WWW, "src", "pages")).map((p) => readFileSync(p, "utf8"));
  for (const r of ROOM_ROUTES) {
    assert.ok(existsSync(join(WWW, r.entrypoint)), `${r.entrypoint} exists`);
    assert.ok(!r.entrypoint.includes("src/pages/"), `${r.entrypoint} must not sit under src/pages/`);
  }
  assert.ok(!pages.some((t) => /from\s+["'][./]*\.\.\/room\//.test(t) || t.includes("src/room/")), "no page imports a room page");
  // the one component a page renders is self-gating
  const entry = readFileSync(join(WWW, "src", "components", "RoomEntry.astro"), "utf8");
  assert.match(entry, /const on = roomEnabled\(\);/);
  assert.match(entry, /on && \(/);
});

test("the sitemap filter drops every room path and keeps everything else", () => {
  assert.equal(notRoomPage("https://averagejoematt.com/system/calibration/"), false);
  assert.equal(notRoomPage("https://averagejoematt.com/next/v9/system/calibration/"), false);
  for (const u of ["https://averagejoematt.com/", "https://averagejoematt.com/system/", "https://averagejoematt.com/system/ledger/"]) assert.equal(notRoomPage(u), true, u);
});

// ── the flag-off dist: six checks, each with its own planted control ──────────────────────────────────────────────
const distTest = (name, fn) => test(name, { skip: HAVE_DIST ? false : `no built dist at ${DIST} — run the flag-off build first (CI: check_www_build.py)` }, fn);

distTest("1 · every room path is a 404 on direct request (control: a planted page answers 200)", async () => {
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    mkdirSync(join(dir, ROOM_PATH), { recursive: true });
    writeFileSync(join(dir, ROOM_PATH, "index.html"), "<!doctype html><p>planted</p>");
    const leaks = await gatedPaths(dir);
    assert.ok(leaks.some((l) => l.includes("200")), `the control must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("2 · no new JSON or API-shaped file, no room-only key (control: a planted calibration.json and a planted key)", () => {
  assert.deepEqual(jsonFiles(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "system", "calibration.json"), JSON.stringify({ ok: true }));
    const pairs = join(dir, "data", "pairs.json");
    const declaredOne = existsSync(pairs);
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, '{"prereg_seal":1,'));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l.startsWith("system/calibration.json: a JSON file")), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) assert.ok(leaks.some((l) => l.includes('"prereg_seal"')), `a room key in a declared file must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("3 · no sitemap lists a room path (control: a planted <loc>)", () => {
  assert.deepEqual(sitemaps(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>https://averagejoematt.com${ROOM_PATH}</loc></url></urlset>`);
    assert.ok(sitemaps(dir).length > 0, "the control must red");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("4 · no feed or search index, and nothing machine-readable names a room path (control: a planted feed)", () => {
  assert.deepEqual(feeds(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "feed.xml"), `<rss><item><link>https://averagejoematt.com${ROOM_PATH}</link></item></rss>`);
    const leaks = feeds(dir);
    assert.ok(leaks.some((l) => l.startsWith("feed.xml: a feed")) && leaks.some((l) => l.includes("names a room path")), `the control must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("5 · the committed owned_paths.json names no room path (control: a planted route)", () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.deepEqual(ownedPaths(owned), []);
  const planted = { ...owned, routes: [...owned.routes, ROOM_PATH], static_routes: [...owned.static_routes, ROOM_PATH] };
  assert.ok(ownedPaths(planted).length >= 2, "the control must red");
});

distTest("6 · no CSS/JS chunk exists only for a gated page, no room marker on any page (control: an orphan chunk + a marker)", () => {
  assert.deepEqual(orphanChunks(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "_astro", "calibration.Zz9PLANT.js"), "export const x = 1;");
    const sys = join(dir, "system", "index.html");
    writeFileSync(sys, readFileSync(sys, "utf8").replace("<main", `<main ${ROOM_MARKER}="entry"`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes("no built page reaches")), `an orphan chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("named for the room")), `a room-named asset must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("room marker")), `the room marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("the flag-off dist holds no room route directory at all", () => {
  for (const r of ROOM_ROUTES) assert.ok(!existsSync(join(DIST, r.path)), `${r.path} must not exist in a flag-off dist (was this dist built with WEB_ROOM=1?)`);
  assert.ok(!readdirSync(DIST).includes("calibration.json"));
});

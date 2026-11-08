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

import { ROOM_DATA_FILES, ROOM_ENV, ROOM_MARKER, ROOM_ROUTES, isRoomPath, notRoomPage, roomEnabled, roomIntegration, roomPathPattern } from "../src/lib/room.js";
import { feeds, gatedPaths, jsonFiles, orphanChunks, ownedPaths, roomPaths, sitemaps, walk } from "../scripts/room_audit.mjs";

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
  for (const p of roomPaths(DIST)) assert.ok(!existsSync(join(DIST, p)), `${p} must not exist in a flag-off dist (was this dist built with WEB_ROOM=1?)`);
  for (const f of ROOM_DATA_FILES) assert.ok(!walk(DIST).some((x) => x.endsWith(`/${f}`)), `${f} must not be in a flag-off dist`);
});

// ── CR2: the per-coach record (/system/coaches/<id>/record/) and the entry on each coach page ──────────────────────
const RECORD = ROOM_ROUTES.find((r) => r.entrypoint.endsWith("coach-record.astro"));
/** A coach id the flag-off dist has a page for (the planted record sits beside a real coach page). */
const someCoach = () => readdirSync(join(DIST, "system", "coaches")).find((d) => existsSync(join(DIST, "system", "coaches", d, "index.html")));

test("CR2 · a [param] room path matches exactly one segment, literally elsewhere (control: a near miss does not match)", () => {
  assert.ok(RECORD, "the per-coach record is a room route");
  assert.equal(RECORD.path, "/system/coaches/[id]/record/");
  for (const p of ["/system/coaches/sleep_coach/record/", "/next/v9/system/coaches/eli_marsh/record/"]) assert.equal(isRoomPath(p), true, p);
  for (const p of ["/system/coaches/sleep_coach/", "/system/coaches/a/b/record/", "/system/coaches//record/", "/system/coachesX/sleep_coach/record/"]) assert.equal(isRoomPath(p), false, p);
  // every metacharacter is escaped, backslash included: a pattern built from a path matches only that path
  const rx = new RegExp(`^${roomPathPattern("/a.b+c(d)\\e/[x]/")}$`);
  assert.equal(rx.test("/a.b+c(d)\\e/one/"), true);
  assert.equal(rx.test("/aXb+c(d)\\e/one/"), false, "an unescaped dot would match any character");
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/record/"), false);
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/"), true);
});

test("CR2 · the coach page's entry is self-gating and the record page refuses to render with the switch off", () => {
  const page = readFileSync(join(WWW, "src", "pages", "system", "coaches", "[id].astro"), "utf8");
  assert.match(page, /import CoachRoomEntry from "..\/..\/..\/components\/CoachRoomEntry.astro"/);
  assert.match(page, /<\/section>\{\/\*[^]*?\*\/\}<CoachRoomEntry coach=\{c\} \/>\n<\/Base>/, "the entry sits flush, so the flag-off bytes do not move");
  const entry = readFileSync(join(WWW, "src", "components", "CoachRoomEntry.astro"), "utf8");
  assert.match(entry, /const on = roomEnabled\(\);/);
  assert.match(entry, /on && \(/);
  assert.match(entry, /const entry = on \? /, "the room's data file is read only when the switch is on");
  assert.doesNotMatch(entry.split("\n---\n")[1], /<style|<script/, "the entry's template adds no asset");
  const record = readFileSync(join(WWW, RECORD.entrypoint), "utf8");
  assert.match(record, /if \(!roomEnabled\(\)\) throw new Error/);
});

distTest("CR2 · 1 · every coach's record path is a 404 (control: a planted record page answers 200)", async () => {
  const probes = roomPaths(DIST).filter((p) => p.endsWith("/record/"));
  assert.ok(probes.length >= 2, `the audit expands [id] over the dist's coach pages: ${probes}`);
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    const id = someCoach();
    mkdirSync(join(dir, "system", "coaches", id, "record"), { recursive: true });
    writeFileSync(join(dir, "system", "coaches", id, "record", "index.html"), "<!doctype html><p>planted</p>");
    const leaks = await gatedPaths(dir);
    assert.ok(leaks.some((l) => l.includes(`/system/coaches/${id}/record/`) && l.includes("200")), `the control must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR2 · 2 · no coach_room.json, no CR2 room key (control: a planted file and a planted key)", () => {
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "coach_room.json"), JSON.stringify({ ok: true }));
    const pairs = join(dir, "data", "pairs.json");
    const declaredOne = existsSync(pairs);
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, '{"stance_history":[],"commitment_counts":{},'));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l.startsWith("coach_room.json: a JSON file")), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) {
      assert.ok(leaks.some((l) => l.includes('"stance_history"')), `a CR2 key must red: ${leaks}`);
      assert.ok(leaks.some((l) => l.includes('"commitment_counts"')), `a CR2 key must red: ${leaks}`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR2 · 3+4 · no sitemap or feed names a record path (control: a planted <loc> and a planted feed)", () => {
  const dir = plantedCopy();
  try {
    const loc = `https://averagejoematt.com/system/coaches/${someCoach()}/record/`;
    writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>${loc}</loc></url></urlset>`);
    assert.ok(sitemaps(dir).length > 0, "a record <loc> must red the sitemap check");
    writeFileSync(join(dir, "feed.xml"), `<rss><item><link>${loc}</link></item></rss>`);
    assert.ok(feeds(dir).some((l) => l.includes("names a room path")), "a record link in a feed must red");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("CR2 · 5 · owned_paths.json names no record path (control: a planted record route; the coach pattern itself stays clean)", () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.ok((owned.route_patterns || []).includes("/system/coaches/*/"), "the existing coach pattern is present — and must not be read as a room path");
  assert.deepEqual(ownedPaths(owned), []);
  const planted = { ...owned, routes: [...owned.routes, "/system/coaches/sleep_coach/record/"], files: [...owned.files, "system/coaches/sleep_coach/record/index.html"] };
  assert.ok(ownedPaths(planted).length >= 2, `the control must red: ${ownedPaths(planted)}`);
});

distTest("CR2 · 6 · no coach-record chunk, no coach-entry marker (control: both planted)", () => {
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "_astro", "coach-record.Zz9PLANT.js"), "export const x = 1;");
    const page = join(dir, "system", "coaches", someCoach(), "index.html");
    writeFileSync(page, readFileSync(page, "utf8").replace("</main>", `<section ${ROOM_MARKER}="coach-entry"></section></main>`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes("coach-record.Zz9PLANT.js: an asset named for the room")), `a coach-record chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("room marker")), `the coach-entry marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

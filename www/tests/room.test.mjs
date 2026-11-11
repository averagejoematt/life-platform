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

import {
  CR1_MARKERS,
  ROOM_DATA_FILES,
  ROOM_ENV,
  ROOM_MARKER,
  ROOM_PRIVATE_MARKER,
  ROOM_ROUTES,
  committedRoomPublic,
  isRoomPath,
  notRoomPage,
  roomAll,
  roomCr2,
  roomEnabled,
  roomIntegration,
  roomPathPattern,
  roomPublic,
  roomScope,
  scopeRoutes,
} from "../src/lib/room.js";
import { cr1Leaks, cr2Leaks, feeds, gatedKeys, gatedPaths, gatedRoutes, jsonFiles, orphanChunks, ownedPaths, roomPaths, sitemaps, walk } from "../scripts/room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.ROOM_AUDIT_DIST || join(WWW, "dist"));
const HAVE_DIST = existsSync(join(DIST, "index.html"));
// The committed switch (www/owned_paths.json `room_public`): "off" today, "cr1" after the launch merge. Every dist check
// below plants what the switch does NOT publish, so each holds — with its control — on both sides of that merge.
const COMMITTED = committedRoomPublic();
const GATED = gatedRoutes(COMMITTED);
const ROOM_PATH = GATED.find((r) => !r.path.includes("[")).path; // "/system/calibration/" while off; "/system/docket/" once CR1 is public
const GATED_KEY = gatedKeys(COMMITTED)[0]; // "prereg_seal" while off; a CR2/CR3 key once CR1 is public
const GATED_ASSET = GATED[0].entrypoint.replace(/^.*\//, "").replace(/\.astro$/, "");
const isGated = (path) => GATED.some((r) => new RegExp(`${roomPathPattern(r.path)}$`).test(path));
// CR2 published (owner GO 2026-11-11, second message): the record pages are ordinary output; CR1 is published with it.
const CR2_ON = COMMITTED === "cr2";
const CR1_ON = COMMITTED === "cr1" || CR2_ON;

/** A throwaway copy of the dist to plant a leak in. */
function plantedCopy() {
  const dir = mkdtempSync(join(tmpdir(), "room-audit-"));
  cpSync(DIST, dir, { recursive: true });
  return dir;
}

// ── the switch ──────────────────────────────────────────────────────────────────────────────────────────────────
test("only the literals WEB_ROOM=1 (all), WEB_ROOM=cr1 (CR1) and WEB_ROOM=cr2 (CR1 + CR2) turn the room on privately; else the committed switch", () => {
  assert.equal(ROOM_ENV, "WEB_ROOM");
  assert.equal(roomEnabled({}, "off"), false);
  for (const v of ["", "0", "true", "yes", " 1", "1 ", "CR1", "CR2", "cr3", "all"]) assert.equal(roomEnabled({ WEB_ROOM: v }, "off"), false, `WEB_ROOM=${JSON.stringify(v)}`);
  assert.equal(roomScope({ WEB_ROOM: "cr2" }, "off"), "cr2");
  assert.equal(roomScope({}, "cr2"), "cr2", "the committed CR2 switch");
  assert.equal(roomScope({}, "cr3"), "off", "no committed value publishes CR3");
  assert.equal(roomCr2({}, "cr2"), true);
  assert.equal(roomCr2({}, "cr1"), false, "a CR1 build carries no CR2");
  assert.equal(roomCr2({ WEB_ROOM: "1" }, "off"), true);
  assert.equal(roomAll({}, "cr2"), false, "the committed switch never turns on CR3");
  assert.equal(roomPublic({}, "cr2"), true);
  assert.equal(roomPublic({ WEB_ROOM: "cr2" }, "cr2"), false, "WEB_ROOM marks a private build even when the switch is on");
  assert.equal(roomScope({ WEB_ROOM: "1" }, "off"), "all");
  assert.equal(roomScope({ WEB_ROOM: "cr1" }, "off"), "cr1");
  assert.equal(roomScope({}, "cr1"), "cr1", "the committed launch switch publishes CR1");
  assert.equal(roomScope({ WEB_ROOM: "1" }, "cr1"), "all", "a private whole-room look still wins locally");
  assert.equal(roomAll({}, "cr1"), false, "the committed switch never turns on CR2/CR3");
  assert.equal(roomPublic({}, "cr1"), true);
  assert.equal(roomPublic({ WEB_ROOM: "cr1" }, "cr1"), false, "WEB_ROOM marks a private build even when the switch is on");
  assert.equal(roomPublic({}, "off"), false);
  assert.ok(["off", "cr1", "cr2"].includes(COMMITTED), `owned_paths.json room_public=${COMMITTED}`);
});

test("switch off: the integration injects no route (controls: WEB_ROOM=1 injects every route; cr1 injects only CR1's)", () => {
  const inject = (env, committed) => {
    const out = [];
    roomIntegration(env, committed).hooks["astro:config:setup"]({ injectRoute: (r) => out.push(r) });
    return out.map((r) => r.pattern);
  };
  assert.deepEqual(inject({}, "off"), []);
  assert.deepEqual(inject({ WEB_ROOM: "1" }, "off"), ROOM_ROUTES.map((r) => r.pattern), "the control: the whole room injects every route");
  const cr1 = ["/system/calibration", "/system/ledger/refuted"];
  assert.deepEqual(inject({ WEB_ROOM: "cr1" }, "off"), cr1, "a CR1 build injects the calibration page and wrong-this-month only");
  assert.deepEqual(inject({}, "cr1"), cr1, "so does the committed switch");
  assert.deepEqual(scopeRoutes("cr1").map((r) => r.release), ["cr1", "cr1"]);
  for (const r of ROOM_ROUTES) assert.ok(["cr1", "cr2", "cr3"].includes(r.release), `${r.path} names its release`);
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

test("the sitemap filter drops every room path and keeps everything else; once CR1 is published it lists CR1 only", () => {
  const off = (u) => notRoomPage(u, {}, "off");
  assert.equal(off("https://averagejoematt.com/system/calibration/"), false);
  assert.equal(off("https://averagejoematt.com/next/v9/system/calibration/"), false);
  for (const u of ["https://averagejoematt.com/", "https://averagejoematt.com/system/", "https://averagejoematt.com/system/ledger/"]) assert.equal(off(u), true, u);
  const pub = (u) => notRoomPage(u, {}, "cr1");
  assert.equal(pub("https://averagejoematt.com/system/calibration/"), true);
  assert.equal(pub("https://averagejoematt.com/system/ledger/refuted/"), true);
  for (const u of ["https://averagejoematt.com/system/docket/", "https://averagejoematt.com/system/docket/x/", "https://averagejoematt.com/system/coaches/sleep_coach/record/"]) {
    assert.equal(pub(u), false, `${u}: never listed`);
  }
  assert.equal(notRoomPage("https://averagejoematt.com/system/calibration/", { WEB_ROOM: "cr1" }, "cr1"), false, "a private build lists nothing");
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
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, `{"${GATED_KEY}":1,`));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l.startsWith("system/calibration.json: a JSON file")), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) assert.ok(leaks.some((l) => l.includes(`"${GATED_KEY}"`)), `a room key in a declared file must red: ${leaks}`);
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
    writeFileSync(join(dir, "_astro", `${GATED_ASSET}.Zz9PLANT.js`), "export const x = 1;");
    const sys = join(dir, "system", "index.html");
    writeFileSync(sys, readFileSync(sys, "utf8").replace("<main", `<main ${ROOM_MARKER}="${CR2_ON ? "docket" : COMMITTED === "cr1" ? "coach-entry" : "entry"}"`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes("no built page reaches")), `an orphan chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("named for the room")), `a room-named asset must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("room marker")), `the room marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("the flag-off dist holds no unpublished room route directory at all", () => {
  for (const p of roomPaths(DIST)) assert.ok(!existsSync(join(DIST, p)), `${p} must not exist in this dist (was it built with WEB_ROOM=1?)`);
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
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/record/", {}, "off"), false);
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/record/", {}, "cr1"), false, "a CR1 build lists no record page");
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/record/", {}, "cr2"), true, "CR2 published: the record is listed");
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/record/", { WEB_ROOM: "cr2" }, "cr2"), false, "never from a private build");
  assert.equal(notRoomPage("https://averagejoematt.com/system/coaches/sleep_coach/"), true);
});

test("CR2 · the coach page's entry is self-gating and the record page refuses to render without CR2", () => {
  const page = readFileSync(join(WWW, "src", "pages", "system", "coaches", "[id].astro"), "utf8");
  assert.match(page, /import CoachRoomEntry from "..\/..\/..\/components\/CoachRoomEntry.astro"/);
  assert.match(page, /<\/section>\{\/\*[^]*?\*\/\}<CoachRoomEntry coach=\{c\} \/>\n<\/Base>/, "the entry sits flush, so the flag-off bytes do not move");
  const entry = readFileSync(join(WWW, "src", "components", "CoachRoomEntry.astro"), "utf8");
  assert.match(entry, /const on = roomCr2\(\);/, "CR2: on for the committed cr2 or a private CR2/whole-room build — never on a CR1 build");
  assert.match(entry, /on && commentary && \(/);
  assert.match(entry, /const entry = on \? /, "the room's data file is read only when the switch is on");
  assert.doesNotMatch(entry.split("\n---\n")[1], /<style|<script/, "the entry's template adds no asset");
  const record = readFileSync(join(WWW, RECORD.entrypoint), "utf8");
  assert.match(record, /if \(!roomCr2\(\)\) throw new Error/);
  assert.match(record, /!pub && \(/, "the private banner only on a private build");
  assert.match(record, /\{!noindex && !pub && <meta name="robots"/, "noindex only on a private build");
  assert.match(record, /whole && \(\n  <section class="section" \{\.\.\.room\} id="docket"/, "the docket (CR3) only on a whole-room build");
  assert.equal(RECORD.release, "cr2");
  assert.deepEqual(scopeRoutes("cr2").map((r) => r.path), ["/system/calibration/", "/system/coaches/[id]/record/", "/system/ledger/refuted/"]);
});

distTest("CR2 · 1 · a record path is a 404 unless CR2 is published, then every coach has one (control: planted / removed)", async () => {
  const coaches = readdirSync(join(DIST, "system", "coaches")).filter((d) => existsSync(join(DIST, "system", "coaches", d, "index.html")));
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    if (CR2_ON) {
      // published: one record page per coach page — and the audit still reds a planted CR3 page
      for (const id of coaches) assert.ok(existsSync(join(DIST, "system", "coaches", id, "record", "index.html")), `${id}'s record page`);
      mkdirSync(join(dir, "system", "docket"), { recursive: true });
      writeFileSync(join(dir, "system", "docket", "index.html"), "<!doctype html><p>planted</p>");
      const leaks = await gatedPaths(dir);
      assert.ok(leaks.some((l) => l.startsWith("/system/docket/ ") && l.includes("200")), `the control must red: ${leaks}`);
    } else {
      const probes = roomPaths(DIST).filter((p) => p.endsWith("/record/"));
      assert.ok(probes.length >= 2, `the audit expands [id] over the dist's coach pages: ${probes}`);
      const id = someCoach();
      mkdirSync(join(dir, "system", "coaches", id, "record"), { recursive: true });
      writeFileSync(join(dir, "system", "coaches", id, "record", "index.html"), "<!doctype html><p>planted</p>");
      const leaks = await gatedPaths(dir);
      assert.ok(leaks.some((l) => l.includes(`/system/coaches/${id}/record/`) && l.includes("200")), `the control must red: ${leaks}`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR2 · 2 · no coach_room.json ever; no gated room key in any JSON (control: a planted file and planted keys)", () => {
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "coach_room.json"), JSON.stringify({ ok: true }));
    const pairs = join(dir, "data", "pairs.json");
    const declaredOne = existsSync(pairs);
    const planted = CR2_ON ? ["docket_positions", "docket_entries"] : ["stance_history", "commitment_counts"];
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, `{${planted.map((k) => `"${k}":[],`).join("")}`));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l.startsWith("coach_room.json: a JSON file")), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) for (const k of planted) assert.ok(leaks.some((l) => l.includes(`"${k}"`)), `${k} must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR2 · 3+4 · the sitemap lists the record pages exactly when CR2 is published; never a gated path (control: planted)", () => {
  const sm = readdirSync(DIST).filter((f) => /^sitemap[^/]*\.xml$/.test(f)).map((f) => readFileSync(join(DIST, f), "utf8")).join("\n");
  // a preview build (WEB_NOINDEX=1) writes no sitemap at all; where one is written it lists the record pages exactly while CR2 is published
  if (sm.includes("<loc>")) assert.equal(/\/system\/coaches\/[^/<]+\/record\//.test(sm), CR2_ON, "record pages in the sitemap exactly while CR2 is published");
  const dir = plantedCopy();
  try {
    const loc = CR2_ON ? "https://averagejoematt.com/system/docket/x/" : `https://averagejoematt.com/system/coaches/${someCoach()}/record/`;
    writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>${loc}</loc></url></urlset>`);
    assert.ok(sitemaps(dir).length > 0, `${loc} must red the sitemap check`);
    writeFileSync(join(dir, "feed.xml"), `<rss><item><link>${loc}</link></item></rss>`);
    assert.ok(feeds(dir).some((l) => l.includes("names a room path") || l.includes("feed or search index")), "a gated link in a feed must red");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("CR2 · 5 · owned_paths.json names a record path exactly when CR2 is published (control: a planted gated route)", () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.ok((owned.route_patterns || []).includes("/system/coaches/*/"), "the existing coach pattern is present — and must not be read as a room path");
  assert.equal((owned.route_patterns || []).includes("/system/coaches/*/record/"), CR2_ON, "the record pattern is owned exactly while CR2 is published");
  assert.deepEqual(ownedPaths(owned), []);
  const plant = CR2_ON ? ["/system/docket/", "system/docket/x/index.html"] : ["/system/coaches/sleep_coach/record/", "system/coaches/sleep_coach/record/index.html"];
  const planted = { ...owned, routes: [...owned.routes, plant[0]], files: [...owned.files, plant[1]] };
  assert.ok(ownedPaths(planted).length >= 2, `the control must red: ${ownedPaths(planted)}`);
});

distTest("CR2 · 6 · no chunk or marker beyond the published release (control: both planted)", () => {
  const dir = plantedCopy();
  try {
    const [asset, marker] = CR2_ON ? ["docket", "docket"] : ["coach-record", "coach-entry"];
    writeFileSync(join(dir, "_astro", `${asset}.Zz9PLANT.js`), "export const x = 1;");
    const page = join(dir, "system", "coaches", someCoach(), "index.html");
    writeFileSync(page, readFileSync(page, "utf8").replace("</main>", `<section ${ROOM_MARKER}="${marker}"></section></main>`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes(`${asset}.Zz9PLANT.js: an asset named for the room`)), `a ${asset} chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("room marker")), `the ${marker} marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// ── CR3: the docket (/system/docket/, /system/docket/<id>/), "wrong this month" (/system/ledger/refuted/) and the
// entry on each disagreement page ─────────────────────────────────────────────────────────────────────────────────
const CR3 = ["/system/docket/", "/system/docket/[id]/", "/system/ledger/refuted/"];
/** The disagreement page a planted marker goes on — or, in a dist with none (a live snapshot serves none today), the ledger. */
const someDisagreementPage = (dir) => {
  const parent = join(dir, "system", "ledger", "disagreements");
  const id = existsSync(parent) ? readdirSync(parent).find((d) => existsSync(join(parent, d, "index.html"))) : null;
  return id ? join(parent, id, "index.html") : join(dir, "system", "ledger", "index.html");
};

test("CR3 · the three routes are room routes; a near miss is not (control: the live ledger and disagreement paths stay public)", () => {
  for (const p of CR3) assert.ok(ROOM_ROUTES.some((r) => r.path === p), `${p} is a room route`);
  for (const p of ["/system/docket/", "/system/docket/2026-10-02-nutrition-coach-sleep-coach/", "/system/ledger/refuted/", "/next/v9/system/docket/x/"]) assert.equal(isRoomPath(p), true, p);
  for (const p of ["/system/ledger/", "/system/ledger/sleep-20261005-deepsleep01/", "/system/ledger/disagreements/x/", "/system/docket/a/b/", "/system/dockets/"]) assert.equal(isRoomPath(p), false, p);
  assert.equal(notRoomPage("https://averagejoematt.com/system/ledger/refuted/", {}, "off"), false);
  assert.equal(notRoomPage("https://averagejoematt.com/system/ledger/", {}, "off"), true);
});

test("CR3 · the disagreement page's entry is self-gating and flush; every CR3 room page refuses to render with the switch off", () => {
  const page = readFileSync(join(WWW, "src", "pages", "system", "ledger", "disagreements", "[id].astro"), "utf8");
  assert.match(page, /import DisagreementRoomEntry from "..\/..\/..\/..\/components\/DisagreementRoomEntry.astro"/);
  assert.match(page, /<\/section>\{\/\*[^]*?\*\/\}<DisagreementRoomEntry d=\{d\} \/>\n<\/Base>/, "the entry sits flush, so the flag-off bytes do not move");
  const entry = readFileSync(join(WWW, "src", "components", "DisagreementRoomEntry.astro"), "utf8");
  assert.match(entry, /const on = roomAll\(\);/, "CR3: on only for the whole room — never on a CR1 build");
  assert.match(entry, /on && \(/);
  assert.match(entry, /const entry = on \? /, "the room's data file is read only when the switch is on");
  assert.doesNotMatch(entry.split("\n---\n")[1], /<style|<script/, "the entry's template adds no asset");
  for (const r of ROOM_ROUTES.filter((x) => CR3.includes(x.path))) {
    // the docket pages refuse anything but the whole room; "wrong this month" ships with CR1 and refuses only "off"
    const guard = r.release === "cr1" ? /if \(!roomEnabled\(\)\) throw new Error/ : /if \(!roomAll\(\)\) throw new Error/;
    assert.match(readFileSync(join(WWW, r.entrypoint), "utf8"), guard, r.entrypoint);
  }
  // RefutedMonth is imported by the room only — no page under src/pages reaches it
  const pages = walk(join(WWW, "src", "pages")).map((p) => readFileSync(p, "utf8"));
  assert.ok(!pages.some((t) => t.includes("RefutedMonth")), "no public page imports the room's ledger rows");
});

distTest("CR3 · 1 · every docket, entry and refuted path is a 404 (control: each planted page answers 200)", async () => {
  const probes = roomPaths(DIST);
  assert.ok(probes.includes("/system/docket/") && probes.includes("/system/docket/room-probe/"), `${probes}`);
  assert.equal(probes.includes("/system/ledger/refuted/"), !CR1_ON, "wrong-this-month is gated exactly while CR1 is unpublished");
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    for (const rel of ["system/docket", "system/docket/2026-10-02-a-b", "system/ledger/refuted"]) {
      mkdirSync(join(dir, rel), { recursive: true });
      writeFileSync(join(dir, rel, "index.html"), "<!doctype html><p>planted</p>");
    }
    const leaks = await gatedPaths(dir);
    for (const p of ["/system/docket/ ", "/system/docket/2026-10-02-a-b/ ", "/system/ledger/refuted/ "].filter((x) => isGated(x.trim()))) {
      assert.ok(leaks.some((l) => l.startsWith(p) && l.includes("200")), `the control must red for ${p.trim()}: ${leaks}`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR3 · 2 · no CR3 room key in any JSON (control: each planted key)", () => {
  const dir = plantedCopy();
  try {
    const pairs = join(dir, "data", "pairs.json");
    assert.ok(existsSync(pairs), "a declared JSON endpoint to plant into");
    writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, '{"docket_entries":[],"docket_counts":{},"concession_withheld":null,'));
    const leaks = jsonFiles(dir);
    for (const k of ["docket_entries", "docket_counts", "concession_withheld"]) assert.ok(leaks.some((l) => l.includes(`"${k}"`)), `${k} must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("CR3 · 3+4 · no sitemap or feed names a docket or refuted path (control: a planted <loc> and a planted feed)", () => {
  for (const loc of ["https://averagejoematt.com/system/docket/x/", "https://averagejoematt.com/system/ledger/refuted/"].filter((u) => isGated(new URL(u).pathname))) {
    const dir = plantedCopy();
    try {
      writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>${loc}</loc></url></urlset>`);
      assert.ok(sitemaps(dir).length > 0, `${loc} in a sitemap must red`);
      writeFileSync(join(dir, "feed.xml"), `<rss><item><link>${loc}</link></item></rss>`);
      assert.ok(feeds(dir).some((l) => l.includes("names a room path")), `${loc} in a feed must red`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

test("CR3 · 5 · owned_paths.json names no CR3 path (control: planted routes; the ledger's own pattern stays clean)", () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.deepEqual(ownedPaths(owned), []);
  const planted = {
    ...owned,
    routes: [...owned.routes, "/system/docket/", "/system/ledger/refuted/"],
    files: [...owned.files, "system/docket/2026-10-02-a-b/index.html"],
  };
  assert.ok(ownedPaths(planted).length >= (CR1_ON ? 2 : 3), `the control must red: ${ownedPaths(planted)}`);
});

distTest("CR3 · 6 · no docket/refuted chunk, no disagreement-entry marker (control: each planted)", () => {
  const dir = plantedCopy();
  try {
    const names = ["docket.Zz9PLANT.js", "docket-entry.Zz9PLANT.css", ...(CR1_ON ? [] : ["refuted.Zz9PLANT.js"])];
    for (const n of names) writeFileSync(join(dir, "_astro", n), "x");
    const page = someDisagreementPage(dir);
    writeFileSync(page, readFileSync(page, "utf8").replace("</main>", `<section ${ROOM_MARKER}="disagreement-entry"></section></main>`));
    const leaks = orphanChunks(dir);
    for (const n of names) {
      assert.ok(leaks.some((l) => l.includes(`${n}: an asset named for the room`)), `${n} must red: ${leaks}`);
    }
    assert.ok(leaks.some((l) => l.includes("room marker")), `the disagreement-entry marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// ── CR1 ships alone (owner ruling 2026-11-09): a CR1-only build carries nothing of CR2/CR3 ──────────────────────────
// cr1Leaks runs on THIS dist (clean when off; the published CR1 dist once `room_public` is "cr1") and on a planted copy
// for every leak class. A private WEB_ROOM=cr1 dist is checked the same way by pointing ROOM_AUDIT_DIST at it.

test("CR1 · the CR1 release is the calibration page and wrong-this-month; the /system/ entry drops the docket door outside the whole room", () => {
  assert.deepEqual(scopeRoutes("cr1").map((r) => r.path), ["/system/calibration/", "/system/ledger/refuted/"]);
  assert.deepEqual(CR1_MARKERS, ["calibration", "refuted", "entry"]);
  const entry = readFileSync(join(WWW, "src", "components", "RoomEntry.astro"), "utf8");
  assert.match(entry, /const docketOpen = on && roomAll\(\) \? /, "the docket (CR3) is read and linked only on a whole-room build");
  const cal = readFileSync(join(WWW, "src", "room", "calibration.astro"), "utf8");
  assert.match(cal, /\{obj && whole && <a href=\{href\(`\/system\/coaches\/\$\{obj\.id\}\/record\/`\)\}/, "the CR2 record link only where the page exists");
  for (const f of ["calibration.astro", "refuted.astro"]) {
    const t = readFileSync(join(WWW, "src", "room", f), "utf8");
    assert.match(t, /!pub && \(/, `${f}: the private banner only on a private build`);
    assert.match(t, new RegExp(`${ROOM_PRIVATE_MARKER}=""`), `${f}: the private banner carries the marker the deploy scan refuses`);
    assert.match(t, /\{!noindex && !pub && <meta name="robots"/, `${f}: noindex only on a private build`);
  }
});

distTest("CR2 · a published CR2 dist carries no CR3 page, link, marker, key or file (control: each planted)", () => {
  if (!CR2_ON) return;
  assert.deepEqual(cr2Leaks(DIST), []);
  const plants = [
    [(d) => { mkdirSync(join(d, "system", "docket"), { recursive: true }); writeFileSync(join(d, "system", "docket", "index.html"), "<p>d</p>"); }, "/system/docket/: a CR3 page"],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", '<a href="/system/docket/">d</a></main>')); }, "system/index.html: links a CR3 page"],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", `<section ${ROOM_MARKER}="disagreement-entry"></section></main>`)); }, 'marker data-room="disagreement-entry"'],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", '<div data-payload="{&quot;docket_positions&quot;:[]}"></div></main>')); }, 'key "docket_positions"'],
    [(d) => writeFileSync(join(d, "coach_room.json"), "{}"), "coach_room.json: the room's data file"],
  ];
  for (const [plant, expect] of plants) {
    const dir = plantedCopy();
    try {
      plant(dir);
      const leaks = cr2Leaks(dir);
      assert.ok(leaks.some((l) => l.includes(expect)), `the control must red (${expect}): ${leaks}`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

distTest("CR1 · a CR1-only dist carries no CR2/CR3 page, link, marker, key or file (control: each planted)", () => {
  if (!CR2_ON) assert.deepEqual(cr1Leaks(DIST), []);
  else assert.ok(cr1Leaks(DIST).length > 0, "a published CR2 dist is not CR1-only: the CR1 bar must see its record pages");
  const plants = [
    [(d) => { mkdirSync(join(d, "system", "docket"), { recursive: true }); writeFileSync(join(d, "system", "docket", "index.html"), "<p>d</p>"); }, "/system/docket/: a CR2/CR3 page"],
    [(d) => { const id = someCoach(); mkdirSync(join(d, "system", "coaches", id, "record"), { recursive: true }); writeFileSync(join(d, "system", "coaches", id, "record", "index.html"), "<p>r</p>"); }, "/record/: a CR2/CR3 page"],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", '<a href="/system/docket/">d</a></main>')); }, "system/index.html: links a CR2/CR3 page"],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", `<a href="/system/coaches/${someCoach()}/record/">r</a></main>`)); }, "system/index.html: links a CR2/CR3 page"],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", `<section ${ROOM_MARKER}="coach-entry"></section></main>`)); }, 'marker data-room="coach-entry"'],
    [(d) => { const f = join(d, "system", "index.html"); writeFileSync(f, readFileSync(f, "utf8").replace("</main>", '<div data-payload="{&quot;docket_entries&quot;:[]}"></div></main>')); }, 'key "docket_entries"'],
    [(d) => writeFileSync(join(d, "coach_room.json"), "{}"), "coach_room.json: CR2/CR3's data file"],
  ];
  for (const [plant, expect] of plants) {
    const dir = plantedCopy();
    try {
      plant(dir);
      const leaks = cr1Leaks(dir);
      assert.ok(leaks.some((l) => l.includes(expect)), `the control must red (${expect}): ${leaks}`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

distTest("CR1 · the private banner never passes the audit, whatever the switch (control: planted on /system/)", () => {
  const dir = plantedCopy();
  try {
    const f = join(dir, "system", "index.html");
    writeFileSync(f, readFileSync(f, "utf8").replace("</main>", `<div ${ROOM_PRIVATE_MARKER}=""></div></main>`));
    for (const c of ["off", "cr1"]) assert.ok(orphanChunks(dir, c).some((l) => l.includes("private-build banner")), `switch ${c}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("CR1 · a published CR1 build may carry the CR1 markers; an unpublished one may not (control)", () => {
  const dir = mkdtempSync(join(tmpdir(), "room-cr1-"));
  try {
    mkdirSync(join(dir, "system", "calibration"), { recursive: true });
    writeFileSync(join(dir, "system", "calibration", "index.html"), `<main ${ROOM_MARKER}="calibration"></main>`);
    assert.ok(!orphanChunks(dir, "cr1").some((l) => l.includes("room marker")), "published: the CR1 marker is allowed");
    assert.ok(orphanChunks(dir, "off").some((l) => l.includes("room marker")), "the control: unpublished, it reds");
    assert.deepEqual(gatedRoutes("cr1").map((r) => r.release).sort(), ["cr2", "cr3", "cr3"]);
    assert.equal(gatedRoutes("off").length, ROOM_ROUTES.length);
    assert.deepEqual(ownedPaths({ room_public: "cr1", routes: ["/system/calibration/", "/system/ledger/refuted/"] }), []);
    assert.ok(ownedPaths({ room_public: "off", routes: ["/system/calibration/"] }).length === 1, "the control: off names no room path");
    assert.ok(ownedPaths({ room_public: "cr1", routes: ["/system/docket/"] }).length === 1, "published CR1 still names no CR3 path");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

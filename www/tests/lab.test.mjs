// The Laboratory is built dark (L1, src/lib/lab.js): with WEB_LAB off it is ABSENT from the artifact, not merely
// unlinked. Two halves, mirroring tests/room.test.mjs:
//   * the switch itself — the helper, the route injection, where the Lab's files live, the sitemap filter;
//   * the flag-off dist — six checks from scripts/lab_audit.mjs, each run on the real build (CI: the fixture build
//     scripts/check_www_build.py leaves in www/dist; elsewhere LAB_AUDIT_DIST) AND on a planted copy, where it must
//     find the leak it exists to find (the mutation control: a check that cannot fail is not a check).
// The master proof stays the byte-identical recursive diff of this tree's flag-off dist against main's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { LAB_DATA_FILE, LAB_ENV, LAB_LIVE, LAB_MARKER, LAB_ROOT, LAB_ROUTES, labEnabled, labIntegration, labPrivate, notLabPage } from "../src/lib/lab.js";
import { feeds, gatedPaths, jsonFiles, orphanChunks, ownedPaths, probes, sitemaps } from "../scripts/lab_audit.mjs";
import { walk } from "../scripts/room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.LAB_AUDIT_DIST || join(WWW, "dist"));
const HAVE_DIST = existsSync(join(DIST, "index.html"));
const LAB_BUILD = HAVE_DIST && existsSync(join(DIST, LAB_ROOT));

function plantedCopy() {
  const dir = mkdtempSync(join(tmpdir(), "lab-audit-"));
  cpSync(DIST, dir, { recursive: true });
  return dir;
}

// ── the switch ──────────────────────────────────────────────────────────────────────────────────────────────────
test("only the literal WEB_LAB=1 turns the Lab on", () => {
  assert.equal(LAB_ENV, "WEB_LAB");
  assert.equal(labEnabled({}, false), false);
  for (const v of ["", "0", "true", "yes", " 1", "1 "]) assert.equal(labEnabled({ WEB_LAB: v }, false), false, `WEB_LAB=${JSON.stringify(v)}`);
  assert.equal(labEnabled({ WEB_ROOM: "1" }, false), false, "the Coaching Room's switch is not the Lab's");
  assert.equal(labEnabled({ WEB_LAB: "1" }, false), true);
});

test("switch off: the integration injects no route (control: switch on injects every Lab route)", () => {
  const off = [];
  labIntegration({}, false).hooks["astro:config:setup"]({ injectRoute: (r) => off.push(r) });
  assert.deepEqual(off, []);
  const on = [];
  labIntegration({ WEB_LAB: "1" }, false).hooks["astro:config:setup"]({ injectRoute: (r) => on.push(r) });
  assert.deepEqual(
    on.map((r) => r.pattern),
    LAB_ROUTES.map((r) => r.pattern),
    "the control: with the switch on the integration must inject — otherwise the off case proves nothing",
  );
});

test("every Lab route sits under /data/lab/ and its page lives outside src/pages, named for the Lab", () => {
  const pages = walk(join(WWW, "src", "pages")).map((p) => readFileSync(p, "utf8"));
  for (const r of LAB_ROUTES) {
    assert.ok(r.path.startsWith(LAB_ROOT), `${r.path} under ${LAB_ROOT}`);
    assert.ok(existsSync(join(WWW, r.entrypoint)), `${r.entrypoint} exists`);
    assert.ok(!r.entrypoint.includes("src/pages/"), `${r.entrypoint} must not sit under src/pages/`);
    assert.match(r.entrypoint, /\/lab-[a-z]+\.astro$/, "a Lab page is named lab-*.astro, so its chunk is named for the Lab");
  }
  assert.ok(!pages.some((t) => /from\s+["'][./]*\.\.\/lab\//.test(t) || t.includes("src/lab/") || t.includes("LabBanner")), "no page imports a Lab page");
  // the one component a page renders is self-gating
  const entry = readFileSync(join(WWW, "src", "components", "LabEntry.astro"), "utf8");
  assert.match(entry, /const on = labEnabled\(\);/);
  assert.match(entry, /const lab = on \? await loadLab\(\) : null;/);
  assert.match(entry, /on && \(/);
  // no challenge write control anywhere in the Lab (owner brief: reader writes stay out)
  for (const f of walk(join(WWW, "src", "lab"))) {
    const t = readFileSync(f, "utf8");
    assert.ok(!/<form\b|<button\b|<input\b|method="post"|challenge_checkin|challenge_vote|experiment_vote|experiment_suggest/i.test(t), `${f}: a write control`);
  }
});

test("the sitemap filter drops every Lab path and keeps everything else", () => {
  for (const p of [...LAB_ROUTES.map((r) => r.path), "/data/lab/tests/x/", "/next/v9/data/lab/"]) assert.equal(notLabPage(`https://averagejoematt.com${p}`, false), false, p);
  for (const p of ["/", "/data/", "/data/experiments/x/", "/data/labs-are-not-the-lab/", "/data/day/2026-10-04/"]) assert.equal(notLabPage(`https://averagejoematt.com${p}`, false), true, p);
});

test("the probes include one object page per dynamic route", () => {
  const p = probes();
  assert.ok(p.some((x) => x.startsWith("/data/lab/experiments/") && x !== "/data/lab/experiments/"));
  assert.ok(p.some((x) => x.startsWith("/data/lab/tests/") && x !== "/data/lab/tests/"));
});

// ── the flag-off dist: six checks, each with its own planted control ──────────────────────────────────────────────
const why = LAB_LIVE ? "the Lab is committed live (LAB_LIVE): the flag-off proofs do not apply" : !HAVE_DIST ? `no built dist at ${DIST} — run the flag-off build first (CI: check_www_build.py)` : LAB_BUILD ? `${DIST} is a WEB_LAB=1 build` : false;
const distTest = (name, fn) => test(name, { skip: why }, fn);

distTest("1 · every Lab path is a 404 on direct request (control: a planted page answers 200)", async () => {
  assert.deepEqual(await gatedPaths(DIST), []);
  const dir = plantedCopy();
  try {
    const sample = probes().find((x) => x.startsWith("/data/lab/tests/") && x !== "/data/lab/tests/");
    mkdirSync(join(dir, sample), { recursive: true });
    writeFileSync(join(dir, sample, "index.html"), "<!doctype html><p>planted</p>");
    const leaks = await gatedPaths(dir);
    assert.ok(leaks.some((l) => l.includes("answered 200")), `the control must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("a file under /data/lab/")), `the file walk must red too: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("2 · no new JSON, not the Lab's data file, no Lab-only key (control: a planted lab.json and a planted key)", () => {
  assert.deepEqual(jsonFiles(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "data", LAB_DATA_FILE), JSON.stringify({ ok: true }));
    const pairs = join(dir, "data", "pairs.json");
    const declaredOne = existsSync(pairs);
    if (declaredOne) writeFileSync(pairs, readFileSync(pairs, "utf8").replace(/^\{/, '{"lab_tests":[],'));
    const leaks = jsonFiles(dir);
    assert.ok(leaks.some((l) => l === `data/${LAB_DATA_FILE}: the Lab's data file`), `the data file must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.startsWith(`data/${LAB_DATA_FILE}: a JSON file`)), `undeclared JSON must red: ${leaks}`);
    if (declaredOne) assert.ok(leaks.some((l) => l.includes('"lab_tests"')), `a Lab key in a declared file must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("3 · no sitemap lists a Lab path (control: a planted <loc>)", () => {
  assert.deepEqual(sitemaps(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "sitemap-0.xml"), `<urlset><url><loc>https://averagejoematt.com${LAB_ROOT}</loc></url></urlset>`);
    assert.ok(sitemaps(dir).length > 0, "the control must red");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("4 · no feed or search index, and nothing machine-readable names a Lab path (control: a planted feed)", () => {
  assert.deepEqual(feeds(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "feed.xml"), `<rss><item><link>https://averagejoematt.com${LAB_ROOT}tests/x/</link></item></rss>`);
    const leaks = feeds(dir);
    assert.ok(leaks.some((l) => l.startsWith("feed.xml: a feed")) && leaks.some((l) => l.includes("names a Lab path")), `the control must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("5 · the committed owned_paths.json names no Lab path (control: a planted route and pattern)", { skip: LAB_LIVE ? "the Lab is committed live" : false }, () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.deepEqual(ownedPaths(owned), []);
  const planted = { ...owned, routes: [...owned.routes, LAB_ROOT], route_patterns: [...(owned.route_patterns || []), "/data/lab/tests/[id]/"] };
  assert.ok(ownedPaths(planted).length >= 2, "the control must red");
});

distTest("6 · no CSS/JS chunk exists only for a gated page, none is named for the Lab, no Lab marker (control: all three)", () => {
  assert.deepEqual(orphanChunks(DIST), []);
  const dir = plantedCopy();
  try {
    writeFileSync(join(dir, "_astro", "lab-test.astro_astro_type_script_index_0_lang.Zz9PLANT.js"), "export const x = 1;");
    const data = join(dir, "data", "index.html");
    writeFileSync(data, readFileSync(data, "utf8").replace("<main", `<main ${LAB_MARKER}="entry"`));
    const leaks = orphanChunks(dir);
    assert.ok(leaks.some((l) => l.includes("no built page reaches")), `an orphan chunk must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("named for the Lab")), `a Lab-named asset must red: ${leaks}`);
    assert.ok(leaks.some((l) => l.includes("Lab marker")), `the Lab marker must red: ${leaks}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

distTest("the flag-off dist holds no Lab directory at all", () => {
  assert.ok(!existsSync(join(DIST, LAB_ROOT)), `${LAB_ROOT} must not exist in a flag-off dist (was this dist built with WEB_LAB=1?)`);
  assert.ok(!readdirSync(join(DIST, "data")).includes(LAB_DATA_FILE));
});

// ── the go-live switch (2026-11-09): LAB_LIVE, one committed line ─────────────────────────────────────────────────
test("the go-live constant is one literal line, false until the owner's go (feat/lab-go-live flips it)", () => {
  const src = readFileSync(join(WWW, "src", "lib", "lab.js"), "utf8");
  const lines = src.match(/^export const LAB_LIVE = (true|false);$/gm) || [];
  assert.equal(lines.length, 1, "scripts/www_launch_switch.py reads exactly this one line");
  assert.equal(typeof LAB_LIVE, "boolean");
});

test("live: the Lab is on with no env, its pages are kept in the sitemap, and no build is 'private' (control: dark)", () => {
  assert.equal(labEnabled({}, true), true);
  assert.equal(labPrivate({ WEB_LAB: "1" }, true), false, "a live Lab is never a private build");
  assert.equal(labPrivate({ WEB_LAB: "1" }, false), true, "the control: dark + env switch IS the private build");
  assert.equal(labPrivate({}, false), false);
  for (const r of LAB_ROUTES) assert.equal(notLabPage(`https://averagejoematt.com${r.path}`, true), true, r.path);
  const on = [];
  labIntegration({}, true).hooks["astro:config:setup"]({ injectRoute: (r) => on.push(r.pattern) });
  assert.deepEqual(on, LAB_ROUTES.map((r) => r.pattern));
});

test("live dist: the Lab is built, owned, mapped and public — no private banner, no noindex", { skip: !LAB_LIVE ? "the Lab is dark (LAB_LIVE false)" : !HAVE_DIST ? "no built dist" : false }, () => {
  const owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"));
  assert.ok(owned.routes.includes(LAB_ROOT) && owned.static_routes.includes(LAB_ROOT), "owned_paths.json owns /data/lab/");
  const html = readFileSync(join(DIST, LAB_ROOT, "index.html"), "utf8");
  assert.ok(!html.includes("private build"), "no private banner on a live page");
  // no robots tag of the Lab's own: exactly as many as an ordinary page of the same build (the preview base stamps one)
  const robots = (h) => (h.match(/<meta name="robots"/g) || []).length;
  assert.equal(robots(html), robots(readFileSync(join(DIST, "data", "index.html"), "utf8")), "no private-build robots tag on a live Lab page");
});

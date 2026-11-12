// www/scripts/postbuild.mjs — what the v9 build emits BESIDES dist/ (#5534, epic #5529).
//
// Runs as the tail of `npm run build` (and so of `build:preview`). Three jobs, all deterministic:
//
//   1. dist/.prerender is removed (Astro's scratch dir; it must never reach S3).
//   2. dist/sitemap.xml is written as a copy of @astrojs/sitemap's sitemap-index.xml, so the
//      URL the site has always advertised (robots.txt, Search Console) is the v9 index once the
//      build owns `/`. The integration cannot name its index `sitemap.xml` itself (it writes
//      `<filenameBase>-index.xml`). Absent on a WEB_NOINDEX build, where the sitemap is off.
//   3. ../owned_paths.json and ../reach.json are (re)written — the two committed artifacts the
//      Python side reads, because pytest cannot run `astro build`:
//        owned_paths.json  every path the PRODUCTION-base build writes under its prefix —
//                          directory routes, loose files, the two asset prefixes — plus the
//                          static routes and route patterns read off src/pages/. The site/
//                          deploy (deploy/sync_site_to_s3.sh, deploy/rollback_site.sh) excludes
//                          exactly these through deploy/www_owned_paths.py: one owner per path.
//                          `live_at_root` is NOT build output — it is the cut-over switch, carried
//                          forward from the existing file (default false) so a rebuild never flips it.
//        reach.json        the static reach from the front page (the #4182 ratchet, re-measured
//                          on this tree): depth-1 (what a newcomer meets on landing) and the
//                          transitive closure over the built pages, the appendix a sink by ruling.
//
// Base handling: Astro writes dist/ the same way for both bases (the base changes URLs, not the
// output tree), so the owned paths are read straight off dist/; only the hrefs the reach walk
// follows carry the preview prefix, and those are normalised to the production base (`/`). Both
// targets therefore emit the same owned_paths.json, and the drift check in
// scripts/check_www_build.py compares like with like.
import { existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync, copyFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { ROOM_ENV, ROOM_PUBLIC_VALUES, roomPrivate, roomScope, scopeRoutes } from "../src/lib/room.js";
import { LAB_ROUTES, labEnabled, labPrivate } from "../src/lib/lab.js";
import { STORY_ROUTES, storyEnabled, storyPrivate } from "../src/lib/story_dark.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(WWW, "dist");
const PAGES = join(WWW, "src", "pages");
const OWNED_OUT = join(WWW, "owned_paths.json");
const REACH_OUT = join(WWW, "reach.json");
const SITE_HOST = "https://averagejoematt.com";
// The footnote appendix is a sink in the reach walk (owner ruling 2026-10-18, #4588).
const REACH_SINKS = ["/system/everything-else/"];
const ASSET_PREFIX_ROOTS = ["_astro", "assets"];

const rawBase = process.env.WEB_BASE || "/";
// A PRIVATE Coaching Room build (WEB_ROOM=1 or WEB_ROOM=cr1, src/lib/room.js) is local: it must never rewrite the two
// committed artifacts the deploy reads, so they are left exactly as committed and the build says so. A PUBLISHED CR1
// build (the committed `room_public: "cr1"`, no WEB_ROOM) is an ordinary build: its pages are owned and counted.
// A Laboratory build (WEB_LAB=1, src/lib/lab.js, L1) is private in the same way and held to the same rule.
// A Human Story build (WEB_STORY=1, src/lib/story_dark.js, HS1) is private and local in exactly the same way.
// Only a PRIVATE build (the env switch while the go-live constant is false) is held back; once LAB_LIVE / STORY_LIVE is
// committed true the Lab / the story is ordinary build output and is owned, mapped and deployed like every page.
const lab = labPrivate();
const story = storyPrivate();
const privateRoom = roomScope() !== "off" && roomPrivate();
const room = privateRoom || lab || story;
const base = "/" + rawBase.replace(/^\/+|\/+$/g, "");

function walk(dir, out = []) {
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

function toPosix(p) {
  return p.split(sep).join("/");
}

// ── 1. scratch dir ────────────────────────────────────────────────────────────────────────
rmSync(join(DIST, ".prerender"), { recursive: true, force: true });

// ── 2. sitemap.xml = the index ────────────────────────────────────────────────────────────
if (existsSync(join(DIST, "sitemap-index.xml"))) copyFileSync(join(DIST, "sitemap-index.xml"), join(DIST, "sitemap.xml"));

// ── 3a. owned paths ───────────────────────────────────────────────────────────────────────
const routes = new Set();
const files = new Set();
const prefixes = new Set();
for (const abs of walk(DIST)) {
  const rel = toPosix(relative(DIST, abs));
  const top = rel.split("/")[0];
  if (ASSET_PREFIX_ROOTS.includes(top)) {
    // _astro/ is hashed output, owned whole; under assets/ own the directories the build writes into.
    prefixes.add(top === "_astro" ? "_astro/" : toPosix(dirname(rel)) + "/");
    continue;
  }
  if (rel.endsWith("/index.html") || rel === "index.html") {
    const dir = rel === "index.html" ? "" : rel.slice(0, -"index.html".length);
    routes.add("/" + dir);
  } else {
    files.add(rel);
  }
}

// The production build writes the sitemap (the preview, WEB_NOINDEX=1, turns it off); the owned
// set describes the production target, so the three sitemap files are owned on every build.
for (const f of ["sitemap-index.xml", "sitemap-0.xml", "sitemap.xml"]) files.add(f);

const staticRoutes = new Set();
const routePatterns = new Set();
for (const abs of walk(PAGES)) {
  const rel = toPosix(relative(PAGES, abs));
  if (!rel.endsWith(".astro")) continue;
  const noExt = rel.slice(0, -".astro".length);
  const route = noExt === "index" ? "/" : noExt.endsWith("/index") ? "/" + noExt.slice(0, -"/index".length) + "/" : "/" + noExt + "/";
  if (route.includes("[")) routePatterns.add(route.replace(/\[[^\]]+\]/g, "*"));
  else if (noExt === "404") files.add("404.html");
  else staticRoutes.add(route);
}

// A LIVE injected route (src/lib/lab.js, src/lib/story_dark.js) is not under src/pages/, so it is added here: a static
// one to static_routes (qa/qa_manifest.py derives its sweep rows from them), a [param] one to route_patterns.
for (const [on, list] of [
  [labEnabled() && !lab, LAB_ROUTES],
  [storyEnabled() && !story, STORY_ROUTES],
]) {
  if (!on) continue;
  for (const r of list) {
    const route = r.pattern.replace(/\/?$/, "/");
    if (route.includes("[")) routePatterns.add(route.replace(/\[[^\]]+\]/g, "*"));
    else staticRoutes.add(route);
  }
}

// A PUBLISHED room build (the committed `room_public: "cr1"` or "cr2"): the room's pages live outside src/pages/ and are
// injected (src/lib/room.js), so they are added here — a static one to static_routes, a [param] one (CR2's per-coach
// record) to route_patterns. Never on a private build (which does not write this file) and never while the switch is
// off (no route is injected).
if (!privateRoom && ["cr1", "cr2"].includes(roomScope())) {
  for (const r of scopeRoutes(roomScope())) {
    if (r.path.includes("[")) routePatterns.add(r.path.replace(/\[[^\]]+\]/g, "*"));
    else staticRoutes.add(r.path);
  }
}

let previous = {};
if (existsSync(OWNED_OUT)) {
  try {
    previous = JSON.parse(readFileSync(OWNED_OUT, "utf8"));
  } catch {
    previous = {};
  }
}

const owned = {
  _about:
    "Every path the v9 build (www/) writes for the production base `/`, emitted by www/scripts/postbuild.mjs on every build and " +
    "drift-checked by scripts/check_www_build.py. deploy/sync_site_to_s3.sh and deploy/rollback_site.sh exclude exactly these " +
    "through deploy/www_owned_paths.py — one owner per path (#5534). `live_at_root` is the cut-over switch, not build output: " +
    "false = the build is served at /next/v9/ only; true = the build owns `/` and every `www/**` merge deploys there. " +
    "`room_public` is the Coaching Room's committed publication switch, not build output: \"off\" = no room page is built; " +
    "\"cr1\" = every build publishes CR1 (/system/calibration/, /system/ledger/refuted/, the /system/ entry); \"cr2\" = CR1 + CR2 " +
    "(/system/coaches/<id>/record/ and the entry on each coach page); never CR3.",
  base: "/",
  files: [...files].sort(),
  flipped_on: previous.flipped_on ?? null,
  live_at_root: previous.live_at_root === true,
  prefixes: [...prefixes].sort(),
  room_public: ROOM_PUBLIC_VALUES.includes(previous.room_public) ? previous.room_public : "off",
  route_patterns: [...routePatterns].sort(),
  routes: [...routes].sort(),
  static_routes: [...staticRoutes].sort(),
};
if (!room) writeFileSync(OWNED_OUT, JSON.stringify(owned, null, 2) + "\n");

// ── 3b. reach ─────────────────────────────────────────────────────────────────────────────
function pagePath(route) {
  const dir = route === "/" ? "" : route.slice(1);
  return join(DIST, dir, "index.html");
}

/** Site-absolute directory routes a page links to (the build's own + kept site/ pages). */
function linksOf(route) {
  const html = readFileSync(pagePath(route), "utf8");
  const out = new Set();
  for (const m of html.matchAll(/<a\s[^>]*href="([^"#]+)(?:#[^"]*)?"/g)) {
    let href = m[1];
    let keptSite = false; // an absolute link to the kept site (e.g. /subscribe/) carries no base
    if (/^[a-z][a-z0-9+.-]*:/i.test(href)) {
      // Absolute: parse it and compare the ORIGIN exactly (a prefix test on the bare host string would
      // accept https://averagejoematt.com.evil.example — CodeQL js/incomplete-url-substring-sanitization).
      let parsed;
      try {
        parsed = new URL(href);
      } catch {
        continue;
      }
      if (parsed.origin !== SITE_HOST) continue; // another host: external
      href = parsed.pathname;
      keptSite = true;
    }
    if (!href.startsWith("/")) continue; // fragment or relative — not a site page
    if (!keptSite && base !== "/") {
      if (!(href === base || href.startsWith(base + "/"))) continue; // outside the preview base
      href = href.slice(base.length) || "/";
    }
    if (!href.endsWith("/")) continue; // a file, not a page
    if (href !== route) out.add(href);
  }
  return out;
}

const depth1 = [...linksOf("/")].filter((r) => !REACH_SINKS.includes(r)).sort();
const seen = new Set(["/"]);
const queue = ["/"];
while (queue.length) {
  const cur = queue.shift();
  for (const next of linksOf(cur)) {
    if (seen.has(next) || REACH_SINKS.includes(next)) continue;
    seen.add(next);
    if (routes.has(next)) queue.push(next); // a kept site/ page is counted as a leaf, not walked
  }
}
const transitive = [...seen].sort();
const reach = {
  _about:
    "The static reach from the v9 front page (tests/test_site_nav_reach_ratchet.py, #4182 ruling vi), measured on the build this " +
    "file was emitted from — the fixture snapshot in CI, so live data adds object pages of the same templates. `depth1` is what a " +
    "newcomer meets on landing (every <a href> on `/`); `transitive` follows links through the built pages. The appendix is a sink " +
    "by ruling (2026-10-18); a kept site/ page that the build links (e.g. /subscribe/) counts as a leaf and is not walked.",
  depth1,
  depth1_count: depth1.length,
  sinks: REACH_SINKS,
  start: "/",
  transitive,
  transitive_count: transitive.length,
};
if (!room) writeFileSync(REACH_OUT, JSON.stringify(reach, null, 2) + "\n");

if (room) {
  console.log(
    `postbuild: ${lab ? "WEB_LAB=1 — a private Laboratory build" : story ? "WEB_STORY=1 — a private Human Story build" : `WEB_ROOM=${process.env[ROOM_ENV]} — a private Coaching Room build`} (${routes.size} routes); owned_paths.json and reach.json left as committed. Never deploy this dist.`
  );
} else {
  console.log(
    `postbuild: ${routes.size} routes, ${files.size} files, ${prefixes.size} asset prefixes → owned_paths.json; ` +
      `reach depth1=${depth1.length} transitive=${transitive.length} → reach.json`
  );
}

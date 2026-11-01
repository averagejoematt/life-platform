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
    "false = the build is served at /next/v9/ only; true = the build owns `/` and every `www/**` merge deploys there.",
  base: "/",
  files: [...files].sort(),
  flipped_on: previous.flipped_on ?? null,
  live_at_root: previous.live_at_root === true,
  prefixes: [...prefixes].sort(),
  route_patterns: [...routePatterns].sort(),
  routes: [...routes].sort(),
  static_routes: [...staticRoutes].sort(),
};
writeFileSync(OWNED_OUT, JSON.stringify(owned, null, 2) + "\n");

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
    if (href.startsWith(SITE_HOST)) {
      href = href.slice(SITE_HOST.length);
      keptSite = true;
    }
    if (!href.startsWith("/")) continue; // external or fragment
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
writeFileSync(REACH_OUT, JSON.stringify(reach, null, 2) + "\n");

console.log(
  `postbuild: ${routes.size} routes, ${files.size} files, ${prefixes.size} asset prefixes → owned_paths.json; ` +
    `reach depth1=${depth1.length} transitive=${transitive.length} → reach.json`
);

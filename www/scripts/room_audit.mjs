// www/scripts/room_audit.mjs — is the Coaching Room ABSENT from a flag-off dist? (CR1, built dark; src/lib/room.js)
//
// The owner's bar (2026-11-08): with WEB_ROOM off, unpublished routes, generated content and supporting assets must
// be absent from the production artifact, not merely unlinked. Owner ruling 2026-11-09: CR1 launches ahead of CR2/CR3,
// through the committed switch `room_public` in www/owned_paths.json. So "gated" below means every room route the
// committed switch does NOT publish — all of them while it is "off"; the CR2/CR3 routes once it is "cr1" — and
// cr1Leaks() holds a CR1-only dist (private or published) to carrying no CR2/CR3 page, link, marker, key or file. Six checks, each pure over a dist directory (or the
// committed owned_paths.json), each returning the leaks it found ([] = clean). tests/room.test.mjs runs every one on
// the real flag-off build AND on a planted copy (the mutation control: each check must see its planted leak).
// The master proof is still the byte-identical recursive diff against a build of main from the same snapshot.
//
//   gatedPaths      a direct request for every room path is a 404 (served as S3 would: no object, no page)
//   jsonFiles       every .json in dist is a declared src/pages endpoint, and none carries a room-only data key
//   sitemaps        no sitemap file lists a room path
//   feeds           the build emits no feed / search index beyond the sitemaps, and nothing machine-readable names a room path
//   ownedPaths      the committed owned_paths.json names no room path
//   orphanChunks    every _astro/ asset is reachable from a built page (a chunk only a gated page used is an orphan);
//                   no asset is named for a gated room page; no page carries a gated room marker or the private banner
//   cr1Leaks        no CR2/CR3 page, link, marker, data key or data file (a CR1-only build's own bar; clean when off)
//
// CLI: node scripts/room_audit.mjs [dist]  → prints the leaks, exit 1 when any.
import { createServer } from "node:http";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CR1_MARKERS,
  CR23_DATA_FILES,
  CR23_DATA_KEYS,
  ROOM_DATA_KEYS,
  ROOM_MARKER,
  ROOM_PRIVATE_MARKER,
  ROOM_ROUTES,
  committedRoomPublic,
  roomPathPattern,
} from "../src/lib/room.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const posix = (p) => p.split(sep).join("/");

export function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}
const files = (dist) => walk(dist).map((p) => posix(relative(dist, p)));

/** The room routes the committed switch does NOT publish ("off": all of them; "cr1": the CR2/CR3 routes). */
export function gatedRoutes(committed = committedRoomPublic()) {
  return committed === "cr1" ? ROOM_ROUTES.filter((r) => r.release !== "cr1") : [...ROOM_ROUTES];
}
/** The room-only data keys a dist may not carry under the committed switch. */
export const gatedKeys = (committed = committedRoomPublic()) => (committed === "cr1" ? [...CR23_DATA_KEYS] : [...ROOM_DATA_KEYS]);
/** The room marker values a dist may carry under the committed switch (none while off). */
export const allowedMarkers = (committed = committedRoomPublic()) => (committed === "cr1" ? [...CR1_MARKERS] : []);
/** The CR2/CR3 routes — never in any CR1 build, private or published. */
export const cr23Routes = () => ROOM_ROUTES.filter((r) => r.release !== "cr1");

/**
 * The concrete room paths to request from a dist. A literal path is itself; a `[param]` path (CR2's per-coach record,
 * `/system/coaches/[id]/record/`) is expanded over every directory the dist holds at the param's place (each coach page
 * the build emitted) plus one probe id, so a dist with no coach pages is still asked.
 */
export function roomPaths(dist, routes = gatedRoutes()) {
  const out = [];
  for (const r of routes) {
    const m = /^(.*?)\[[^\]]+\](.*)$/.exec(r.path);
    if (!m) {
      out.push(r.path);
      continue;
    }
    const parent = dist ? join(dist, m[1]) : null;
    const ids = parent && existsSync(parent) ? readdirSync(parent).filter((d) => statSync(join(parent, d)).isDirectory()) : [];
    for (const id of [...ids, "room-probe"]) out.push(`${m[1]}${id}${m[2]}`);
  }
  return out;
}

/** One RegExp per room path (a `[param]` = one segment), matching the path with or without its trailing slash. */
const roomRx = (routes = gatedRoutes()) => routes.map((r) => new RegExp(`${roomPathPattern(r.path.slice(0, -1))}(/|")`));
const namesRoom = (text, routes = gatedRoutes()) => roomRx(routes).some((rx) => rx.test(text));

/** Serve dist as the S3 website origin does (`/x/` → `x/index.html`, a missing object → 404) and GET each room path. */
export async function gatedPaths(dist, routes = gatedRoutes()) {
  const server = createServer((req, res) => {
    const url = decodeURIComponent(new URL(req.url, "http://x").pathname);
    let p = join(dist, url);
    if (url.endsWith("/")) p = join(p, "index.html");
    if (existsSync(p) && statSync(p).isFile()) {
      res.writeHead(200);
      res.end(readFileSync(p));
    } else {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  const { port } = server.address();
  const leaks = [];
  try {
    for (const path of roomPaths(dist, routes)) {
      for (const variant of [path, path.slice(0, -1), `${path}index.html`]) {
        const r = await fetch(`http://127.0.0.1:${port}${variant}`);
        if (r.status !== 404) leaks.push(`${variant} answered ${r.status} (expected 404)`);
      }
    }
  } finally {
    server.close();
  }
  return leaks;
}

/** The JSON endpoints src/pages declares (`data/pairs.json.ts` → /^data\/pairs\.json$/, `[x]` → one segment). */
export function declaredJson(pagesDir = join(WWW, "src", "pages")) {
  return walk(pagesDir)
    .map((p) => posix(relative(pagesDir, p)))
    .filter((r) => /\.json\.(ts|js|mjs)$/.test(r))
    .map((r) => {
      // `[x]` → one segment; every other character escaped (backslash included), so a path is matched literally.
      const parts = r.replace(/\.(ts|js|mjs)$/, "").split(/(\[[^\]]+\])/);
      return new RegExp("^" + parts.map((s) => (/^\[[^\]]+\]$/.test(s) ? "[^/]+" : s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))).join("") + "$");
    });
}

export function jsonFiles(dist, declared = declaredJson(), keys = gatedKeys()) {
  const leaks = [];
  for (const rel of files(dist).filter((f) => f.endsWith(".json"))) {
    if (!declared.some((rx) => rx.test(rel))) leaks.push(`${rel}: a JSON file no src/pages endpoint declares`);
    const text = readFileSync(join(dist, rel), "utf8");
    for (const k of keys) if (text.includes(`"${k}"`)) leaks.push(`${rel}: carries the room-only key "${k}"`);
  }
  return leaks;
}

export function sitemaps(dist) {
  return files(dist)
    .filter((f) => /^sitemap[^/]*\.xml$/.test(f))
    .filter((f) => namesRoom(readFileSync(join(dist, f), "utf8")))
    .map((f) => `${f}: lists a room path`);
}

const FEED_LIKE = /\.(xml|rss|atom|txt|webmanifest)$|(^|\/)(pagefind|search|feed)[^/]*(\/|$)|index\.json$/i;
export function feeds(dist) {
  const leaks = [];
  for (const rel of files(dist)) {
    const sitemap = /^sitemap[^/]*\.xml$/.test(rel);
    if (FEED_LIKE.test(rel) && !sitemap) leaks.push(`${rel}: a feed or search index the build did not emit before the room`);
    if (/\.(xml|rss|atom|txt|json|webmanifest)$/.test(rel) && namesRoom(readFileSync(join(dist, rel), "utf8"))) leaks.push(`${rel}: names a room path`);
  }
  return leaks;
}

export function ownedPaths(owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"))) {
  const leaks = [];
  // the file's own switch decides which room paths it may name: none while off, the CR1 pages once "cr1"
  const routes = gatedRoutes(owned.room_public === "cr1" ? "cr1" : "off");
  for (const key of ["routes", "static_routes", "route_patterns", "files"]) {
    // a gated room path, or anything under one, with or without its leading slash (`[param]` = one segment)
    const rxs = routes.map((r) => new RegExp(`^/?${roomPathPattern(r.path.slice(1))}`));
    for (const v of owned[key] || []) if (rxs.some((rx) => rx.test(v))) leaks.push(`owned_paths.json ${key}: ${v}`);
  }
  return leaks;
}

/** An asset named for a gated room page: "room", or a gated page's entrypoint name (coach-record, docket, …), read off ROOM_ROUTES. */
const roomAssetNames = (routes) =>
  new RegExp(
    ["room", ...routes.map((r) => r.entrypoint.replace(/^.*\//, "").replace(/\.astro$/, ""))].map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"),
    "i"
  );
const MARKER_RX = new RegExp(`${ROOM_MARKER}="([^"]*)"`, "g");

export function orphanChunks(dist, committed = committedRoomPublic()) {
  const names = roomAssetNames(gatedRoutes(committed));
  const allowed = allowedMarkers(committed);
  const all = files(dist);
  const assets = all.filter((f) => f.startsWith("_astro/"));
  const pages = all.filter((f) => f.endsWith(".html"));
  const leaks = [];
  const seen = new Set();
  const queue = [];
  const scanText = (text) => {
    for (const a of assets) {
      const name = a.slice("_astro/".length);
      if (!seen.has(a) && text.includes(name)) {
        seen.add(a);
        queue.push(a);
      }
    }
  };
  for (const p of pages) {
    const html = readFileSync(join(dist, p), "utf8");
    if (html.includes(ROOM_PRIVATE_MARKER)) leaks.push(`${p}: carries the private-build banner ${ROOM_PRIVATE_MARKER}`);
    for (const m of html.matchAll(MARKER_RX)) if (!allowed.includes(m[1])) leaks.push(`${p}: carries the room marker ${ROOM_MARKER}="${m[1]}"`);
    scanText(html);
  }
  while (queue.length) scanText(readFileSync(join(dist, queue.shift()), "utf8"));
  for (const a of assets) {
    if (!seen.has(a)) leaks.push(`${a}: an asset no built page reaches (built for a page that is not in this dist)`);
    if (names.test(a)) leaks.push(`${a}: an asset named for the room`);
  }
  return leaks;
}

/**
 * A CR1-only dist (WEB_ROOM=cr1, or the committed `room_public: "cr1"`) carries nothing of CR2/CR3: no record or docket
 * page, no link to one, no CR2/CR3 marker, no CR2/CR3-only key in any page, script or JSON, no coach_room.json.
 * Clean on a flag-off dist by construction; on a whole-room (WEB_ROOM=1) dist it is meant to red.
 */
export function cr1Leaks(dist) {
  const leaks = [];
  const routes = cr23Routes();
  for (const path of roomPaths(dist, routes)) if (existsSync(join(dist, path, "index.html"))) leaks.push(`${path}: a CR2/CR3 page in the dist`);
  const linkRx = routes.map((r) => new RegExp(`href="[^"]*${roomPathPattern(r.path.slice(0, -1))}/?(?:[#?][^"]*)?"`));
  const cr23Markers = ["coach-record", "coach-entry", "docket", "docket-entry", "disagreement-entry"];
  for (const rel of files(dist)) {
    if (CR23_DATA_FILES.some((f) => rel === f || rel.endsWith(`/${f}`))) leaks.push(`${rel}: CR2/CR3's data file`);
    if (!/\.(html|json|js|xml|txt)$/.test(rel)) continue;
    const text = readFileSync(join(dist, rel), "utf8");
    for (const k of CR23_DATA_KEYS) if (text.includes(`"${k}"`) || text.includes(`&quot;${k}&quot;`) || text.includes(`&#34;${k}&#34;`)) leaks.push(`${rel}: carries the CR2/CR3-only key "${k}"`);
    if (!rel.endsWith(".html")) continue;
    if (linkRx.some((rx) => rx.test(text))) leaks.push(`${rel}: links a CR2/CR3 page`);
    for (const m of text.matchAll(MARKER_RX)) if (cr23Markers.includes(m[1])) leaks.push(`${rel}: carries the CR2/CR3 marker ${ROOM_MARKER}="${m[1]}"`);
  }
  return leaks;
}

/** Every check over one dist (+ the committed owned_paths.json). */
export async function audit(dist, owned) {
  return {
    gatedPaths: await gatedPaths(dist),
    jsonFiles: jsonFiles(dist),
    sitemaps: sitemaps(dist),
    feeds: feeds(dist),
    ownedPaths: ownedPaths(owned),
    orphanChunks: orphanChunks(dist),
    cr1Leaks: cr1Leaks(dist),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dist = resolve(process.argv[2] || join(WWW, "dist"));
  const result = await audit(dist);
  const leaks = Object.entries(result).flatMap(([k, v]) => v.map((l) => `${k}: ${l}`));
  for (const l of leaks) console.log(`  ✗ ${l}`);
  console.log(leaks.length ? `room audit: ${leaks.length} leak(s) in ${dist}` : `room audit: clean — no Coaching Room route, data, sitemap entry, feed, owned path or chunk in ${dist}`);
  process.exit(leaks.length ? 1 : 0);
}

// www/scripts/room_audit.mjs — is the Coaching Room ABSENT from a flag-off dist? (CR1, built dark; src/lib/room.js)
//
// The owner's bar (2026-11-08): with WEB_ROOM off, unpublished routes, generated content and supporting assets must
// be absent from the production artifact, not merely unlinked. Six checks, each pure over a dist directory (or the
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
//                   no asset is named for the room; no page carries the room marker
//
// CLI: node scripts/room_audit.mjs [dist]  → prints the leaks, exit 1 when any.
import { createServer } from "node:http";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { ROOM_DATA_KEYS, ROOM_MARKER, ROOM_ROUTES, roomPathPattern } from "../src/lib/room.js";

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

/**
 * The concrete room paths to request from a dist. A literal path is itself; a `[param]` path (CR2's per-coach record,
 * `/system/coaches/[id]/record/`) is expanded over every directory the dist holds at the param's place (each coach page
 * the build emitted) plus one probe id, so a dist with no coach pages is still asked.
 */
export function roomPaths(dist) {
  const out = [];
  for (const r of ROOM_ROUTES) {
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
const roomRx = () => ROOM_ROUTES.map((r) => new RegExp(`${roomPathPattern(r.path.slice(0, -1))}(/|")`));
const namesRoom = (text) => roomRx().some((rx) => rx.test(text));

/** Serve dist as the S3 website origin does (`/x/` → `x/index.html`, a missing object → 404) and GET each room path. */
export async function gatedPaths(dist) {
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
    for (const path of roomPaths(dist)) {
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

export function jsonFiles(dist, declared = declaredJson()) {
  const leaks = [];
  for (const rel of files(dist).filter((f) => f.endsWith(".json"))) {
    if (!declared.some((rx) => rx.test(rel))) leaks.push(`${rel}: a JSON file no src/pages endpoint declares`);
    const text = readFileSync(join(dist, rel), "utf8");
    for (const k of ROOM_DATA_KEYS) if (text.includes(`"${k}"`)) leaks.push(`${rel}: carries the room-only key "${k}"`);
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
  for (const key of ["routes", "static_routes", "route_patterns", "files"]) {
    // a room path, or anything under one, with or without its leading slash (`[param]` = one segment)
    const rxs = ROOM_ROUTES.map((r) => new RegExp(`^/?${roomPathPattern(r.path.slice(1))}`));
    for (const v of owned[key] || []) if (rxs.some((rx) => rx.test(v))) leaks.push(`owned_paths.json ${key}: ${v}`);
  }
  return leaks;
}

/** An asset named for the room: "room", or any room page's entrypoint name (calibration, coach-record), read off ROOM_ROUTES. */
const ROOM_ASSET_NAMES = new RegExp(
  ["room", ...ROOM_ROUTES.map((r) => r.entrypoint.replace(/^.*\//, "").replace(/\.astro$/, ""))].map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"),
  "i"
);

export function orphanChunks(dist) {
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
    if (html.includes(`${ROOM_MARKER}=`)) leaks.push(`${p}: carries the room marker ${ROOM_MARKER}`);
    scanText(html);
  }
  while (queue.length) scanText(readFileSync(join(dist, queue.shift()), "utf8"));
  for (const a of assets) {
    if (!seen.has(a)) leaks.push(`${a}: an asset no built page reaches (built for a page that is not in this dist)`);
    if (ROOM_ASSET_NAMES.test(a)) leaks.push(`${a}: an asset named for the room`);
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

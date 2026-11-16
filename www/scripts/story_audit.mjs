// www/scripts/story_audit.mjs — is the Human Story ABSENT from a flag-off dist? (HS1, built dark; src/lib/story_dark.js)
//
// The same bar as the Coaching Room (scripts/room_audit.mjs, CR1): with WEB_STORY off, the timeline, the episode index,
// the "story so far" entry, their data and their assets must be absent from the production artifact, not merely
// unlinked. Six checks, each pure over a dist directory (or the committed owned_paths.json), each returning the leaks it
// found ([] = clean). tests/story_dark.test.mjs runs every one on the real flag-off build AND on a planted copy (the
// mutation control). The master proof is the byte-identical recursive diff against a build of main from the same
// snapshot. The directory walk and the declared-endpoint matcher are room_audit.mjs's, reused rather than copied.
//
//   gatedPaths      a direct request for every story path is a 404 (served as S3 would: no object, no page)
//   jsonFiles       every .json in dist is a declared src/pages endpoint, and none carries a story-only data key
//   sitemaps        no sitemap file lists a story path
//   feeds           no feed / search index beyond the sitemaps, and nothing machine-readable names a story path
//   ownedPaths      the committed owned_paths.json names no story path
//   orphanChunks    every _astro/ asset is reachable from a built page; no asset is named for the story build;
//                   no page carries the story marker
//
// CLI: node scripts/story_audit.mjs [dist]  → prints the leaks, exit 1 when any.
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { STORY_DATA_FILE, STORY_DATA_KEYS, STORY_MARKER, STORY_ROUTES } from "../src/lib/story_dark.js";
import { declaredJson, walk } from "./room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const posix = (p) => p.split(sep).join("/");
const files = (dist) => walk(dist).map((p) => posix(relative(dist, p)));
const storyPaths = () => STORY_ROUTES.map((r) => r.path);
const namesStory = (text) => storyPaths().some((p) => text.includes(p) || text.includes(p.slice(0, -1) + '"'));
/** An asset name only a story build would produce (the two gated entrypoints, the helper modules, the data file). */
const STORY_ASSET = /(^|[/._-])(timeline|episodes|story_dark|StoryEntry|story\.json)([._-]|$)/i;

/** Serve dist as the S3 website origin does (`/x/` → `x/index.html`, a missing object → 404) and GET each story path. */
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
    for (const path of [...storyPaths(), `/${STORY_DATA_FILE}`, `/story/${STORY_DATA_FILE}`]) {
      const variants = path.endsWith("/") ? [path, path.slice(0, -1), `${path}index.html`] : [path];
      for (const variant of variants) {
        const r = await fetch(`http://127.0.0.1:${port}${variant}`);
        if (r.status !== 404) leaks.push(`${variant} answered ${r.status} (expected 404)`);
      }
    }
  } finally {
    server.close();
  }
  return leaks;
}

export function jsonFiles(dist, declared = declaredJson()) {
  const leaks = [];
  for (const rel of files(dist).filter((f) => f.endsWith(".json"))) {
    if (!declared.some((rx) => rx.test(rel))) leaks.push(`${rel}: a JSON file no src/pages endpoint declares`);
    const text = readFileSync(join(dist, rel), "utf8");
    for (const k of STORY_DATA_KEYS) if (text.includes(`"${k}"`)) leaks.push(`${rel}: carries the story-only key "${k}"`);
  }
  return leaks;
}

export function sitemaps(dist) {
  return files(dist)
    .filter((f) => /^sitemap[^/]*\.xml$/.test(f))
    .filter((f) => namesStory(readFileSync(join(dist, f), "utf8")))
    .map((f) => `${f}: lists a story path`);
}

const FEED_LIKE = /\.(xml|rss|atom|txt|webmanifest)$|(^|\/)(pagefind|search|feed)[^/]*(\/|$)|index\.json$/i;
export function feeds(dist) {
  const leaks = [];
  for (const rel of files(dist)) {
    const sitemap = /^sitemap[^/]*\.xml$/.test(rel);
    if (FEED_LIKE.test(rel) && !sitemap) leaks.push(`${rel}: a feed or search index the build did not emit before the story`);
    if (/\.(xml|rss|atom|txt|json|webmanifest)$/.test(rel) && namesStory(readFileSync(join(dist, rel), "utf8"))) leaks.push(`${rel}: names a story path`);
  }
  return leaks;
}

export function ownedPaths(owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"))) {
  const leaks = [];
  for (const key of ["routes", "static_routes", "route_patterns", "files"]) {
    for (const v of owned[key] || []) {
      if (storyPaths().some((p) => v === p || v.startsWith(p) || v === p.slice(1) || v.startsWith(p.slice(1)))) leaks.push(`owned_paths.json ${key}: ${v}`);
      if (v === STORY_DATA_FILE || v.endsWith(`/${STORY_DATA_FILE}`)) leaks.push(`owned_paths.json ${key}: ${v}`);
    }
  }
  return leaks;
}

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
    if (html.includes(`${STORY_MARKER}=`)) leaks.push(`${p}: carries the story marker ${STORY_MARKER}`);
    scanText(html);
  }
  while (queue.length) scanText(readFileSync(join(dist, queue.shift()), "utf8"));
  for (const a of assets) {
    if (!seen.has(a)) leaks.push(`${a}: an asset no built page reaches (built for a page that is not in this dist)`);
    if (STORY_ASSET.test(a)) leaks.push(`${a}: an asset named for the story build`);
  }
  for (const f of all) if (f === STORY_DATA_FILE || f.endsWith(`/${STORY_DATA_FILE}`)) leaks.push(`${f}: the story's data file`);
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
  console.log(leaks.length ? `story audit: ${leaks.length} leak(s) in ${dist}` : `story audit: clean — no Human Story route, data, sitemap entry, feed, owned path, chunk or marker in ${dist}`);
  process.exit(leaks.length ? 1 : 0);
}

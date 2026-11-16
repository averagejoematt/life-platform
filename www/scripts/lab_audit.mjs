// www/scripts/lab_audit.mjs — is the Laboratory ABSENT from a flag-off dist? (L1, built dark; src/lib/lab.js)
//
// The owner's bar (2026-11-08, the same as the Coaching Room's): with WEB_LAB off, unpublished routes, generated content
// and supporting assets must be absent from the production artifact, not merely unlinked. Six checks, each pure over a
// dist directory (or the committed owned_paths.json), each returning the leaks it found ([] = clean).
// tests/lab.test.mjs runs every one on the real flag-off build AND on a planted copy (the mutation control: each check
// must see its planted leak). The master proof is the byte-identical recursive diff against a build of main from the
// same snapshot. Mirrors scripts/room_audit.mjs (whose helpers it reuses), for the Lab's own routes, data and marker.
//
//   gatedPaths      a direct request for every Lab path (and a sampled object page) is a 404; no file sits under /data/lab/
//   jsonFiles       every .json in dist is a declared src/pages endpoint; none is the Lab's data file or carries a Lab-only key
//   sitemaps        no sitemap file lists a Lab path
//   feeds           no feed / search index beyond the sitemaps, and nothing machine-readable names a Lab path
//   ownedPaths      the committed owned_paths.json names no Lab path
//   orphanChunks    every _astro/ asset is reachable from a built page; no asset is named for the Lab; no page carries
//                   the Lab marker
//
// CLI: node scripts/lab_audit.mjs [dist]  → prints the leaks, exit 1 when any.
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { LAB_DATA_FILE, LAB_DATA_KEYS, LAB_MARKER, LAB_ROOT, LAB_ROUTES } from "../src/lib/lab.js";
import { declaredJson, walk } from "./room_audit.mjs";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const posix = (p) => p.split(sep).join("/");
const files = (dist) => walk(dist).map((p) => posix(relative(dist, p)));
const labPaths = () => LAB_ROUTES.map((r) => r.path);
const namesLab = (text) => text.includes(LAB_ROOT) || text.includes(LAB_ROOT.slice(0, -1) + '"');
/** An asset named for the Lab: the Lab's page entrypoints are lab-*.astro, its island and libraries lab*.js. */
export const LAB_ASSET = /(^|\/)(lab[-._]|laborator)/i;

/** One object page per dynamic route, sampled from the committed fixture (a 404 for the route's directory alone could
 *  hide an object page that answers 200). */
export function probes(fixture = join(WWW, "content", "fixtures", LAB_DATA_FILE)) {
  const out = [...labPaths()];
  try {
    const lab = JSON.parse(readFileSync(fixture, "utf8"));
    const x = (lab.lab_experiments || [])[0];
    const t = (lab.lab_tests || [])[0];
    if (x) out.push(`/data/lab/experiments/${x.id}/`);
    if (t) out.push(`/data/lab/tests/${t.id}/`);
  } catch {
    /* no fixture: the route directories are still probed */
  }
  return out;
}

/** Serve dist as the S3 website origin does (`/x/` → `x/index.html`, a missing object → 404) and GET each Lab path. */
export async function gatedPaths(dist, paths = probes()) {
  const leaks = files(dist)
    .filter((f) => f.startsWith(LAB_ROOT.slice(1)))
    .map((f) => `${f}: a file under ${LAB_ROOT} in the dist`);
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
  try {
    for (const path of paths) {
      for (const variant of [path, path.slice(0, -1), `${path}index.html`]) {
        const r = await fetch(`http://127.0.0.1:${port}${variant}`);
        await r.arrayBuffer();
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
    if (rel.split("/").pop() === LAB_DATA_FILE) leaks.push(`${rel}: the Lab's data file`);
    if (!declared.some((rx) => rx.test(rel))) leaks.push(`${rel}: a JSON file no src/pages endpoint declares`);
    const text = readFileSync(join(dist, rel), "utf8");
    for (const k of LAB_DATA_KEYS) if (text.includes(`"${k}"`)) leaks.push(`${rel}: carries the Lab-only key "${k}"`);
  }
  return leaks;
}

export function sitemaps(dist) {
  return files(dist)
    .filter((f) => /^sitemap[^/]*\.xml$/.test(f))
    .filter((f) => namesLab(readFileSync(join(dist, f), "utf8")))
    .map((f) => `${f}: lists a Lab path`);
}

const FEED_LIKE = /\.(xml|rss|atom|txt|webmanifest)$|(^|\/)(pagefind|search|feed)[^/]*(\/|$)|index\.json$/i;
export function feeds(dist) {
  const leaks = [];
  for (const rel of files(dist)) {
    const sitemap = /^sitemap[^/]*\.xml$/.test(rel);
    if (FEED_LIKE.test(rel) && !sitemap) leaks.push(`${rel}: a feed or search index the build did not emit before the Lab`);
    if (/\.(xml|rss|atom|txt|json|webmanifest)$/.test(rel) && namesLab(readFileSync(join(dist, rel), "utf8"))) leaks.push(`${rel}: names a Lab path`);
  }
  return leaks;
}

export function ownedPaths(owned = JSON.parse(readFileSync(join(WWW, "owned_paths.json"), "utf8"))) {
  const leaks = [];
  const root = LAB_ROOT;
  for (const key of ["routes", "static_routes", "route_patterns", "files"]) {
    for (const v of owned[key] || []) if (v === root.slice(0, -1) || v.startsWith(root) || v.startsWith(root.slice(1))) leaks.push(`owned_paths.json ${key}: ${v}`);
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
    if (html.includes(`${LAB_MARKER}=`)) leaks.push(`${p}: carries the Lab marker ${LAB_MARKER}`);
    scanText(html);
  }
  while (queue.length) scanText(readFileSync(join(dist, queue.shift()), "utf8"));
  for (const a of assets) {
    if (!seen.has(a)) leaks.push(`${a}: an asset no built page reaches (built for a page that is not in this dist)`);
    if (LAB_ASSET.test(a.slice("_astro/".length))) leaks.push(`${a}: an asset named for the Lab`);
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
  console.log(leaks.length ? `lab audit: ${leaks.length} leak(s) in ${dist}` : `lab audit: clean — no Laboratory route, data, sitemap entry, feed, owned path or chunk in ${dist}`);
  process.exit(leaks.length ? 1 : 0);
}

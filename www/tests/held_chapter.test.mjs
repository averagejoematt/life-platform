// A HELD chapter has no public page (owner ruling 2026-11-10, item 5): a week whose installment is drafted but not
// approved gets no route, no sitemap entry and no link — its state may be said in words where the week is listed,
// never as a destination. Two halves:
//   * the rule — url.js::hasPage, and the rail filter edges.js::connected({ keep }) every Connected rail goes through;
//   * the built dist (CI: the fixture build scripts/check_www_build.py leaves in www/dist, whose fixture carries one
//     held chapter) — no page, no sitemap <loc>, no href for any held chapter in the snapshot it was built from; each
//     check is also run on a planted copy, where it must find the leak it exists to find (the mutation control).
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { hasPage } from "../src/lib/url.js";
import { buildIndex, connected } from "../src/lib/edges.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = resolve(process.env.HELD_AUDIT_DIST || join(WWW, "dist"));
const SNAPSHOT = join(WWW, "content", "snapshot", "chapters.json");
const HAVE_DIST = existsSync(join(DIST, "index.html")) && existsSync(SNAPSHOT);

function heldIds() {
  const raw = JSON.parse(readFileSync(SNAPSHOT, "utf8"));
  const list = Array.isArray(raw) ? raw : raw.chapters || raw.items || [];
  return list.filter((c) => c.status === "held").map((c) => c.id);
}

function htmlFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) htmlFiles(p, out);
    else if (name.endsWith(".html") || name.endsWith(".xml")) out.push(p);
  }
  return out;
}

/** Every leak of a held chapter in a dist: its page directory, a sitemap <loc>, an href. */
function leaks(dist, ids) {
  const found = [];
  for (const id of ids) {
    const path = `/story/${id}/`;
    if (existsSync(join(dist, "story", id))) found.push(`page ${path}`);
    for (const f of htmlFiles(dist)) {
      const s = readFileSync(f, "utf8");
      if (s.includes(`href="${path}"`) || s.includes(`href="${path}#`)) found.push(`href ${path} in ${f.slice(dist.length)}`);
      if (s.includes(`${path}</loc>`)) found.push(`sitemap ${path} in ${f.slice(dist.length)}`);
    }
  }
  return found;
}

test("hasPage: a held chapter has no page; published, skipped and pending chapters do; other types always do", () => {
  assert.equal(hasPage("chapter", { status: "held" }), false);
  for (const status of ["published", "skipped", "pending"]) assert.equal(hasPage("chapter", { status }), true, status);
  assert.equal(hasPage("chapter", null), false);
  assert.equal(hasPage("day", { status: "held" }), true);
});

test("connected({ keep }): a row the predicate refuses is not a row, and is not counted", () => {
  const objects = [
    { type: "day", id: "d1", edges: [{ type: "chapter", id: "held-8" }, { type: "metric", id: "weight" }] },
    { type: "chapter", id: "held-8", status: "held", edges: [] },
    { type: "metric", id: "weight", edges: [] },
  ];
  const index = buildIndex(objects);
  const byId = new Map(objects.map((o) => [`${o.type}:${o.id}`, o]));
  const open = connected(index, "day", "d1");
  assert.deepEqual(open.items.map((e) => e.id), ["held-8", "weight"], "control: without keep the held chapter is a row");
  const kept = connected(index, "day", "d1", { keep: (e) => hasPage(e.type, byId.get(`${e.type}:${e.id}`)) });
  assert.deepEqual(kept.items.map((e) => e.id), ["weight"]);
  assert.equal(kept.total, 1);
});

test("the built dist carries no page, sitemap entry or link for a held chapter (control: a planted page, link and loc)", { skip: !HAVE_DIST && "no www/dist + content/snapshot (build first)" }, () => {
  const ids = heldIds();
  assert.ok(ids.length > 0, "the snapshot this dist was built from carries a held chapter (the fixture does)");
  assert.deepEqual(leaks(DIST, ids), []);

  const dir = mkdtempSync(join(tmpdir(), "held-audit-"));
  try {
    cpSync(DIST, dir, { recursive: true });
    const id = ids[0];
    mkdirSync(join(dir, "story", id), { recursive: true });
    writeFileSync(join(dir, "story", id, "index.html"), "<p>Held.</p>");
    writeFileSync(join(dir, "planted.html"), `<a href="/story/${id}/">Week</a>`);
    writeFileSync(join(dir, "planted-sitemap.xml"), `<url><loc>https://averagejoematt.com/story/${id}/</loc></url>`);
    const found = leaks(dir, [id]);
    assert.ok(found.some((f) => f.startsWith("page ")), "control: the planted page is found");
    assert.ok(found.some((f) => f.startsWith("href ")), "control: the planted link is found");
    assert.ok(found.some((f) => f.startsWith("sitemap ")), "control: the planted sitemap entry is found");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

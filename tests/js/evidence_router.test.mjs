// tests/js/evidence_router.test.mjs — unit tests for evidence.js's router
// mapping (#1431), split into site/assets/js/evidence_router.js specifically
// so it's testable without executing evidence.js's DOM side effects (see that
// module's header comment). evidence.js is the shared archive router behind
// ~30 /data/ + /protocols/ + /method/ topic pages — a bug in the unlisted
// filter or the slug resolver silently breaks direct-URL routing or leaks an
// unlisted topic (e.g. /data/ledger/) onto the tile rail.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { indexRegistry, resolveSlugFromPath } from "../../site/assets/js/evidence_router.js";

const REG = [
  { slug: "vitals", title: "Vitals", group: "the body" },
  { slug: "labs", title: "Labs", group: "the body" },
  { slug: "ledger", title: "Ledger", group: "mind & accountability", unlisted: true },
  { slug: "habits", title: "Habits", group: "mind & accountability" },
];

test("indexRegistry — BYSLUG keeps every entry, including unlisted ones", () => {
  const { BYSLUG } = indexRegistry(REG);
  assert.equal(Object.keys(BYSLUG).length, 4);
  assert.equal(BYSLUG.ledger.title, "Ledger");
  assert.equal(BYSLUG.vitals.group, "the body");
});

test("indexRegistry — LISTED drops unlisted entries (#1109), keeps the rest in order", () => {
  const { LISTED } = indexRegistry(REG);
  assert.deepEqual(LISTED.map((t) => t.slug), ["vitals", "labs", "habits"]);
});

test("indexRegistry — GROUPS is the de-duped, first-seen-order set of LISTED groups", () => {
  const { GROUPS } = indexRegistry(REG);
  assert.deepEqual(GROUPS, ["the body", "mind & accountability"]);
});

test("indexRegistry — an unlisted-only group never surfaces in GROUPS", () => {
  const reg = [{ slug: "a", group: "solo-unlisted", unlisted: true }, { slug: "b", group: "real" }];
  const { GROUPS } = indexRegistry(reg);
  assert.deepEqual(GROUPS, ["real"]);
});

test("indexRegistry — an empty/missing registry indexes to empty views, not a throw", () => {
  assert.deepEqual(indexRegistry([]), { BYSLUG: {}, LISTED: [], GROUPS: [] });
  assert.deepEqual(indexRegistry(undefined), { BYSLUG: {}, LISTED: [], GROUPS: [] });
});

test("resolveSlugFromPath — the last non-empty path segment is the slug", () => {
  assert.equal(resolveSlugFromPath("/data/labs/"), "labs");
  assert.equal(resolveSlugFromPath("/data/labs"), "labs"); // no trailing slash still resolves
  assert.equal(resolveSlugFromPath("/protocols/training/"), "training");
});

test("resolveSlugFromPath — a single-segment path resolves to that one segment", () => {
  // "/data/" has exactly one non-empty segment ("data") — the router's caller
  // (evidence.js's popstate handler) is the one that knows "data" isn't a
  // real topic slug and falls back to the current selection; this function's
  // only job is "last non-empty segment", honestly, with no topic awareness.
  assert.equal(resolveSlugFromPath("/data/"), "data");
});

test("resolveSlugFromPath — the true root (no segment at all) resolves to empty", () => {
  assert.equal(resolveSlugFromPath("/"), "");
  assert.equal(resolveSlugFromPath(""), "");
});

test("resolveSlugFromPath — a null/undefined pathname never throws", () => {
  assert.equal(resolveSlugFromPath(null), "");
  assert.equal(resolveSlugFromPath(undefined), "");
});

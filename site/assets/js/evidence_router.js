/*
  evidence_router.js — the pure slug/registry mapping split out of evidence.js
  (#1431). evidence.js's router logic (BYSLUG/LISTED/GROUPS derivation + the
  current-slug-from-path resolver) previously lived inline as module-scope
  consts wired straight to `window.__EVIDENCE_REGISTRY__` and `location` — both
  browser globals unavailable in a plain Node unit test, AND evidence.js itself
  runs a chain of DOM side effects at import time (initTheme/buildTabs/
  buildSide/renderCenter/stampGenesis all fire at the bottom of the module), so
  importing evidence.js to test just the mapping logic would drag in the whole
  DOM-wiring path. Splitting these two functions out — no behavior change,
  same pattern evidence_shared.js used at #581 — makes the router mapping
  unit-testable on its own.
*/

// Index a build-time registry (window.__EVIDENCE_REGISTRY__ shape, embedded by
// scripts/v4_build_evidence.py: [{slug,title,blurb,group,mode,endpoint,root,
// legacy,editorial,unlisted}]) into the three derived views the router needs.
//
// BYSLUG keeps EVERY entry — an unlisted topic's direct URL (e.g. /data/ledger/)
// must still route + render.
// LISTED drops `unlisted` entries (#1109) — only the menu surfaces (tile rail,
// group tabs, "all N topics" count) use this view; direct URLs bypass it via
// BYSLUG.
// GROUPS is the ordered set of groups present among LISTED entries, in
// first-seen order (the tab bar's order).
export function indexRegistry(reg) {
  const list = reg || [];
  const BYSLUG = Object.fromEntries(list.map((t) => [t.slug, t]));
  const LISTED = list.filter((t) => !t.unlisted);
  const GROUPS = [...new Set(LISTED.map((t) => t.group))];
  return { BYSLUG, LISTED, GROUPS };
}

// The current topic slug is the last non-empty path segment, e.g.
// "/data/labs/" -> "labs", "/data/" -> "", "/data" -> "data".
export function resolveSlugFromPath(pathname) {
  const seg = String(pathname || "").split("/").filter(Boolean);
  return seg.length ? seg[seg.length - 1] : "";
}

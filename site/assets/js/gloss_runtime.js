/*
  gloss_runtime.js — the runtime half of the site glossary (#4182, M2).
  ----------------------------------------------------------------------------
  scripts/v4_glossary.py glosses every registered term's first appearance in the STATIC
  HTML at build time. Most reader pages then render their numbers and prose from /api/*
  in the browser, and that text is invisible to a build step. This pass closes the gap:
  a debounced MutationObserver on <main> wraps the first appearance of each registered
  term that the page has not glossed yet, via orient.js::glossFirst with {ci:true}.

  The registry is site/data/glossary.json; glossary_terms.js is its GENERATED copy
  (`python3 scripts/v4_glossary.py --emit-js`). Served coach text is fenced
  `[data-verbatim]` and never touched. Loaded once per page from the canonical footer
  (scripts/v4_chrome.site_footer).
*/
import { GLOSSARY_TERMS } from "/assets/js/glossary_terms.js";
import { glossFirst } from "/assets/js/orient.js";

const DEBOUNCE_MS = 250;

function glossedAlready(root) {
  const have = new Set();
  root.querySelectorAll("dfn.gloss, abbr.gloss").forEach((el) => have.add(el.textContent.trim().toLowerCase()));
  return have;
}

export function glossPass(root) {
  if (!root) return 0;
  const have = glossedAlready(root);
  let n = 0;
  for (const t of GLOSSARY_TERMS) {
    if (have.has(t.term.toLowerCase())) continue;
    if (glossFirst(root, t.term, t.gloss, { ci: t.ci })) n += 1;
  }
  return n;
}

function start() {
  const main = document.querySelector("main");
  if (!main || typeof MutationObserver === "undefined") return;
  let timer = null;
  let busy = false;
  const run = () => {
    timer = null;
    busy = true;
    try { glossPass(main); } finally { busy = false; }
  };
  new MutationObserver(() => {
    if (busy || timer) return;
    timer = setTimeout(run, DEBOUNCE_MS);
  }).observe(main, { childList: true, subtree: true, characterData: true });
  run();
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
}

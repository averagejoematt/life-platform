#!/usr/bin/env node
// scripts/import_site_js_graph.mjs — real import() of the full site JS module graph (#1432).
//
// WHY: `node --check` only PRE-PARSES function bodies (V8 lazy compilation) — a
// `const` redeclared inside an already-large function body passes `--check` (even
// with `--input-type=module`, the flag the existing deploy-time gate in
// deploy/sync_site_to_s3.sh uses) but throws a real SyntaxError on full parse. That's
// exactly what happened in story.js (2026-07-12, PR #1156 → hotfix #1159, memory
// reference_node_check_lazy_parse) — the bug shipped past the parse gate and blocked
// site publish downstream. A genuine `import()` forces Node to fully parse the ENTIRE
// module source — every function body, not just the outer shape — before any code
// runs. That's the guarantee `--check` can't give, at any flag setting.
//
// WHAT THIS DOES: imports every .js file under site/assets/js/ as an ES module (via
// scripts/site_js_loader.mjs, which teaches Node the site's root-relative import
// specifiers — e.g. "/assets/js/theme.js" — and forces ESM parsing for a
// no-package.json static site). Two files (agents.js, motion.js) are authored as
// classic <script> tags, not ES modules — no import/export. They're imported anyway:
// a script with no import/export is still valid to load as a module (it just runs as
// a plain IIFE with no exports), and doing so gets the SAME full-parse guarantee for
// their function bodies. That's a deliberate choice, not an oversight — see the
// CLASSIC_SCRIPTS comment below.
//
// RUNS FROM A MINIMAL BROWSER SHIM (document/window/etc.) so top-level module code
// that touches the DOM doesn't immediately throw a ReferenceError before its own
// guards (readyState checks, `if (el)`, try/catch) get a chance to run. The shim is
// deliberately NOT a full DOM (no jsdom dependency — keeps this fast and dependency-
// free) — just enough surface for those guards to take their normal branch.
//
// FAIL CONDITION: only a SyntaxError fails this gate. A runtime error past that point
// (e.g. a shim gap) is logged as a non-fatal warning — this gate's job is full-depth
// SYNTAX verification, not full runtime behavior; real DOM execution is already
// covered by tests/pr_render_gate.py / visual QA (an actual Playwright browser against
// a mocked API). Conflating the two would make this gate flaky on shim gaps instead of
// reliable on the one thing node --check can't do.
import { register } from "node:module";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..");
const JS_DIR = path.join(REPO_ROOT, "site", "assets", "js");

register("./site_js_loader.mjs", import.meta.url);

// ── Minimal browser-global shim ─────────────────────────────────────────────
function makeElement(tag = "div") {
  const classSet = new Set();
  const el = {
    tagName: String(tag).toUpperCase(),
    children: [],
    attributes: {},
    dataset: {},
    style: {},
    hidden: false,
    disabled: false,
    textContent: "",
    innerHTML: "",
    value: "",
    classList: {
      add: (...c) => c.forEach((x) => classSet.add(x)),
      remove: (...c) => c.forEach((x) => classSet.delete(x)),
      toggle: (c, force) => {
        const on = force === undefined ? !classSet.has(c) : force;
        on ? classSet.add(c) : classSet.delete(c);
        return on;
      },
      contains: (c) => classSet.has(c),
    },
    setAttribute(name, val) {
      this.attributes[name] = String(val);
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
    hasAttribute(name) {
      return name in this.attributes;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    append() {},
    prepend() {},
    remove() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return true;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    closest() {
      return null;
    },
    matches() {
      return false;
    },
    getBoundingClientRect() {
      return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
    },
    getTotalLength() {
      return 0;
    },
    focus() {},
    blur() {},
    click() {},
    cloneNode() {
      return makeElement(tag);
    },
    scrollIntoView() {},
  };
  return el;
}

class ObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

function makeStorage() {
  const store = new Map();
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  };
}

const documentElement = makeElement("html");
const body = makeElement("body");
const head = makeElement("head");

globalThis.document = {
  documentElement,
  body,
  head,
  title: "",
  readyState: "complete", // so `if (document.readyState === "loading")` guards skip straight to the ready branch
  createElement: (tag) => makeElement(tag),
  createElementNS: (_ns, tag) => makeElement(tag),
  createTextNode: (text) => ({ nodeType: 3, textContent: String(text) }),
  createDocumentFragment: () => makeElement("#fragment"),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {
    return true;
  },
  cookie: "",
};
// Node 21+ ships a built-in read-only `navigator` global — redefine it rather than
// assign (a plain assignment throws: "Cannot set property navigator ... only a getter").
Object.defineProperty(globalThis, "navigator", {
  value: { userAgent: "site-js-graph-import-check", language: "en-US" },
  writable: true,
  configurable: true,
});
globalThis.localStorage = makeStorage();
globalThis.sessionStorage = makeStorage();
globalThis.matchMedia = () => ({
  matches: false,
  media: "",
  addListener() {},
  removeListener() {},
  addEventListener() {},
  removeEventListener() {},
});
globalThis.IntersectionObserver = ObserverStub;
globalThis.MutationObserver = ObserverStub;
globalThis.ResizeObserver = ObserverStub;
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
if (typeof globalThis.CustomEvent !== "function") {
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, opts = {}) {
      this.type = type;
      this.detail = opts.detail;
      this.bubbles = !!opts.bubbles;
    }
  };
}
globalThis.location = {
  href: "https://averagejoematt.com/",
  pathname: "/",
  search: "",
  hash: "",
  origin: "https://averagejoematt.com",
};
// Never let a module make a real network call during this check — fail closed, fast,
// synchronously-guarded (getJSON-style helpers in this codebase already try/catch fetch).
globalThis.fetch = async () => {
  throw new Error("network disabled in the JS module-graph import check");
};
// A plain `globalThis.window = globalThis` alias looks tempting but Node's global
// object is NOT an EventTarget (no addEventListener/dispatchEvent) — several modules
// call `window.addEventListener("resize", …)` at module scope, which would throw.
// Give window its own small stub instead.
globalThis.window = {
  document: globalThis.document,
  navigator: globalThis.navigator,
  localStorage: globalThis.localStorage,
  sessionStorage: globalThis.sessionStorage,
  location: globalThis.location,
  matchMedia: globalThis.matchMedia,
  fetch: globalThis.fetch,
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {
    return true;
  },
  requestAnimationFrame: globalThis.requestAnimationFrame,
  cancelAnimationFrame: globalThis.cancelAnimationFrame,
  setTimeout: globalThis.setTimeout,
  clearTimeout: globalThis.clearTimeout,
  setInterval: globalThis.setInterval,
  clearInterval: globalThis.clearInterval,
  CustomEvent: globalThis.CustomEvent,
  innerWidth: 1280,
  innerHeight: 800,
  devicePixelRatio: 1,
};

// ── Classic (non-module) site scripts ───────────────────────────────────────
// agents.js and motion.js are shipped as plain <script src="..."> tags (no
// import/export) — not part of the ESM import graph any page pulls in via
// evidence.js's import chain. They're still imported here as modules: a script
// with no import/export is valid to load as a module (runs as a no-export IIFE),
// and doing so gets them the SAME full-parse guarantee this gate exists for. Not
// exempted — explicitly included.
const CLASSIC_SCRIPTS = new Set(["agents.js", "motion.js"]);

async function main() {
  if (!fs.existsSync(JS_DIR)) {
    console.error(`❌ site JS directory not found: ${JS_DIR}`);
    process.exit(1);
  }
  const files = fs
    .readdirSync(JS_DIR)
    .filter((f) => f.endsWith(".js"))
    .sort();

  if (!files.length) {
    console.error(`❌ no .js files found under ${JS_DIR} — resolver or repo layout changed?`);
    process.exit(1);
  }

  console.log(`→ importing ${files.length} site JS module(s) from ${path.relative(REPO_ROOT, JS_DIR)}/ …`);

  let failures = 0;
  let warnings = 0;
  for (const file of files) {
    const abs = path.join(JS_DIR, file);
    const tag = CLASSIC_SCRIPTS.has(file) ? " (classic script, imported as module for full-parse coverage)" : "";
    try {
      await import(pathToFileURL(abs).href);
      console.log(`  ok    ${file}${tag}`);
    } catch (err) {
      const isSyntax = err instanceof SyntaxError;
      if (isSyntax) {
        failures++;
        console.error(`  FAIL  ${file}${tag} — SyntaxError: ${err.message}`);
      } else {
        warnings++;
        console.log(`  warn  ${file}${tag} — ${err.constructor.name}: ${err.message} (non-fatal: runtime-only, not a parse error)`);
      }
    }
  }

  console.log(`\n${files.length} module(s) imported — ${failures} syntax failure(s), ${warnings} non-fatal runtime warning(s).`);

  if (failures > 0) {
    console.error(
      "\n❌ JS MODULE GRAPH IMPORT FAILED — a full parse caught a SyntaxError that `node --check` " +
        "misses (e.g. a function-body const redeclaration, #1156). Publish blocked."
    );
    process.exit(1);
  }
  console.log("✓ full site JS module graph parses clean (real import(), not node --check).");
  // motion.js (deliberately imported, see CLASSIC_SCRIPTS above) arms a real
  // `setInterval` at module scope — that keeps a bare Node process alive forever, so
  // exit explicitly on the known-good path rather than waiting on the event loop to
  // drain on its own.
  process.exit(0);
}

main();

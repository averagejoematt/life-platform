// tests/js/support/loader.mjs — registers the site's root-relative "/assets/js/…"
// module resolver so these unit tests can `import` site/assets/js/*.js files
// directly, unmodified, the exact way a browser resolves them.
//
// Reuses scripts/site_js_loader.mjs (landed for #1432 — the JS module-graph
// import gate) rather than reinventing a second resolver: it rewrites a leading
// "/assets/…" specifier to the real path under site/assets/ and forces ESM
// parsing for a no-package.json-at-that-level static site. Side-effect import —
// every test file imports this first, before importing the module under test.
import { register } from "node:module";

// Guard against double-registration: node:test can load multiple test files
// into the same process depending on runner isolation settings, and this
// module gets imported once per test file.
if (!globalThis.__SITE_JS_LOADER_REGISTERED__) {
  register("../../../scripts/site_js_loader.mjs", import.meta.url);
  globalThis.__SITE_JS_LOADER_REGISTERED__ = true;
}

/*
  page_data.js (#3048) — reader for the per-page build-time data island.

  The archive/coaching/story shells used to carry their per-page data as inline
  `window.__*__ = ...` script blocks. Under the hardened CSP (script-src 'self',
  no 'unsafe-inline') executable inline blocks are gone; build-time data now
  ships as a non-executable JSON island the generators emit:

      <script type="application/json" id="page-data">{ ... }</script>

  type="application/json" is not executable, so it needs no script-src
  allowance. Malformed/absent islands read as {} — callers keep their own
  defaults, same as the old `window.X || fallback` idiom.
*/
export function pageData() {
  var el = document.getElementById("page-data");
  if (!el) return {};
  try {
    return JSON.parse(el.textContent) || {};
  } catch (e) {
    return {};
  }
}

// v7_shell.js — the v7 bar's state, nothing else (#4182).
//
// The builder (scripts/v7_build.py) already marks the current page's bar item with
// aria-current="page" at build time; this re-derives it from location.pathname so a page
// reached under a different base (the /next/ preview, a trailing-slash-less hit that the
// CloudFront function 301s) still lights the right item. No data, no fetches.
(function () {
  if (typeof document === "undefined") return;
  var run = function () {
    var bar = document.querySelector("nav.v7-bar");
    if (!bar) return;
    var here = (location.pathname || "/").replace(/\/?$/, "/");
    var links = bar.querySelectorAll("a[href]");
    var hit = null;
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      if (href.replace(/\/?$/, "/") === here) hit = links[i];
    }
    if (!hit) return;
    for (var j = 0; j < links.length; j++) links[j].removeAttribute("aria-current");
    hit.setAttribute("aria-current", "page");
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();

/* Standalone theme toggle for pages that do not load the module chrome
   (404, privacy). #3048 — extracted from the former inline block. */
(function(){
  var tb = document.querySelector(".theme-toggle");
  if (tb) tb.addEventListener("click", function(){
    var cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = cur === "light" ? "dark" : "light";
    try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {}
  });
})();

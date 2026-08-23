/* Motion-layer head guard (#3048 — extracted from the former inline head block).
   Fail-open: content shows if motion.js never runs; reduced-motion aware. */
(function(){try{if(!("IntersectionObserver" in window))return;if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;document.documentElement.classList.add("mo");window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();

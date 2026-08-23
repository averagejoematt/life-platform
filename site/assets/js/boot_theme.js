/* Pre-paint theme boot (#3048 — extracted from the former inline head block so the
   site CSP can drop 'unsafe-inline' for scripts). Loaded synchronously in <head>
   BEFORE first paint: parser blocks on this fetch, so no theme flash. */
(function(){try{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();

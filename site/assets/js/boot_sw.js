/* Service-worker registration (#3048 — extracted from the former inline block). */
if("serviceWorker" in navigator){window.addEventListener("load",function(){navigator.serviceWorker.register("/sw.js").catch(function(){});});}

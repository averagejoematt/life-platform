/*
  motion.js — v5 "alive" motion layer.
  ----------------------------------------------------------------------------
  Reveal-on-scroll (fade + rise), SVG chart draw-in, and an opt-in number
  count-up — all reduced-motion aware and FAIL-OPEN: the hidden state lives on
  `html.mo` (set by a tiny inline head script), and if this file never runs a
  head-side failsafe removes `.mo` so content is always shown. Works for
  statically-rendered AND SPA-injected content (MutationObserver).

  Pair with the inline head snippet:
    <script>(function(){try{if(!('IntersectionObserver'in window))return;
      if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
      document.documentElement.classList.add('mo');
      window.__moFail=setTimeout(function(){document.documentElement.classList.remove('mo');},2600);
    }catch(e){}})();</script>
*/
(function () {
  var root = document.documentElement;

  // ── Interactive line charts (ALWAYS on — interaction, not motion, so it runs even
  //    under prefers-reduced-motion). lineChart embeds data-cpts (normalized coords +
  //    label per point); we draw a focus dot + tooltip that track the cursor. ──
  function wireChart(svg) {
    if (svg.__ix) return; svg.__ix = 1;
    var cpts; try { cpts = JSON.parse(svg.getAttribute("data-cpts")); } catch (e) { return; }
    if (!cpts || !cpts.length) return;
    var fig = svg.closest(".chart"); if (!fig) return;
    if (getComputedStyle(fig).position === "static") fig.style.position = "relative";
    var dot = document.createElement("span"); dot.className = "chart-focus"; dot.hidden = true;
    var tip = document.createElement("span"); tip.className = "chart-tip label"; tip.hidden = true;
    fig.appendChild(dot); fig.appendChild(tip);
    svg.addEventListener("mousemove", function (e) {
      var r = svg.getBoundingClientRect(), fr = fig.getBoundingClientRect();
      var ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      var pt = cpts[Math.round(ratio * (cpts.length - 1))]; if (!pt) return;
      var px = (r.left - fr.left) + pt.x * r.width, py = (r.top - fr.top) + pt.y * r.height;
      dot.style.left = px + "px"; dot.style.top = py + "px"; dot.hidden = false;
      tip.textContent = pt.l; tip.style.left = px + "px"; tip.style.top = py + "px"; tip.hidden = false;
    });
    svg.addEventListener("mouseleave", function () { dot.hidden = true; tip.hidden = true; });
  }
  function wireCharts(scope) {
    if (!scope.querySelectorAll) return;
    Array.prototype.forEach.call(scope.querySelectorAll(".chart svg[data-cpts]"), wireChart);
    if (scope.matches && scope.matches(".chart svg[data-cpts]")) wireChart(scope);
  }

  var reduce;
  try { reduce = !("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { reduce = true; }
  if (reduce) {
    root.classList.remove("mo"); // motion off — but charts stay interactive
    wireCharts(document);
    try {
      new MutationObserver(function (muts) {
        muts.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1) wireCharts(n); }); });
      }).observe(document.body, { childList: true, subtree: true });
    } catch (e) {}
    return;
  }
  clearTimeout(window.__moFail); // we're alive — cancel the fail-open timer

  var SEL = ".hero, .page-hero, .ev-head, .dx-head, .beat, .loop, .rd-sec, .two-voice, .coach-daily, " +
    ".coach-progress, .coach-report, .coach-stance, .team-lead, .team-focus, .team-tension, .team-huddle, " +
    ".supp, .rd-card, .cap-card, .vr-row, .figs, .ml-ladder";

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add("is-in");
      io.unobserve(e.target);
      draw(e.target);
      countUp(e.target);
    });
  }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });

  function arm(scope) {
    var list = [];
    if (scope.matches && scope.matches(SEL)) list.push(scope);
    if (scope.querySelectorAll) list = list.concat(Array.prototype.slice.call(scope.querySelectorAll(SEL)));
    list.forEach(function (el) {
      if (el.__mo) return;
      el.__mo = 1;
      // already on screen at arm time? reveal next frame (entrance), else observe.
      io.observe(el);
    });
    wireCharts(scope); // make any line charts in this scope explorable
  }

  // SVG line charts draw themselves in when their section reveals.
  function draw(scope) {
    var paths = scope.querySelectorAll(".chart-line, .wt-trend, .ah-hrv, .ah-rhr, .pc-mid, .cgm-curve, .corr-fill");
    Array.prototype.forEach.call(paths, function (p) {
      if (p.__drawn || typeof p.getTotalLength !== "function") return;
      p.__drawn = 1;
      try {
        var L = p.getTotalLength();
        if (!L) return;
        p.style.strokeDasharray = L;
        p.style.strokeDashoffset = L;
        p.getBoundingClientRect(); // force reflow so the transition runs
        requestAnimationFrame(function () {
          p.style.transition = "stroke-dashoffset 1.15s var(--ease-out)";
          p.style.strokeDashoffset = "0";
        });
      } catch (e) { /* non-path stroke — skip */ }
    });
  }

  // Opt-in count-up: any [data-countup] whose text is numeric animates 0 → value.
  function countUp(scope) {
    var els = scope.querySelectorAll ? scope.querySelectorAll("[data-countup]") : [];
    Array.prototype.forEach.call(els, function (el) { animateCount(el); });
    if (scope.matches && scope.matches("[data-countup]")) animateCount(scope);
  }
  function animateCount(el) {
    if (el.__counted) return;
    var raw = (el.textContent || "").trim();
    var m = raw.match(/-?[\d,]*\.?\d+/);
    if (!m) return; // placeholder like "··" — leave it; story.js will re-call us
    el.__counted = 1;
    var target = parseFloat(m[0].replace(/,/g, ""));
    if (!isFinite(target)) return;
    var prefix = raw.slice(0, m.index), suffix = raw.slice(m.index + m[0].length);
    var decimals = (m[0].split(".")[1] || "").length;
    var dur = 900, t0 = null;
    function frame(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur);
      var eased = 1 - Math.pow(1 - k, 3);
      var v = (target * eased).toFixed(decimals);
      el.textContent = prefix + (decimals ? v : Math.round(target * eased)) + suffix;
      if (k < 1) requestAnimationFrame(frame); else el.textContent = prefix + (decimals ? target.toFixed(decimals) : target) + suffix;
    }
    requestAnimationFrame(frame);
  }
  // Public hook so JS that sets a number AFTER load (e.g. story.js) can trigger the count.
  window.__moCount = function (el) { if (el) { el.__counted = 0; animateCount(el); } };

  arm(document);
  var mo = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1) arm(n); });
    });
  });
  mo.observe(document.body, { childList: true, subtree: true });
})();

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

  // ── Interactive charts (ALWAYS on — interaction, not motion, so it runs even
  //    under prefers-reduced-motion). Any chart element that embeds data-cpts
  //    (normalized 0–1 coords + a label per point) gets a focus dot + tooltip —
  //    SVG plots AND the div-based charts (stacked bars, spines, column stacks,
  //    row lists) alike, so every series answers when touched (#582). Hit-testing
  //    is NEAREST-ON-THE-DOMINANT-AXIS: x by default (date-positioned charts have
  //    irregular x spacing, so round(ratio·(n−1)) picks the wrong point — nearest
  //    keeps uniform charts pixel-identical), or y when data-cpts-axis="y" (the
  //    vertically-stacked row lists: sufficiency / dumbbell / landmark bars).
  //    Pointer events cover mouse + pen + touch: touch-action pan-y keeps the page
  //    scrolling vertically while a horizontal drag scrubs the chart, and a tap
  //    inspects (lingers briefly — touch has no hover-out). Keyboard rides the
  //    SAME path: the plot is focusable, arrows/Home/End walk points, Escape
  //    dismisses (pairs with #579's focus styles). ──
  function wireChart(el) {
    if (el.__ix) return; el.__ix = 1;
    var cpts; try { cpts = JSON.parse(el.getAttribute("data-cpts")); } catch (e) { return; }
    if (!cpts || !cpts.length) return;
    var fig = el.closest(".chart") || el.parentElement; if (!fig) return;
    if (getComputedStyle(fig).position === "static") fig.style.position = "relative";
    el.style.touchAction = "pan-y";
    var yAxis = el.getAttribute("data-cpts-axis") === "y";
    var dot = document.createElement("span"); dot.className = "chart-focus"; dot.hidden = true;
    var tip = document.createElement("span"); tip.className = "chart-tip label"; tip.hidden = true;
    fig.appendChild(dot); fig.appendChild(tip);
    var hideT = null, cur = -1;
    function place(pt) {
      var r = el.getBoundingClientRect(), fr = fig.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var px = (r.left - fr.left) + pt.x * r.width, py = (r.top - fr.top) + pt.y * r.height;
      dot.style.left = px + "px"; dot.style.top = py + "px"; dot.hidden = false;
      tip.textContent = pt.l; tip.style.left = px + "px"; tip.style.top = py + "px"; tip.hidden = false;
      // Cross-highlight hook (uplevel P4): fire-and-forget — a consumer (e.g. the
      // weight silhouette) can follow the focused point; a listener error must
      // never break the chart itself.
      try { el.dispatchEvent(new CustomEvent("chart:point", { bubbles: true, detail: { label: pt.l, v: pt.v } })); } catch (e) {}
    }
    function showIndex(i) { if (i < 0 || i >= cpts.length) return; cur = i; place(cpts[i]); }
    function showAt(clientX, clientY) {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var ratio = yAxis ? Math.max(0, Math.min(1, (clientY - r.top) / r.height))
                        : Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      var best = Infinity, bi = 0;
      for (var i = 0; i < cpts.length; i++) {
        var d = Math.abs((yAxis ? cpts[i].y : cpts[i].x) - ratio);
        if (d < best) { best = d; bi = i; }
      }
      showIndex(bi);
    }
    function hide() { clearTimeout(hideT); dot.hidden = true; tip.hidden = true; }
    el.addEventListener("pointermove", function (e) { clearTimeout(hideT); showAt(e.clientX, e.clientY); });
    el.addEventListener("pointerdown", function (e) { clearTimeout(hideT); showAt(e.clientX, e.clientY); });
    el.addEventListener("pointerup", function (e) {
      // tap-to-inspect: linger long enough to read, then tidy up.
      if (e.pointerType !== "mouse") { clearTimeout(hideT); hideT = setTimeout(hide, 2600); }
    });
    el.addEventListener("pointerleave", function (e) {
      // touch fires leave right after up — that would kill the tap linger.
      if (e.pointerType === "mouse") hide();
    });
    el.addEventListener("pointercancel", hide); // the scroll took over the gesture
    // Keyboard exploration — same code path. Skip decorative (aria-hidden) plots.
    if (el.getAttribute("aria-hidden") !== "true") {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      el.addEventListener("keydown", function (e) {
        var k = e.key;
        if (k === "ArrowRight" || k === "ArrowDown") { clearTimeout(hideT); showIndex(cur < 0 ? 0 : Math.min(cpts.length - 1, cur + 1)); e.preventDefault(); }
        else if (k === "ArrowLeft" || k === "ArrowUp") { clearTimeout(hideT); showIndex(cur < 0 ? 0 : Math.max(0, cur - 1)); e.preventDefault(); }
        else if (k === "Home") { clearTimeout(hideT); showIndex(0); e.preventDefault(); }
        else if (k === "End") { clearTimeout(hideT); showIndex(cpts.length - 1); e.preventDefault(); }
        else if (k === "Escape") { hide(); cur = -1; }
      });
      el.addEventListener("blur", hide);
    }
  }
  function wireCharts(scope) {
    if (!scope.querySelectorAll) return;
    Array.prototype.forEach.call(scope.querySelectorAll("[data-cpts]"), wireChart);
    if (scope.matches && scope.matches("[data-cpts]")) wireChart(scope);
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

  // .rd-card removed (2026-07-02): the coach-read/protocol cards paint immediately —
  // opacity-gating them read as dead air on the Coaching landing tab (see tokens.css).
  var SEL = ".hero, .page-hero, .ev-head, .dx-head, .beat, .loop, .rd-sec, .two-voice, .coach-daily, " +
    ".coach-progress, .coach-report, .coach-stance, .team-lead, .team-focus, .team-tension, .team-huddle, " +
    ".supp, .cap-card, .vr-row, .figs, .ml-ladder";

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

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

  // ── Freshness pulse (#589) — a NEW, self-contained primitive kept beside (not
  //    merged into) the data-cpts chart-wiring below: the epic's no-fake-liveness
  //    rule made reusable. Any element carrying data-fresh-ts (an ISO instant) +
  //    data-fresh-window (its OWN freshness window in seconds, sourced from
  //    source_registry.py via /api/source_freshness or /api/last_sync — never a
  //    guessed constant) gets .fr-live ONLY while now − ts is inside that window.
  //    Runs regardless of the reduced-motion branch below: the fresh/stale STATE
  //    must update either way (color/text), only the CSS keyframe itself is
  //    reduced-motion-gated (tokens.css §12c). Re-checks on an interval since a
  //    page can sit open long enough for a window to close on its own, and via
  //    MutationObserver so SPA-injected markup (the cockpit sync line rebuilds
  //    its DOM on every poll) is picked up automatically. FRESH_WINDOW_OK below
  //    is deliberately fenced with sentinel comments — a unit test extracts and
  //    exercises this exact predicate, never a re-implementation of it.
  // FRESH_WINDOW_OK_START
  function freshWindowOk(tsIso, windowSeconds, nowMs) {
    var ts = Date.parse(tsIso);
    var win = parseFloat(windowSeconds);
    if (!isFinite(ts) || !isFinite(win) || win <= 0) return false;
    var now = typeof nowMs === "number" ? nowMs : Date.now();
    var age = now - ts;
    return age >= -60000 && age <= win * 1000; // −60s clock-skew grace; a future ts is never "live"
  }
  // FRESH_WINDOW_OK_END
  window.__freshWindowOk = freshWindowOk; // exposed so the unit test drives the exact DOM predicate

  function wireFreshness(scope) {
    if (!scope || !scope.querySelectorAll) return;
    var els = (scope.matches && scope.matches("[data-fresh-ts]")) ? [scope] : [];
    els = els.concat(Array.prototype.slice.call(scope.querySelectorAll("[data-fresh-ts]")));
    els.forEach(function (el) {
      var ok = freshWindowOk(el.getAttribute("data-fresh-ts"), el.getAttribute("data-fresh-window"));
      el.classList.toggle("fr-live", ok);
    });
  }
  wireFreshness(document);
  try {
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1) wireFreshness(n); }); });
    }).observe(document.body, { childList: true, subtree: true });
  } catch (e) {}
  setInterval(function () { wireFreshness(document); }, 60000);

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
  // ONE readout implementation (the focus dot + cursor-following tooltip), shared by
  //    every hit-test strategy below (#582 line/bar path, #583 radial + cell paths).
  //    Hosts the dot/tip inside `fig` (positioned relative) and exposes set()/hide().
  function makeReadout(fig, srcEl) {
    if (getComputedStyle(fig).position === "static") fig.style.position = "relative";
    var dot = document.createElement("span"); dot.className = "chart-focus"; dot.hidden = true;
    var tip = document.createElement("span"); tip.className = "chart-tip label"; tip.hidden = true;
    fig.appendChild(dot); fig.appendChild(tip);
    return {
      set: function (px, py, label, v) {
        dot.style.left = px + "px"; dot.style.top = py + "px"; dot.hidden = false;
        tip.textContent = label; tip.style.left = px + "px"; tip.style.top = py + "px"; tip.hidden = false;
        // Cross-highlight hook (uplevel P4): fire-and-forget — a consumer (e.g. the
        // weight silhouette) can follow the focused point; a listener error must
        // never break the chart itself.
        try { srcEl.dispatchEvent(new CustomEvent("chart:point", { bubbles: true, detail: { label: label, v: v } })); } catch (e) {}
      },
      hide: function () { dot.hidden = true; tip.hidden = true; },
    };
  }

  // Wire the pointer + tap-linger + keyboard grammar shared by both strategies onto
  //    `el`, delegating the actual point resolution to the caller's closures:
  //    resolveAt(clientX, clientY) → index, step(dir) → index (keyboard), showIndex(i).
  function wireGrammar(el, showIndex, resolveAt, step, hide) {
    var hideT = null;
    el.style.touchAction = "pan-y";
    el.addEventListener("pointermove", function (e) { clearTimeout(hideT); showIndex(resolveAt(e.clientX, e.clientY)); });
    el.addEventListener("pointerdown", function (e) { clearTimeout(hideT); showIndex(resolveAt(e.clientX, e.clientY)); });
    el.addEventListener("pointerup", function (e) {
      // tap-to-inspect: linger long enough to read, then tidy up.
      if (e.pointerType !== "mouse") { clearTimeout(hideT); hideT = setTimeout(hide, 2600); }
    });
    el.addEventListener("pointerleave", function (e) {
      // touch fires leave right after up — that would kill the tap linger.
      if (e.pointerType === "mouse") hide();
    });
    el.addEventListener("pointercancel", hide); // the scroll took over the gesture
    // Keyboard exploration — same readout. Skip decorative (aria-hidden) plots.
    if (el.getAttribute("aria-hidden") !== "true") {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      el.addEventListener("keydown", function (e) {
        var i = step(e.key);
        if (i === -2) { clearTimeout(hideT); hide(); return; } // Escape
        if (i === -1) return; // key not handled — let it bubble
        clearTimeout(hideT); showIndex(i); e.preventDefault();
      });
      el.addEventListener("blur", hide);
    }
  }

  // Strategy 1 — abstract coordinate points (data-cpts). Hit-test is NEAREST on the
  //    dominant axis (x, or y for data-cpts-axis="y"), OR 2-D Euclidean for radial /
  //    scatter plots (data-cpts-hit="xy" — rings, radar, the autonomic 2×2), where a
  //    single axis is meaningless. Keyboard walks the point array in order.
  function wireChart(el) {
    if (el.__ix) return; el.__ix = 1;
    var cpts; try { cpts = JSON.parse(el.getAttribute("data-cpts")); } catch (e) { return; }
    if (!cpts || !cpts.length) return;
    var fig = el.closest(".chart") || el.parentElement; if (!fig) return;
    var yAxis = el.getAttribute("data-cpts-axis") === "y";
    var xy = el.getAttribute("data-cpts-hit") === "xy";
    var rd = makeReadout(fig, el);
    var cur = -1;
    function place(pt) {
      var r = el.getBoundingClientRect(), fr = fig.getBoundingClientRect();
      if (!r.width || !r.height) return;
      rd.set((r.left - fr.left) + pt.x * r.width, (r.top - fr.top) + pt.y * r.height, pt.l, pt.v);
    }
    function showIndex(i) { if (i < 0 || i >= cpts.length) return; cur = i; place(cpts[i]); }
    function resolveAt(clientX, clientY) {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return -1;
      var best = Infinity, bi = 0, i;
      if (xy) {
        var nx = (clientX - r.left) / r.width, ny = (clientY - r.top) / r.height;
        for (i = 0; i < cpts.length; i++) { var dx = cpts[i].x - nx, dy = cpts[i].y - ny, d = dx * dx + dy * dy; if (d < best) { best = d; bi = i; } }
      } else {
        var ratio = yAxis ? Math.max(0, Math.min(1, (clientY - r.top) / r.height))
                          : Math.max(0, Math.min(1, (clientX - r.left) / r.width));
        for (i = 0; i < cpts.length; i++) { var da = Math.abs((yAxis ? cpts[i].y : cpts[i].x) - ratio); if (da < best) { best = da; bi = i; } }
      }
      return bi;
    }
    function step(k) {
      if (k === "ArrowRight" || k === "ArrowDown") return cur < 0 ? 0 : Math.min(cpts.length - 1, cur + 1);
      if (k === "ArrowLeft" || k === "ArrowUp") return cur < 0 ? 0 : Math.max(0, cur - 1);
      if (k === "Home") return 0;
      if (k === "End") return cpts.length - 1;
      if (k === "Escape") { cur = -1; return -2; }
      return -1;
    }
    wireGrammar(el, showIndex, resolveAt, step, rd.hide);
  }

  // Strategy 2 — reflowing DOM cells (data-cells). Each cell carries data-l (its label);
  //    hit-test is nearest cell CENTRE in live screen space (robust to responsive wrap —
  //    heat calendars, effort maps, meal-window rows all reflow), and the keyboard walks
  //    cells in 2-D (arrows pick the nearest cell in the pressed direction). One readout,
  //    measured at interaction time so a re-layout can never desync the dot from a cell.
  function wireCells(el) {
    if (el.__ix) return; el.__ix = 1;
    var cells = Array.prototype.slice.call(el.querySelectorAll("[data-l]"));
    if (!cells.length) return;
    var rd = makeReadout(el, el); // the container hosts its own dot/tip
    var cur = -1;
    function centre(i) { var r = cells[i].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
    function showIndex(i) {
      if (i < 0 || i >= cells.length) return; cur = i;
      var er = el.getBoundingClientRect(), r = cells[i].getBoundingClientRect();
      if (!er.width) return;
      rd.set((r.left - er.left) + r.width / 2, (r.top - er.top) + r.height / 2, cells[i].getAttribute("data-l"), cells[i].getAttribute("data-v"));
    }
    function resolveAt(clientX, clientY) {
      var best = Infinity, bi = 0;
      for (var i = 0; i < cells.length; i++) { var c = centre(i), dx = c.x - clientX, dy = c.y - clientY, d = dx * dx + dy * dy; if (d < best) { best = d; bi = i; } }
      return bi;
    }
    function directional(dx, dy) {
      if (cur < 0) return 0;
      var c0 = centre(cur), best = Infinity, bi = cur;
      for (var i = 0; i < cells.length; i++) {
        if (i === cur) continue;
        var c = centre(i), ddx = c.x - c0.x, ddy = c.y - c0.y;
        if (dx > 0 && ddx <= 1) continue; if (dx < 0 && ddx >= -1) continue;
        if (dy > 0 && ddy <= 1) continue; if (dy < 0 && ddy >= -1) continue;
        // cross-axis drift is penalised so a step reads as "the next one over", not a diagonal jump.
        var along = dx ? Math.abs(ddx) : Math.abs(ddy), across = dx ? Math.abs(ddy) : Math.abs(ddx);
        var score = along + across * 2;
        if (score < best) { best = score; bi = i; }
      }
      return bi;
    }
    function step(k) {
      if (k === "ArrowRight") return cur < 0 ? 0 : directional(1, 0);
      if (k === "ArrowLeft") return cur < 0 ? 0 : directional(-1, 0);
      if (k === "ArrowDown") return cur < 0 ? 0 : directional(0, 1);
      if (k === "ArrowUp") return cur < 0 ? 0 : directional(0, -1);
      if (k === "Home") return 0;
      if (k === "End") return cells.length - 1;
      if (k === "Escape") { cur = -1; return -2; }
      return -1;
    }
    wireGrammar(el, showIndex, resolveAt, step, rd.hide);
  }
  function wireCharts(scope) {
    if (!scope.querySelectorAll) return;
    Array.prototype.forEach.call(scope.querySelectorAll("[data-cpts]"), wireChart);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-cells]"), wireCells);
    if (scope.matches) {
      if (scope.matches("[data-cpts]")) wireChart(scope);
      if (scope.matches("[data-cells]")) wireCells(scope);
    }
  }

  // ── Scroll-region keyboard access (#3277) — a self-contained primitive in the
  //    same shape as the freshness pulse above: it runs REGARDLESS of the
  //    reduced-motion branch below (keyboard reach is not motion). Below the tablet
  //    breakpoint the shared table primitive (.rd-tbl / .table-scroll — evidence.css,
  //    tokens.css) and the code wells (.rd-code, <pre>) become horizontally-scrolling
  //    boxes; a box that scrolls but cannot take focus cannot be reached or scrolled
  //    from the keyboard — axe `scrollable-region-focusable` (serious), which 14
  //    reader pages carried at 390px while no gate measured that viewport.
  //    Scrollability is a LAYOUT fact, not a markup one (the same table scrolls at
  //    390px and not at 1440px, and most of these tables are rendered client-side
  //    by the evidence modules), so it is decided here from the live box rather
  //    than by a static attribute in 90 shells: an element whose computed
  //    overflow-x allows scrolling AND whose content is wider than its box gets
  //    tabindex="0" (Tab reaches it, the arrow keys scroll it) plus an accessible
  //    name where its role permits one — role="group" for generic elements, never
  //    the landmark role="region" — and loses all of it again when it stops
  //    overflowing (rotate, resize, data change). Elements that already contain
  //    focusable content are left alone — focus lands inside and the arrow keys
  //    already scroll the container; that is also exactly axe's own pass condition.
  //    Re-runs on resize/load/fonts and on the same MutationObserver channel the
  //    evidence pages render their tables through. Fenced so a test can extract it
  //    (tests/test_scroll_region_focus_3277.py runs this exact block in Node).
  // SCROLL_REGION_START
  var SR_GENERIC = { DIV: 1, PRE: 1, SPAN: 1, P: 1, CODE: 1 }; // no implicit role → gets role="group" so a name is permitted
  var SR_NAMED = { TABLE: 1, FIGURE: 1, SECTION: 1, ARTICLE: 1, ASIDE: 1, UL: 1, OL: 1, DL: 1 }; // implicit role already accepts a name
  var SR_FOCUSABLE = 'a[href], area[href], button, input, select, textarea, summary, iframe, [contenteditable="true"], [tabindex]:not([tabindex="-1"])';
  function srIsHScrollable(el) {
    if (el.scrollWidth <= el.clientWidth + 1) return false; // cheap layout read first
    var ox = getComputedStyle(el).overflowX;
    return ox === "auto" || ox === "scroll";
  }
  function srHasName(el) {
    if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby")) return true;
    if (el.tagName === "TABLE") return !!el.querySelector(":scope > caption");
    if (el.tagName === "FIGURE") return !!el.querySelector(":scope > figcaption");
    return false;
  }
  function srName(el) {
    var tag = el.tagName;
    var kind = tag === "TABLE" ? "table" : (tag === "PRE" || tag === "CODE" || /\brd-code\b/.test(el.className || "")) ? "code" : tag === "FIGURE" ? "figure" : "content";
    var scope = el.closest("section, article, .rd-sec, main") || document;
    var h = scope.querySelector("h1, h2, h3, h4");
    var t = h && h.textContent ? h.textContent.replace(/\s+/g, " ").trim().slice(0, 80) : "";
    return "Scrollable " + kind + (t ? ": " + t : "");
  }
  function srApply(el) {
    var on = srIsHScrollable(el);
    var mine = el.getAttribute("data-scroll-region") === "auto";
    if (on && !mine) {
      if (el.hasAttribute("tabindex") || el.querySelector(SR_FOCUSABLE)) return; // already reachable
      var tag = el.tagName;
      // role="group", never "region": region is a LANDMARK, and two same-named
      // landmarks are axe `landmark-unique` — measured, not guessed (2026-08-31:
      // role="region" here traded 33 serious nodes for 3 new moderate findings on
      // /method/{verify,predictions,calibration}/). group names the box without
      // adding anything to the landmark menu.
      if (SR_GENERIC[tag] && !el.hasAttribute("role")) { el.setAttribute("role", "group"); el.setAttribute("data-sr-role", "1"); }
      if ((SR_GENERIC[tag] || SR_NAMED[tag]) && !srHasName(el)) { el.setAttribute("aria-label", srName(el)); el.setAttribute("data-sr-label", "1"); }
      el.setAttribute("tabindex", "0");
      el.setAttribute("data-scroll-region", "auto");
    } else if (!on && mine) {
      el.removeAttribute("tabindex");
      if (el.getAttribute("data-sr-role")) { el.removeAttribute("role"); el.removeAttribute("data-sr-role"); }
      if (el.getAttribute("data-sr-label")) { el.removeAttribute("aria-label"); el.removeAttribute("data-sr-label"); }
      el.removeAttribute("data-scroll-region");
    }
  }
  function srScan() {
    try {
      var all = document.body.getElementsByTagName("*");
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.namespaceURI !== "http://www.w3.org/1999/xhtml" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") continue;
        srApply(el);
      }
    } catch (e) {}
  }
  var srTimer = 0;
  function srSchedule() { clearTimeout(srTimer); srTimer = setTimeout(srScan, 60); }
  // SCROLL_REGION_END
  srScan();
  window.addEventListener("resize", srSchedule);
  window.addEventListener("load", srSchedule);
  try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(srSchedule); } catch (e) {}
  try {
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        if (muts[i].type === "childList" && muts[i].addedNodes.length) { srSchedule(); return; }
      }
    }).observe(document.body, { childList: true, subtree: true });
  } catch (e) {}
  window.__srScan = srScan; // hook for JS that reflows a table after load

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
  var SEL = ".hero, .page-hero, .ev-head, .dx-head, .beat, .verse, .loop, .rd-sec, .two-voice, .coach-daily, " +
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
    // threshold:0 (any-pixel intersect) is height-independent — a fractional threshold
    // like 0.1 can NEVER be reached on a section taller than 10 viewport-heights (the
    // 80-card /protocols/challenges/ backlog is ~22,600px; max ratio ≈3.7%), so its
    // cards stay opacity:0 forever. The -12% bottom rootMargin gives the same "reveal a
    // beat after it enters" feel the threshold used to, but for any element height. (#1002)
  }, { threshold: 0, rootMargin: "0px 0px -12% 0px" });

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
        // #421 render-QA: clear the dash props once drawn. getTotalLength() is USER units,
        // but on a vector-effect:non-scaling-stroke path Chromium applies the dash in SCREEN
        // space — leave the dasharray in place and any chart rendered wider than its viewBox
        // (desktop, preserveAspectRatio="none") paints only L/renderedWidth of the line.
        // At offset 0 the line is fully drawn, so clearing is visually a no-op.
        var undash = function () {
          p.style.strokeDasharray = "";
          p.style.strokeDashoffset = "";
          p.removeEventListener("transitionend", undash);
        };
        p.addEventListener("transitionend", undash);
        setTimeout(undash, 1500); // fallback if transitionend never fires
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

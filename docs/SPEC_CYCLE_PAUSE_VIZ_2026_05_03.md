# SPEC: Cycle Pause Visual Rendering on Observatory Charts

**Status:** Ready to execute
**Author:** Matt + Claude (web)
**Date:** 2026-05-03
**Estimated effort:** 90–120 min (one focused session in Claude Code)
**Related backlog items:** WR-47 Pause Mode (this is the user-facing surface)

---

## 1. Problem & rationale

Matthew was off-grid from approximately **2026-04-12 to 2026-05-01** (house move). Every observatory chart that spans that window currently shows it as either flatlines, missing data, or — worse — interpolated continuity. A first-time visitor landing on the site Monday should *immediately* understand they're looking at a documented pause, not broken data.

The handover already captured this state in DDB with cycle markers:
- `CYCLE#1#launch`        — 2026-04-01 → 2026-04-11
- `CYCLE#1.5#gap_move`    — 2026-04-12 → 2026-05-01
- `CYCLE#2#reentry`       — 2026-05-02 → ongoing

The platform's daily-brief banner already explains stale-source state in text. This spec adds the **visual** layer: a labeled gray band on every observatory chart that spans the gap window, with a small annotation linking to context.

This is the user-facing surface of the WR-47 Pause Mode feature in the backlog. Shipping this gives Matthew a real prototype to evaluate before the bigger architectural work on WR-47.

---

## 2. Acceptance criteria

A reviewer (or Matthew himself) opens averagejoematt.com Monday morning. Each observatory page (Sleep, Glucose, Nutrition, Training, Physical, Mind) shows trend charts in 30-day or 90-day mode. Acceptance:

1. **Visible gray band** spans the April 12 → May 1 window on every time-series chart (SVG and Canvas).
2. **Label is readable** above or beside the band: "Platform Pause · House Move" with the date range. Mobile-responsive — band stays visible at narrow widths.
3. **No data drawn over the gap** — line charts skip across the gap (broken segments), area charts don't fill the gap, dots don't render inside the band.
4. **Tooltips** on hover/touch over the band show "Platform pause: April 12 → May 1, 2026 · House move".
5. **7-day window** (default) shows nothing (gap is outside the window) — band is conditionally rendered only when the visible window intersects the gap.
6. **Color/style** matches the existing observatory aesthetic (subtle, monospace label, faint gray fill — see §5 design tokens).
7. **No JS errors** in browser console on any observatory page.
8. **Visual QA passes:** `python3 tests/visual_qa.py --screenshot` runs to completion. Manual visual inspection confirms band placement is correct.
9. **Performance** — no measurable lag added to chart render. Gap rendering should be O(1) overlay, not data-iteration.

---

## 3. Out of scope

- **The Pulse / "Live" page** (`/live/`) — single-day data, no time-series, no gap to render.
- **Character Sheet rings/gauges** — not time-series.
- **Discoveries timeline** — has its own annotation mechanism; defer to WR-47 proper.
- **Pre-2026-04-12 archived charts** — the band is forward-looking; old chart screenshots in markdown/blog content stay as-is.
- **Ledger / experiments / challenges history charts** — these don't have continuous time-series in the same shape.
- **Adding new historical pause periods** — config supports a list, but only one pause is needed today.

---

## 4. Files to modify

### Required (in this order):

1. **`site/assets/js/cycle-pause.js`** *(NEW)* — shared module with the gap-rendering primitives.
2. **`site/assets/css/observatory-v3.css`** — add `.cycle-pause-*` utility classes.
3. **`site/sleep/index.html`** — wire the SVG band overlay to `s-arch-svg` and the canvas overlay to `s-trend-canvas`.
4. **`site/glucose/index.html`** — same pattern, glucose-specific chart IDs.
5. **`site/nutrition/index.html`** — same pattern.
6. **`site/training/index.html`** — same pattern.
7. **`site/physical/index.html`** — same pattern.
8. **`site/mind/index.html`** — same pattern. **Read carefully — the Mind page uses Conti Amendment narrative-first treatment; band should appear below the narrative, not on top of it.**

### Optional (only if it cleanly extends scope):

9. **`site/assets/config/cycle_markers.json`** *(NEW)* — config-driven gap windows so Cycle 2 / 3 / 4 don't require code edits when a future pause happens.

---

## 5. Design tokens

Match the observatory editorial aesthetic. Use existing CSS variables from `site/assets/css/tokens.css`:

| Element | Token / Value |
|---|---|
| Band fill | `rgba(255,255,255,0.04)` (matches grid line opacity) |
| Band border (left/right vertical lines) | `rgba(255,255,255,0.10)` |
| Label text color | `var(--text-faint)` |
| Label font | `var(--font-mono)`, `10px`, `letter-spacing: 0.12em`, `text-transform: uppercase` |
| Label position | Inside the band, top-left, with `4px` padding |
| Label content | `"⏸ PLATFORM PAUSE · APR 12 → MAY 1"` |
| Tooltip on hover | Standard observatory tooltip pattern (see `s-chart-tooltip` in sleep/index.html) |

**Critical:** the band must be subtle. Not a big alert box — this is "this happened, here's why" framing, not "ERROR." Aim for the visual weight of the existing 30-day target zone shading on the sleep trend chart (the `rgba(96,165,250,0.06)` 85+ band). That's the right level of presence.

---

## 6. Reference implementation

### 6a. The shared module — `site/assets/js/cycle-pause.js`

```javascript
/**
 * cycle-pause.js — Render visual gap-bands on observatory charts.
 *
 * Used by every observatory page that renders time-series charts.
 * Idempotent: safe to call multiple times (e.g. on time-window toggle).
 *
 * Public API:
 *   getCyclePauses()                          → array of pause windows
 *   renderSvgPauseBand(svgEl, opts)           → overlay <g> on an SVG chart
 *   renderCanvasPauseBand(ctx, opts)          → fillRect on a canvas chart
 *   filterTrendForPause(trendData, valueKey)  → null out data points inside any pause window
 */

(function (window) {
  'use strict';

  // Hardcoded for now. Future: fetch from /assets/config/cycle_markers.json
  // or from /api/cycle_markers (DDB-backed).
  var PAUSES = [
    {
      id: 'cycle_1_5_gap_move',
      label: 'Platform Pause · House Move',
      short_label: 'PLATFORM PAUSE',
      start: '2026-04-12',
      end:   '2026-05-01',
      reason: 'House move. Tracking interrupted; resumed May 2.',
      link:   '/elena/2026-05-04-comeback/'  // Link target may not exist yet
    }
  ];

  function getCyclePauses() { return PAUSES.slice(); }

  /**
   * Filter a trend array, nullifying any value inside a pause window.
   * Charts that draw lines/areas should treat null as a break.
   *
   * @param  {Array}  trendData   array of {date, ...} records
   * @param  {string} valueKey    the field to nullify (e.g. 'sleep_score')
   * @return {Array}              new array with null'd values inside pauses
   */
  function filterTrendForPause(trendData, valueKey) {
    if (!trendData || !trendData.length) return trendData;
    return trendData.map(function (d) {
      if (!d.date) return d;
      var inPause = PAUSES.some(function (p) {
        return d.date >= p.start && d.date <= p.end;
      });
      if (inPause) {
        var clone = Object.assign({}, d);
        clone[valueKey] = null;
        clone._inPause = true;
        return clone;
      }
      return d;
    });
  }

  /**
   * Overlay a pause band on an SVG chart. Inserts a <g class="cycle-pause-band">
   * as the FIRST child of the SVG so it sits behind data.
   *
   * @param {SVGElement} svgEl
   * @param {Object} opts
   *   @param {Array<{date, ...}>} opts.trendData  used to compute x-axis mapping
   *   @param {number} opts.viewBoxW               width of SVG viewBox (e.g. 800)
   *   @param {number} opts.viewBoxH               height of SVG viewBox (e.g. 200)
   *   @param {boolean} opts.preserveAspectRatio   if 'none' (default), x maps proportionally
   */
  function renderSvgPauseBand(svgEl, opts) {
    if (!svgEl || !opts || !opts.trendData || !opts.trendData.length) return;
    // Remove any prior band (idempotent on re-render)
    var existing = svgEl.querySelector('.cycle-pause-band');
    if (existing) existing.remove();

    var W = opts.viewBoxW || 800, H = opts.viewBoxH || 200;
    var n = opts.trendData.length;
    if (n < 2) return;

    var firstDate = opts.trendData[0].date;
    var lastDate  = opts.trendData[n - 1].date;
    if (!firstDate || !lastDate) return;

    var bandsToDraw = [];
    PAUSES.forEach(function (p) {
      // Skip if pause window is entirely outside visible range
      if (p.end < firstDate || p.start > lastDate) return;

      // Clamp pause boundaries to visible range
      var startClamped = p.start < firstDate ? firstDate : p.start;
      var endClamped   = p.end   > lastDate  ? lastDate  : p.end;

      // Find indices
      var startIdx = opts.trendData.findIndex(function (d) { return d.date >= startClamped; });
      var endIdx   = opts.trendData.findIndex(function (d) { return d.date >= endClamped; });
      if (startIdx < 0) startIdx = 0;
      if (endIdx < 0) endIdx = n - 1;

      var x1 = (startIdx / (n - 1)) * W;
      var x2 = (endIdx / (n - 1)) * W;
      var bandW = Math.max(2, x2 - x1);

      bandsToDraw.push({ pause: p, x: x1, width: bandW });
    });

    if (!bandsToDraw.length) return;

    var SVG_NS = 'http://www.w3.org/2000/svg';
    var g = document.createElementNS(SVG_NS, 'g');
    g.setAttribute('class', 'cycle-pause-band');

    bandsToDraw.forEach(function (b) {
      // Background fill
      var rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', b.x.toFixed(1));
      rect.setAttribute('y', '0');
      rect.setAttribute('width', b.width.toFixed(1));
      rect.setAttribute('height', H);
      rect.setAttribute('fill', 'rgba(255,255,255,0.04)');
      rect.setAttribute('stroke', 'rgba(255,255,255,0.10)');
      rect.setAttribute('stroke-width', '1');
      rect.setAttribute('stroke-dasharray', '2,3');
      g.appendChild(rect);

      // Hover tooltip via <title>
      var title = document.createElementNS(SVG_NS, 'title');
      title.textContent = b.pause.label + ' (' + b.pause.start + ' → ' + b.pause.end + ')';
      rect.appendChild(title);

      // Label text (only if band is wide enough)
      if (b.width > 60) {
        var label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('x', (b.x + 6).toFixed(1));
        label.setAttribute('y', '14');
        label.setAttribute('class', 'cycle-pause-label');
        label.textContent = '⏸ ' + b.pause.short_label;
        g.appendChild(label);
      }
    });

    // Insert as first child (so it sits behind data)
    if (svgEl.firstChild) svgEl.insertBefore(g, svgEl.firstChild);
    else svgEl.appendChild(g);
  }

  /**
   * Draw pause bands on a canvas chart. Call AFTER the grid lines but BEFORE
   * the data line/area, so the band sits behind data.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {Object} opts
   *   @param {Array<{date, ...}>} opts.trendData
   *   @param {Object} opts.padding  {t, r, b, l}
   *   @param {number} opts.canvasW
   *   @param {number} opts.canvasH
   */
  function renderCanvasPauseBand(ctx, opts) {
    if (!ctx || !opts || !opts.trendData || !opts.trendData.length) return;
    var n = opts.trendData.length;
    if (n < 2) return;

    var pad = opts.padding || { t: 16, r: 16, b: 24, l: 42 };
    var iW  = opts.canvasW - pad.l - pad.r;
    var iH  = opts.canvasH - pad.t - pad.b;

    var firstDate = opts.trendData[0].date;
    var lastDate  = opts.trendData[n - 1].date;
    if (!firstDate || !lastDate) return;

    PAUSES.forEach(function (p) {
      if (p.end < firstDate || p.start > lastDate) return;

      var startClamped = p.start < firstDate ? firstDate : p.start;
      var endClamped   = p.end   > lastDate  ? lastDate  : p.end;

      var startIdx = opts.trendData.findIndex(function (d) { return d.date >= startClamped; });
      var endIdx   = opts.trendData.findIndex(function (d) { return d.date >= endClamped; });
      if (startIdx < 0) startIdx = 0;
      if (endIdx < 0) endIdx = n - 1;

      var x1 = pad.l + (startIdx / (n - 1)) * iW;
      var x2 = pad.l + (endIdx / (n - 1)) * iW;
      var w  = Math.max(2, x2 - x1);

      // Background fill
      ctx.fillStyle = 'rgba(255,255,255,0.04)';
      ctx.fillRect(x1, pad.t, w, iH);

      // Dashed left/right borders
      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.10)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, pad.t); ctx.lineTo(x1, pad.t + iH);
      ctx.moveTo(x1 + w, pad.t); ctx.lineTo(x1 + w, pad.t + iH);
      ctx.stroke();
      ctx.restore();

      // Label (only if band is wide enough)
      if (w > 60) {
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('⏸ ' + p.short_label, x1 + 6, pad.t + 14);
      }
    });
  }

  // Expose
  window.CyclePause = {
    getPauses: getCyclePauses,
    filterTrend: filterTrendForPause,
    renderSvgBand: renderSvgPauseBand,
    renderCanvasBand: renderCanvasPauseBand
  };
}(window));
```

### 6b. CSS additions — `site/assets/css/observatory-v3.css`

```css
/* ── Cycle Pause Visualization (WR-47 surface) ───────────── */

.cycle-pause-label {
  font-family: var(--font-mono);
  font-size: 10px;
  fill: var(--text-faint);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  pointer-events: none;
}

.cycle-pause-band rect {
  pointer-events: all;
  cursor: help;
}

/* HTML overlay variant (used when a chart can't accept SVG/Canvas overlay) */
.cycle-pause-overlay {
  position: absolute;
  background: rgba(255, 255, 255, 0.04);
  border-left: 1px dashed rgba(255, 255, 255, 0.10);
  border-right: 1px dashed rgba(255, 255, 255, 0.10);
  pointer-events: all;
  cursor: help;
}

.cycle-pause-overlay__label {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-faint);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 4px 6px;
  pointer-events: none;
}
```

### 6c. Wire-up pattern — Sleep page

Two integration points in `site/sleep/index.html`:

**(a) SVG architecture chart** — after the existing `drawTrendChart` and arch-rebuild blocks, add:

```javascript
// CYCLE PAUSE: overlay on SVG architecture chart
if (window.CyclePause && trend.length >= 2) {
  CyclePause.renderSvgBand(
    document.getElementById('s-arch-svg'),
    { trendData: trend, viewBoxW: 800, viewBoxH: 200 }
  );
}
```

This needs to also fire inside the `s-arch-toggles` click handler, since changing the time window rebuilds the SVG and the band needs to redraw with the new x-axis mapping. Add the same call at the end of the toggle's click handler with `sliced` instead of `trend`.

**(b) Canvas score-trend chart** — inside `drawTrendChart`, between the grid drawing and the area-fill drawing, add:

```javascript
// CYCLE PAUSE: overlay band BEFORE data so it sits behind
if (window.CyclePause) {
  CyclePause.renderCanvasBand(ctx, {
    trendData: trendData,
    padding: pad,
    canvasW: cW,
    canvasH: cH
  });
}
```

**(c) Script tag** — add to the `<script>` includes near the bottom of the page, before the per-page IIFE:

```html
<script src="/assets/js/cycle-pause.js"></script>
```

### 6d. Other observatory pages — pattern is identical

For each of `glucose`, `nutrition`, `training`, `physical`, `mind`:

1. Add the `<script src="/assets/js/cycle-pause.js"></script>` include.
2. Identify each chart's render function (search for `drawTrendChart`, `drawChart`, or canvas `getContext('2d')` calls).
3. Insert `CyclePause.renderSvgBand` for SVG charts immediately after the chart's path data is drawn.
4. Insert `CyclePause.renderCanvasBand` for canvas charts after grid lines but before data fill.
5. **For the Mind page specifically:** the Conti Amendment narrative-first treatment should not be disrupted. The pause band should *only* appear on time-series charts within the page, not on the narrative blocks.

The chart IDs and viewBox dimensions vary per page. Inspect each page's HTML to find them. Patterns to search for:
- SVG charts: `<svg id="..." viewBox="..."`
- Canvas charts: `<canvas class="..." id="...`
- Render functions: `function draw...` or fetch handlers calling chart construction.

---

## 7. Testing protocol

### 7a. Local sanity (before deploy)

```bash
cd ~/Documents/Claude/life-platform

# 1. Sync site to S3 (or push to a preview branch first if available)
bash deploy/sync_site_to_s3.sh

# 2. Smoke-test critical observatory pages render without errors
python3 tests/visual_qa.py --page /sleep/    --screenshot
python3 tests/visual_qa.py --page /glucose/  --screenshot
python3 tests/visual_qa.py --page /nutrition/ --screenshot
python3 tests/visual_qa.py --page /training/ --screenshot
python3 tests/visual_qa.py --page /physical/ --screenshot
python3 tests/visual_qa.py --page /mind/     --screenshot

# 3. Full sweep
python3 tests/visual_qa.py --screenshot
```

### 7b. Manual visual check

For each observatory page, in incognito window:

1. Load the page. Switch chart to **30-day mode**. Confirm the gray band appears spanning roughly April 12 → May 1.
2. Switch to **7-day mode**. Confirm the band does NOT appear (gap is outside the window).
3. Switch to **90-day mode**. Confirm the band appears, narrower than 30d view.
4. Hover/touch the band. Confirm tooltip shows pause label + dates.
5. Confirm the data line/area is broken — no interpolation across the gap.
6. Scroll the page. Confirm no console errors.
7. **On mobile width (≤768px):** confirm the label text either truncates gracefully or hides (the `width > 60` check should handle this).

### 7c. Visual regression baseline

After acceptance, capture a fresh baseline:

```bash
# Capture screenshots for the qa_baselines/ dir
python3 tests/visual_qa.py --screenshot
# Move new screenshots into deploy/qa_baselines/ if visual_qa.py supports it,
# or commit the qa-screenshots/ directory.
```

---

## 8. Deploy steps

```bash
# 1. Build/sync the site assets
bash deploy/sync_site_to_s3.sh

# 2. CloudFront invalidation for changed paths
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/assets/js/cycle-pause.js" \
          "/assets/css/observatory-v3.css" \
          "/sleep/*" "/glucose/*" "/nutrition/*" \
          "/training/*" "/physical/*" "/mind/*"

# 3. Verify
bash deploy/smoke_test_cloudfront.sh

# 4. Manual eyeball — open averagejoematt.com/sleep/ and confirm band appears
```

---

## 9. Known gotchas

1. **The Mind page Conti Amendment.** Don't break the narrative-first treatment. Charts on the Mind page sit *below* the narrative, not interleaved with it. Treat them like any other observatory chart.

2. **Time-window toggles re-render charts.** Every toggle click rebuilds chart paths from sliced data. The pause band must be re-rendered after each toggle, otherwise it'll have stale coordinates. The reference implementation handles this for SVG (via the toggle handler) but the canvas path goes through `drawTrendChart` so re-renders automatically.

3. **Canvas `dpr` (device pixel ratio) scaling.** The sleep page does `ctx.scale(dpr, dpr)` once at chart start. The pause band draws in CSS pixels, not device pixels. Make sure you're using `cW` (canvas offsetWidth) not `canvas.width` (the device-pixel buffer).

4. **`findIndex` + sparse data.** Some trend arrays may have date gaps even before April 12 (intermittent device sync). The `findIndex` calls assume sorted-by-date arrays. Double-check that each page's trend data is sorted ascending by date — if not, the band coordinates will be wrong. The reference implementation assumes sorted; if a page sorts descending, reverse before passing to `renderSvgBand` / `renderCanvasBand`.

5. **The "comeback" link target may not exist yet.** The PAUSES config references `/elena/2026-05-04-comeback/` which won't exist until Matthew writes the comeback essay. Either create a stub redirect at that URL or remove the `link` field from the PAUSES config until the essay ships.

6. **Don't filter the trend data globally.** The `filterTrendForPause()` helper exists for cases where a chart would otherwise interpolate across the gap. Use it judiciously per-chart — some charts (like protocol adherence bars) don't benefit from null-ing out the gap and would just look broken.

7. **Performance: don't loop over the full trend on every animation frame.** If a chart has hover/animation that triggers redraws, cache the band coordinates after the first compute.

---

## 10. Follow-ups (after this ships)

- **Config-driven pauses.** Move `PAUSES` from a hardcoded JS array to `/assets/config/cycle_markers.json`, fetched on page load. This eliminates code edits when a new pause happens.
- **DDB-backed pauses.** Read pause windows directly from `CYCLE#*` items in DynamoDB via a new `/api/cycle_markers` endpoint, so the source of truth is the same as the daily-brief banner.
- **Pre-pause / post-pause indicators.** Subtle dot or marker on the days immediately before and after the pause to give a "where the data picks back up" cue.
- **Discoveries page integration.** Add a discovery annotation type "platform_pause" so the Discoveries timeline references the same gap window.
- **Public Pause Mode.** Phase 2 of WR-47: subscribers see a "Matthew is on pause" status on the homepage when `CYCLE#*#gap_*` is active in DDB.

---

## 11. Done definition

- [ ] `cycle-pause.js` committed to `site/assets/js/`
- [ ] `observatory-v3.css` updated with new utility classes
- [ ] All 6 observatory pages updated (sleep, glucose, nutrition, training, physical, mind)
- [ ] `python3 tests/visual_qa.py --screenshot` passes for each page
- [ ] Manual visual check passed in incognito browser at desktop and mobile widths
- [ ] CloudFront invalidation completed
- [ ] `docs/CHANGELOG.md` entry added
- [ ] `handovers/HANDOVER_LATEST.md` updated to note v6.9.0 (or whatever next version)
- [ ] Commit pushed to main

---

## 12. Rollback

If the band breaks any chart visually:

```bash
# Revert the commit and resync
git revert <commit-sha>
bash deploy/sync_site_to_s3.sh
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
```

The change is purely additive (new file + new CSS classes + new function calls). Nothing existing was renamed or removed, so revert is safe.

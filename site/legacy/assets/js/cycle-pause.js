/**
 * cycle-pause.js — Render visual gap-bands on observatory charts.
 *
 * Used by every observatory page that renders time-series charts.
 * Idempotent: safe to call multiple times (e.g. on time-window toggle).
 *
 * Public API:
 *   CyclePause.getPauses()                          → array of pause windows
 *   CyclePause.renderSvgBand(svgEl, opts)           → overlay <g> on an SVG chart
 *   CyclePause.renderCanvasBand(ctx, opts)          → fillRect on a canvas chart
 *   CyclePause.filterTrend(trendData, valueKey)     → null out data points inside any pause window
 *
 * Spec: docs/SPEC_CYCLE_PAUSE_VIZ_2026_05_03.md
 * Source DDB: USER#matthew#MEMORY → CYCLE#1.5#gap_move (2026-04-12 → 2026-05-01)
 */

(function (window) {
  'use strict';

  // Hardcoded for now. Future: fetch from /assets/config/cycle_markers.json
  // or from /api/cycle_markers (DDB-backed) — see spec §10 follow-ups.
  var PAUSES = [
    {
      id: 'cycle_1_5_gap_move',
      label: 'Platform Pause · House Move',
      short_label: 'PLATFORM PAUSE',
      start: '2026-04-12',
      end:   '2026-05-01',
      reason: 'House move. Tracking interrupted; resumed May 2.',
      link:   '/elena/2026-05-04-comeback/'  // Link target may not exist yet; tooltip-only for now.
    }
  ];

  function getCyclePauses() { return PAUSES.slice(); }

  /**
   * Filter a trend array, nullifying any value inside a pause window.
   * Charts that draw lines/areas should treat null as a break.
   */
  function filterTrendForPause(trendData, valueKey) {
    if (!trendData || !trendData.length) return trendData;
    return trendData.map(function (d) {
      if (!d || !d.date) return d;
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
   */
  function renderSvgPauseBand(svgEl, opts) {
    if (!svgEl || !opts || !opts.trendData || !opts.trendData.length) return;
    // Idempotent: remove any prior band before re-rendering.
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

      // Find indices (assumes sorted-ascending; spec gotcha §9.4)
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
      // Background fill + dashed border
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

      // Native browser tooltip via <title>
      var title = document.createElementNS(SVG_NS, 'title');
      title.textContent = b.pause.label + ' (' + b.pause.start + ' → ' + b.pause.end + ')';
      rect.appendChild(title);

      // Label text (only if band is wide enough to fit)
      if (b.width > 60) {
        var label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('x', (b.x + 6).toFixed(1));
        label.setAttribute('y', '14');
        label.setAttribute('class', 'cycle-pause-label');
        label.textContent = '⏸ ' + b.pause.short_label;
        g.appendChild(label);
      }
    });

    // Insert as first child so it sits behind data
    if (svgEl.firstChild) svgEl.insertBefore(g, svgEl.firstChild);
    else svgEl.appendChild(g);
  }

  /**
   * Draw pause bands on a canvas chart. Call AFTER the grid lines but BEFORE
   * the data line/area, so the band sits behind data.
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

  /**
   * Chart.js plugin. Reads dates from chart.options.plugins.cyclePause.dates
   * (an array of ISO YYYY-MM-DD strings, aligned with chart.data.labels) and
   * draws a pause band per chart.
   *
   * Usage:
   *   options: { plugins: { cyclePause: { dates: ['2026-03-15', '2026-03-16', ...] } } }
   *   plugins: [CyclePause.chartjsPlugin]
   */
  var chartjsPlugin = {
    id: 'cyclePause',
    beforeDatasetsDraw: function (chart) {
      var cfg = chart.options && chart.options.plugins && chart.options.plugins.cyclePause;
      var dates = cfg && cfg.dates;
      if (!dates || !dates.length) return;
      var area = chart.chartArea;
      if (!area) return;
      var firstDate = dates[0], lastDate = dates[dates.length - 1];
      if (!firstDate || !lastDate) return;
      var ctx = chart.ctx;

      PAUSES.forEach(function (p) {
        if (p.end < firstDate || p.start > lastDate) return;
        var startClamped = p.start < firstDate ? firstDate : p.start;
        var endClamped   = p.end   > lastDate  ? lastDate  : p.end;

        var startIdx = dates.findIndex(function (d) { return d >= startClamped; });
        var endIdx   = dates.findIndex(function (d) { return d >= endClamped; });
        if (startIdx < 0) startIdx = 0;
        if (endIdx < 0) endIdx = dates.length - 1;

        // Use chart's x-scale to map index → pixel.
        var xScale = chart.scales.x;
        var x1 = xScale.getPixelForValue(startIdx);
        var x2 = xScale.getPixelForValue(endIdx);
        var w = Math.max(2, x2 - x1);

        ctx.save();
        ctx.fillStyle = 'rgba(255,255,255,0.04)';
        ctx.fillRect(x1, area.top, w, area.bottom - area.top);

        ctx.strokeStyle = 'rgba(255,255,255,0.10)';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(x1, area.top); ctx.lineTo(x1, area.bottom);
        ctx.moveTo(x1 + w, area.top); ctx.lineTo(x1 + w, area.bottom);
        ctx.stroke();
        ctx.restore();

        if (w > 60) {
          ctx.save();
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '10px monospace';
          ctx.textAlign = 'left';
          ctx.fillText('⏸ ' + p.short_label, x1 + 6, area.top + 14);
          ctx.restore();
        }
      });
    }
  };

  // Expose
  window.CyclePause = {
    getPauses: getCyclePauses,
    filterTrend: filterTrendForPause,
    renderSvgBand: renderSvgPauseBand,
    renderCanvasBand: renderCanvasPauseBand,
    chartjsPlugin: chartjsPlugin
  };
}(window));

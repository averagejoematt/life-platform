/**
 * engagement.js — Phase 1 Reader Engagement utilities
 *
 * Provides: sparkline(), trendArrow(), freshness(), countUp(),
 *           initSinceLastVisit(), initObservatoryWeek(), initObsInsight()
 *
 * Loaded after components.js on pages that use engagement features.
 */
(function() {
  'use strict';

  // ── Sparkline SVG generator (Nadieh Bremer spec) ──────────
  window.amjSparkline = function(data, opts) {
    opts = opts || {};
    var w = opts.width || 100;
    var h = opts.height || 24;
    var color = opts.color || 'var(--accent)';
    var id = 'sf' + Math.random().toString(36).substr(2, 6);

    if (!data || data.length < 2) return '';

    var filtered = data.filter(function(v) { return v != null && !isNaN(v); });
    if (filtered.length < 2) return '';

    var min = Math.min.apply(null, filtered);
    var max = Math.max.apply(null, filtered);
    var range = max - min || 1;

    var points = filtered.map(function(v, i) {
      var x = (i / (filtered.length - 1)) * w;
      var y = h - ((v - min) / range) * (h - 4) - 2;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');

    var last = points.split(' ').pop().split(',');
    var lx = last[0], ly = last[1];
    var fillPoints = '0,' + h + ' ' + points + ' ' + w + ',' + h;

    var trending = filtered[filtered.length - 1] > filtered[0];
    var glow = trending ? ' style="filter:drop-shadow(0 0 3px ' + color + ')"' : '';

    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" class="sparkline">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + color + '" stop-opacity="0.15"/>' +
      '<stop offset="100%" stop-color="' + color + '" stop-opacity="0"/>' +
      '</linearGradient></defs>' +
      '<polygon points="' + fillPoints + '" fill="url(#' + id + ')"/>' +
      '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<circle cx="' + lx + '" cy="' + ly + '" r="2.5" fill="' + color + '"' + glow + '/>' +
      '</svg>';
  };

  // ── Trend arrow system ────────────────────────────────────
  window.amjTrendArrow = function(data, opts) {
    opts = opts || {};
    var color = opts.accentColor || 'var(--accent)';

    if (!data || data.length < 2) return '';

    var filtered = data.filter(function(v) { return v != null && !isNaN(v); });
    if (filtered.length < 2) return '';

    var first = filtered[0], last = filtered[filtered.length - 1];
    var pctChange = Math.abs((last - first) / (first || 1)) * 100;
    var arrow, cls;

    if (pctChange < 1) {
      arrow = '\u2192'; cls = 'trend-indicator__arrow--flat';
    } else if (last > first) {
      arrow = pctChange > 5 ? '\u2191\u2191' : '\u2191';
      cls = 'trend-indicator__arrow--up';
    } else {
      arrow = pctChange > 5 ? '\u2193\u2193' : '\u2193';
      cls = 'trend-indicator__arrow--down';
    }

    return '<span class="trend-indicator">' +
      '<span class="' + cls + '" style="color:' + (cls.indexOf('up') > -1 ? color : 'var(--text-faint)') + '">' + arrow + '</span>' +
      '</span>';
  };

  // ── Count-up animation (Janum Trivedi spec) ───────────────
  window.amjCountUp = function(el, target, duration) {
    duration = duration || 800;
    var start = parseFloat(el.textContent) || 0;
    var range = target - start;
    if (Math.abs(range) < 0.01) { el.textContent = target; return; }
    var startTime = performance.now();
    var decimals = (target % 1 !== 0) ? 1 : 0;
    function step(now) {
      var progress = Math.min((now - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = (start + range * eased).toFixed(decimals);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  };

  // ── Freshness indicator ───────────────────────────────────
  window.amjFreshness = function(isoDateStr) {
    if (!isoDateStr) return { text: 'No data', cls: '', dotCls: '' };

    var updated = new Date(isoDateStr);
    var now = new Date();
    var hoursAgo = Math.floor((now - updated) / 3600000);
    var daysAgo = Math.floor((now - updated) / 86400000);

    if (hoursAgo < 6) {
      return { text: hoursAgo + 'h ago', cls: '--fresh-0h', dotCls: 'obs-freshness__dot--live' };
    } else if (hoursAgo < 24) {
      return { text: 'today', cls: '--fresh-1d', dotCls: '' };
    } else if (daysAgo <= 3) {
      return { text: daysAgo + ' days ago', cls: '--fresh-3d', dotCls: 'obs-freshness__dot--amber' };
    } else {
      var m = updated.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return { text: m, cls: '--fresh-stale', dotCls: 'obs-freshness__dot--stale' };
    }
  };

  // ── "Since Your Last Visit" (homepage) ────────────────────
  var LAST_VISIT_KEY = 'amj_last_visit';

  window.initSinceLastVisit = async function() {
    var container = document.getElementById('amj-since-last-visit');
    if (!container) return;

    var lastTs = localStorage.getItem(LAST_VISIT_KEY);
    if (!lastTs) {
      localStorage.setItem(LAST_VISIT_KEY, Date.now().toString());
      return;
    }

    var daysSince = Math.floor((Date.now() - parseInt(lastTs)) / 86400000);
    // Guard: if timestamp is corrupted or way too old, reset and skip
    if (daysSince < 1 || daysSince > 365) {
      localStorage.setItem(LAST_VISIT_KEY, Date.now().toString());
      if (daysSince > 365) return;
      return;
    }

    try {
      var resp = await fetch('/api/changes-since?ts=' + Math.floor(parseInt(lastTs) / 1000));
      if (!resp.ok) return;
      var data = await resp.json();
      if (!data.deltas || Object.keys(data.deltas).length === 0) return;

      var daysLabel = daysSince === 1 ? '1 day' : daysSince + ' days';
      var html = '<div class="since-last-visit reveal">';
      html += '<div class="since-last-visit__header">';
      html += '<div class="since-last-visit__heading">Since your last visit</div>';
      html += '<div class="since-last-visit__sub">' + daysLabel + ' ago \u2014 here\u2019s what changed</div>';
      html += '<button class="since-last-visit__dismiss" onclick="this.closest(\'.since-last-visit\').remove()" aria-label="Dismiss">\u00D7</button>';
      html += '</div>';
      html += '<div class="since-last-visit__grid">';

      var metrics = [
        { key: 'weight', label: 'Weight', suffix: ' lbs' },
        { key: 'hrv', label: 'HRV', suffix: 'ms' },
        { key: 'sleep', label: 'Sleep', suffix: 'h' },
        { key: 'character', label: 'Character', suffix: ' pts' },
      ];

      metrics.forEach(function(m) {
        var d = data.deltas[m.key];
        html += '<div class="since-last-visit__metric">';
        html += '<div class="since-last-visit__metric-label">' + m.label + '</div>';
        if (d) {
          var sign = d.change >= 0 ? '+' : '';
          html += '<div class="since-last-visit__metric-delta">' + d.from + '\u2192' + d.to + '</div>';
          html += '<div class="since-last-visit__metric-change">' + sign + d.change + m.suffix + ' ' + amjTrendArrow(d.sparkline) + '</div>';
          if (d.sparkline) html += '<div>' + amjSparkline(d.sparkline, { width: 80, height: 20 }) + '</div>';
        } else {
          html += '<div class="since-last-visit__metric-delta">\u2014</div>';
        }
        html += '</div>';
      });

      html += '</div>';

      if (data.events && data.events.length) {
        html += '<div class="since-last-visit__events">';
        data.events.forEach(function(e) {
          html += '<div class="since-last-visit__event">\u25B8 <strong>NEW:</strong> ' + e.title + '</div>';
        });
        html += '</div>';
      }

      html += '</div>';
      container.innerHTML = html;

      // Trigger reveal animation — class must be 'is-visible' to match CSS
      setTimeout(function() {
        var el = container.querySelector('.since-last-visit');
        if (el) el.classList.add('is-visible');
      }, 100);
    } catch (e) {
      console.warn('Changes-since unavailable:', e);
    }

    localStorage.setItem(LAST_VISIT_KEY, Date.now().toString());
  };

  // ── Observatory "This Week" card ──────────────────────────
  window.initObservatoryWeek = async function(domain, containerId) {
    var container = document.getElementById(containerId || 'obs-thisweek');
    if (!container) return;

    try {
      var resp = await fetch('/api/observatory_week?domain=' + domain);
      if (!resp.ok) return;
      var data = await resp.json();
      var s = data.summary;
      if (!s || !s.primary) return;

      var accentColors = {
        sleep: '#60a5fa', glucose: '#2dd4bf', nutrition: '#f59e0b',
        training: '#ef4444', mind: '#818cf8'
      };
      var accent = accentColors[domain] || 'var(--accent)';

      var html = '<div class="obs-thisweek__header">This week in ' + domain + '</div>';
      html += '<div class="obs-thisweek__grid">';

      // Col 1: Primary metric
      html += '<div class="obs-thisweek__col">';
      html += '<div class="obs-thisweek__label">' + s.primary.label + '</div>';
      html += '<div class="obs-thisweek__value" style="color:' + accent + '">' + s.primary.value + '<span style="font-size:14px;color:var(--text-muted)"> ' + s.primary.unit + '</span></div>';
      if (s.primary.sparkline) html += amjSparkline(s.primary.sparkline, { width: 100, height: 28, color: accent });
      html += '<div class="obs-thisweek__delta">' + s.primary.delta_label + '</div>';
      html += '</div>';

      // Col 2: Highlight
      html += '<div class="obs-thisweek__col">';
      html += '<div class="obs-thisweek__label">' + s.highlight.label + '</div>';
      html += '<div class="obs-thisweek__value" style="font-size:clamp(16px,2vw,22px)">' + s.highlight.value + '</div>';
      if (s.highlight.detail) html += '<div class="obs-thisweek__detail">' + s.highlight.detail + '</div>';
      html += '</div>';

      // Col 3: Lowlight
      html += '<div class="obs-thisweek__col">';
      html += '<div class="obs-thisweek__label">' + s.lowlight.label + '</div>';
      html += '<div class="obs-thisweek__value" style="font-size:clamp(16px,2vw,22px)">' + s.lowlight.value + '</div>';
      if (s.lowlight.detail) html += '<div class="obs-thisweek__detail">' + s.lowlight.detail + '</div>';
      html += '</div>';

      html += '</div>';

      // Notable
      if (data.notable) {
        html += '<div class="obs-thisweek__notable">\u25B8 <strong>NOTABLE:</strong> ' + data.notable + '</div>';
      }

      container.innerHTML = html;
      container.style.display = '';
    } catch (e) {
      console.warn('Observatory week unavailable:', e);
    }
  };

  // ── Freshness indicator injection ─────────────────────────
  window.initObsFreshness = function(lastUpdatedISO, containerId) {
    var container = document.getElementById(containerId || 'obs-freshness');
    if (!container) return;

    var f = amjFreshness(lastUpdatedISO);
    var timeEl = container.querySelector('#obs-fresh-time');
    var dotEl = container.querySelector('#obs-fresh-dot');
    if (timeEl) timeEl.textContent = f.text;
    if (dotEl) {
      dotEl.className = 'obs-freshness__dot';
      if (f.dotCls) dotEl.classList.add(f.dotCls);
    }
    container.style.display = '';
  };

  // ── Phase 4: The Pulse Feed ────────────────────────────
  var _pulseItems = [];
  var _pulseOffset = 0;
  var PULSE_PAGE = 10;

  window.loadMorePulse = function() {
    var list = document.getElementById('pulse-list');
    var loadMore = document.getElementById('pulse-load-more');
    if (!list || !_pulseItems.length) return;

    var batch = _pulseItems.slice(_pulseOffset, _pulseOffset + PULSE_PAGE);
    batch.forEach(function(item) {
      list.insertAdjacentHTML('beforeend', _renderPulseItem(item));
    });
    _pulseOffset += PULSE_PAGE;

    if (_pulseOffset >= _pulseItems.length && loadMore) {
      loadMore.style.display = 'none';
    }
  };

  function _renderPulseItem(item) {
    var pipCls = 'pulse-feed__pip pulse-feed__pip--' + (item.domain || 'body');
    var timeStr = '';
    if (item.date) {
      var d = new Date(item.date + 'T12:00:00');
      timeStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }
    var sparkHtml = '';
    if (item.sparkline && typeof amjSparkline === 'function') {
      var pipColors = { body: '#f59e0b', sleep: '#60a5fa', glucose: '#2dd4bf', training: '#ef4444', mind: '#818cf8', nutrition: '#f59e0b', story: '#f59e0b', science: '#a78bfa' };
      sparkHtml = '<div class="pulse-feed__spark">' + amjSparkline(item.sparkline, { width: 80, height: 20, color: pipColors[item.domain] || '#f59e0b' }) + '</div>';
    }

    return '<a href="' + (item.link || '#') + '" class="pulse-feed__item">' +
      '<span class="' + pipCls + '"></span>' +
      '<span class="pulse-feed__time">' + timeStr + '</span>' +
      '<div class="pulse-feed__content">' +
        '<div class="pulse-feed__headline">' + (item.headline || '') + '</div>' +
        '<div class="pulse-feed__detail">' + (item.detail || '') + '</div>' +
      '</div>' +
      sparkHtml +
    '</a>';
  }

  window.initPulseFeed = async function() {
    var section = document.getElementById('amj-pulse-section');
    if (!section) return;

    // Don't show Pulse feed before launch
    if (new Date() < new Date('2026-04-01T00:00:00')) return;

    try {
      // Build pulse items from multiple data sources
      var items = [];

      // Source 1: Pulse endpoint (pre-computed daily signal)
      var pulseResp = await fetch('/api/pulse').catch(function() { return null; });
      if (pulseResp && pulseResp.ok) {
        var pulseData = await pulseResp.json();
        var p = pulseData.pulse || pulseData;
        if (p && p.narrative) {
          items.push({
            domain: 'body',
            date: p.date || new Date().toISOString().split('T')[0],
            headline: (function() {
              var launch = new Date('2026-04-01T00:00:00');
              var now = new Date();
              if (now < launch) {
                var daysUntil = Math.ceil((launch - now) / 86400000);
                return 'T-' + daysUntil + ' \u2014 ' + (p.status || 'quiet');
              }
              var daysSince = Math.floor((now - launch) / 86400000) + 1;
              return 'Day ' + daysSince + ' \u2014 ' + (p.status || 'quiet');
            })(),
            detail: p.narrative,
            link: '/live/',
            sparkline: null,
          });
        }
        // Add glyph-based items
        var glyphs = p.glyphs || {};
        if (glyphs.scale && glyphs.scale.value) {
          items.push({
            domain: 'body',
            date: p.date,
            headline: 'Weight: ' + glyphs.scale.value + ' lbs' + (glyphs.scale.delta ? ' (' + (glyphs.scale.delta > 0 ? '+' : '') + glyphs.scale.delta + ')' : ''),
            detail: glyphs.scale.direction === 'down' ? 'Trending down' : glyphs.scale.direction === 'up' ? 'Trending up' : 'Holding steady',
            link: '/live/',
            sparkline: glyphs.scale.sparkline_7d,
          });
        }
        if (glyphs.recovery && glyphs.recovery.recovery_pct) {
          items.push({
            domain: 'training',
            date: p.date,
            headline: 'Recovery: ' + Math.round(glyphs.recovery.recovery_pct) + '%',
            detail: 'HRV ' + Math.round(glyphs.recovery.hrv_ms || 0) + 'ms \u00B7 RHR ' + Math.round(glyphs.recovery.rhr_bpm || 0) + 'bpm',
            link: '/training/',
            sparkline: glyphs.recovery.sparkline_7d,
          });
        }
        if (glyphs.sleep && glyphs.sleep.hours) {
          items.push({
            domain: 'sleep',
            date: p.date,
            headline: 'Sleep: ' + glyphs.sleep.hours.toFixed(1) + 'h' + (glyphs.sleep.score ? ' \u00B7 Score ' + glyphs.sleep.score : ''),
            detail: '',
            link: '/sleep/',
            sparkline: glyphs.sleep.sparkline_7d,
          });
        }
        if (glyphs.movement && glyphs.movement.zone2_week_min) {
          items.push({
            domain: 'training',
            date: p.date,
            headline: 'Zone 2: ' + Math.round(glyphs.movement.zone2_week_min) + ' min this week',
            detail: glyphs.movement.zone2_week_min >= 150 ? 'Target met \u2713' : Math.round(150 - glyphs.movement.zone2_week_min) + ' min to go',
            link: '/training/',
            sparkline: glyphs.movement.sparkline_7d,
          });
        }
        if (glyphs.water && glyphs.water.liters) {
          var wPct = Math.round(glyphs.water.liters / (glyphs.water.target || 3.0) * 100);
          items.push({
            domain: 'body',
            date: p.date,
            headline: 'Water: ' + glyphs.water.liters.toFixed(1) + 'L' + (glyphs.water.target ? ' / ' + glyphs.water.target + 'L' : ''),
            detail: wPct >= 100 ? 'Target met \u2713' : wPct + '% of daily target',
            link: '/live/',
            sparkline: glyphs.water.sparkline_7d,
          });
        }
        if (glyphs.journal && glyphs.journal.streak_days) {
          items.push({
            domain: 'mind',
            date: p.date,
            headline: 'Journal streak: ' + glyphs.journal.streak_days + ' days',
            detail: glyphs.journal.written_today ? 'Written today' : 'Not yet today',
            link: '/mind/',
            sparkline: null,
          });
        }
      }

      // Source 2: Pulse history — daily log from April 1 onward
      var histResp = await fetch('/api/pulse_history').catch(function() { return null; });
      if (histResp && histResp.ok) {
        var histData = await histResp.json();
        var history = (histData.pulse_history || []).reverse(); // most recent first
        history.forEach(function(day) {
          if (day.headline === 'No data recorded') return;
          // Skip today — already covered by live pulse above
          if (day.date === new Date().toISOString().split('T')[0]) return;
          var detailParts = [];
          if (day.hrv_ms) detailParts.push('HRV ' + day.hrv_ms + 'ms');
          if (day.steps) detailParts.push(day.steps.toLocaleString() + ' steps');
          items.push({
            domain: day.recovery_pct && day.recovery_pct >= 67 ? 'training' : day.sleep_hours ? 'sleep' : 'body',
            date: day.date,
            headline: 'Day ' + day.day_number + ' \u2014 ' + day.headline,
            detail: detailParts.join(' \u00B7 '),
            link: '/live/',
            sparkline: null,
          });
        });
      }

      // Governance check: minimum items to show section
      if (items.length < 3) return;

      _pulseItems = items;
      _pulseOffset = 0;

      // Show first batch
      var list = document.getElementById('pulse-list');
      var batch = _pulseItems.slice(0, PULSE_PAGE);
      list.innerHTML = '';
      batch.forEach(function(item) {
        list.insertAdjacentHTML('beforeend', _renderPulseItem(item));
      });
      _pulseOffset = PULSE_PAGE;

      if (_pulseItems.length > PULSE_PAGE) {
        document.getElementById('pulse-load-more').style.display = '';
      }

      // Delay visibility until after CSS has applied to prevent FOUC (plain text flash on mobile)
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          section.style.display = '';
        });
      });
    } catch (e) {
      console.warn('Pulse feed unavailable:', e);
    }
  };

})();

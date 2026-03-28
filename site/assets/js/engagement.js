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
    if (daysSince < 1) return;

    try {
      var resp = await fetch('/api/changes-since?ts=' + Math.floor(parseInt(lastTs) / 1000));
      if (!resp.ok) return;
      var data = await resp.json();
      if (!data.deltas || Object.keys(data.deltas).length === 0) return;

      var html = '<div class="since-last-visit reveal">';
      html += '<div class="since-last-visit__header">';
      html += '<span class="since-last-visit__title">// Since your last visit \u00B7 ' + daysSince + ' day' + (daysSince > 1 ? 's' : '') + ' ago</span>';
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

      // Trigger reveal animation
      setTimeout(function() {
        var el = container.querySelector('.since-last-visit');
        if (el) el.classList.add('visible');
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

  // ── Phase 2: Dynamic observatory selection ─────────────
  // Picks the observatory with the most dramatic recent data
  window.amjPickBestObservatory = async function() {
    try {
      var resp = await fetch('/api/snapshot');
      if (!resp.ok) return { id: 'sleep', path: '/sleep/', label: 'Sleep' };
      var stats = await resp.json();
      var trends = (stats.vitals || {});

      var domains = [
        { id: 'sleep', path: '/sleep/', label: 'Sleep', val: trends.sleep_hours || 0 },
        { id: 'glucose', path: '/glucose/', label: 'Glucose', val: 0 },
        { id: 'training', path: '/training/', label: 'Training', val: 0 },
        { id: 'nutrition', path: '/nutrition/', label: 'Nutrition', val: 0 },
        { id: 'mind', path: '/mind/', label: 'Inner Life', val: 0 },
      ];

      // Simple heuristic: pick the domain with data, prefer sleep as default
      return domains[0];
    } catch (e) {
      return { id: 'sleep', path: '/sleep/', label: 'Sleep' };
    }
  };

  // ── Phase 2: Update guided path Step 3 with best observatory ──
  window.initGuidedPathDynamic = async function() {
    var bar = document.getElementById('amj-guided-path');
    if (!bar) return;

    var best = await amjPickBestObservatory();
    var steps = bar.querySelectorAll('.guided-path__step');
    // Step 3 is index 2 (0=Story, 1=Live, 2=Explore)
    if (steps[2]) {
      steps[2].textContent = best.label;
      steps[2].href = best.path;
    }
  };

  // ── Phase 2: Enhanced subscribe CTA for guided-path users ─
  window.initGuidedSubscribeCTA = function() {
    var GUIDED_KEY = 'amj_guided_path';
    var completed = [];
    try { completed = JSON.parse(localStorage.getItem(GUIDED_KEY) || '[]'); } catch(e) {}

    // Only enhance if user has visited story + live + at least one observatory
    if (completed.indexOf('story') === -1 || completed.indexOf('live') === -1) return;
    var hasObservatory = completed.indexOf('sleep') > -1 || completed.indexOf('glucose') > -1 ||
                         completed.indexOf('training') > -1 || completed.indexOf('nutrition') > -1 ||
                         completed.indexOf('mind') > -1;
    if (!hasObservatory) return;

    var cta = document.getElementById('amj-guided-cta');
    if (!cta) return;

    cta.innerHTML = '<section style="padding:var(--space-12) var(--page-padding);border-top:1px solid var(--border);border-bottom:1px solid var(--border);text-align:center;max-width:var(--max-width);margin:0 auto">' +
      '<p style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:0.15em;text-transform:uppercase;color:var(--c-amber-500);margin-bottom:var(--space-4)">// You\'ve seen the full picture</p>' +
      '<h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-4)">Every Wednesday, the numbers move.</h3>' +
      '<p style="font-size:var(--text-base);color:var(--text-muted);max-width:440px;margin:0 auto var(--space-6);line-height:1.7">Subscribe to see where this goes.<br>3-minute read. Real data. Every failure included.</p>' +
      '<div style="display:flex;gap:var(--space-2);max-width:400px;margin:0 auto">' +
      '<input type="email" id="guided-cta-email" placeholder="your@email.com" style="flex:1;background:var(--bg);border:1px solid var(--cta);color:var(--text);font-family:var(--font-mono);font-size:var(--text-xs);padding:var(--space-3) var(--space-4);outline:none">' +
      '<button onclick="amjSubscribe(\'guided\')" class="btn btn--cta" style="white-space:nowrap">Follow the journey \u2192</button>' +
      '</div>' +
      '<p id="cta-msg-guided" style="font-size:var(--text-2xs);color:var(--text-faint);margin-top:var(--space-3);min-height:1em"></p>' +
      '</section>';
    cta.style.display = '';
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
    var pipCls = 'pulse__pip pulse__pip--' + (item.domain || 'body');
    var timeStr = '';
    if (item.date) {
      var d = new Date(item.date + 'T12:00:00');
      timeStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }
    var sparkHtml = '';
    if (item.sparkline && typeof amjSparkline === 'function') {
      var pipColors = { body: '#f59e0b', sleep: '#60a5fa', glucose: '#2dd4bf', training: '#ef4444', mind: '#818cf8', nutrition: '#f59e0b', story: '#f59e0b', science: '#a78bfa' };
      sparkHtml = '<div class="pulse__spark">' + amjSparkline(item.sparkline, { width: 80, height: 20, color: pipColors[item.domain] || '#f59e0b' }) + '</div>';
    }

    return '<a href="' + (item.link || '#') + '" class="pulse__item">' +
      '<span class="' + pipCls + '"></span>' +
      '<span class="pulse__time">' + timeStr + '</span>' +
      '<div class="pulse__content">' +
        '<div class="pulse__headline">' + (item.headline || '') + '</div>' +
        '<div class="pulse__detail">' + (item.detail || '') + '</div>' +
      '</div>' +
      sparkHtml +
    '</a>';
  }

  window.initPulseFeed = async function() {
    var section = document.getElementById('amj-pulse-section');
    if (!section) return;

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
            headline: 'Day ' + (p.day_number || '?') + ' \u2014 ' + (p.status || 'quiet'),
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

      // Source 2: Snapshot for journey milestones
      var snapResp = await fetch('/api/snapshot').catch(function() { return null; });
      if (snapResp && snapResp.ok) {
        var snap = await snapResp.json();
        var journey = (snap.journey || {}).journey || snap.journey || {};
        if (journey.lost_lbs && journey.lost_lbs > 0) {
          items.push({
            domain: 'body',
            date: new Date().toISOString().split('T')[0],
            headline: Math.round(journey.lost_lbs) + ' lbs lost from ' + Math.round(journey.start_weight_lbs || 302) + ' lbs',
            detail: Math.round(journey.progress_pct || 0) + '% to goal \u00B7 Day ' + (journey.days_in || '?'),
            link: '/live/',
            sparkline: null,
          });
        }
        var character = (snap.character || {}).character || {};
        if (character.level) {
          items.push({
            domain: 'story',
            date: new Date().toISOString().split('T')[0],
            headline: 'Character Level ' + Math.floor(character.level) + (character.tier ? ' \u2014 ' + character.tier : ''),
            detail: 'Gamified health score across 7 pillars',
            link: '/character/',
            sparkline: null,
          });
        }
      }

      // Governance check: minimum 8 items
      if (items.length < 5) return; // Not enough content yet

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

      section.style.display = '';
    } catch (e) {
      console.warn('Pulse feed unavailable:', e);
    }
  };

})();

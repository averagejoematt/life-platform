/**
 * observatory-v3.js — Shared V3 observatory rendering module.
 * PB-09: Coach-led dashboard pattern.
 * V3.1: Deltas, subtitles, dividers, teasers, journaling prompt.
 *
 * Named function exports (per Elena Reyes, Tech Board):
 *   renderSubtitle(container, text)
 *   renderStatusBar(container, metrics, opts)
 *   renderCoachAnalysis(container, expertKey, coachMeta)
 *   renderTrends(container, chartConfigs, trendData)
 *   renderWeekDetail(container, detailCards, data)
 *   renderCrossDomain(container, links)
 *   renderDepth(container, sections)
 *   computeDelta(dataArray, valueKey, daysBack)
 */

/* ── Helpers ───────────────────────────────────────────────── */

function _el(tag, cls, html) {
  var d = document.createElement(tag);
  if (cls) d.className = cls;
  if (html) d.innerHTML = html;
  return d;
}

function _freshnessDot(hoursAgo) {
  if (hoursAgo < 24)  return 'obs-status-dot obs-status-dot--live';
  if (hoursAgo < 48)  return 'obs-status-dot obs-status-dot--stale';
  return 'obs-status-dot obs-status-dot--old';
}

function _timeSince(isoDate) {
  if (!isoDate) return { text: 'Unknown', hours: 999 };
  var diff = (Date.now() - new Date(isoDate).getTime()) / 3600000;
  if (diff < 1)  return { text: 'Just now', hours: diff };
  if (diff < 24) return { text: Math.round(diff) + 'h ago', hours: diff };
  return { text: Math.round(diff / 24) + 'd ago', hours: diff };
}

/* ── V3.1 Item 1: Delta computation ───────────────────────── */

/**
 * Compute week-over-week delta from trend data already on the page.
 * @param {Array} dataArray — 30-day trend array [{date, ...values}]
 * @param {string} valueKey — field name to compare (e.g. 'sleep_score')
 * @param {number} daysBack — comparison window (default 7)
 * @returns {{delta, currentAvg, priorAvg, label, early}}
 */
function computeDelta(dataArray, valueKey, daysBack) {
  daysBack = daysBack || 7;
  if (!dataArray || dataArray.length < 3) return { delta: null, label: '\u2014 insufficient data' };

  var now = new Date();
  var current = [], prior = [];
  dataArray.forEach(function(d) {
    if (d[valueKey] == null) return;
    var daysDiff = (now - new Date(d.date)) / 86400000;
    if (daysDiff <= daysBack) current.push(d[valueKey]);
    else if (daysDiff <= daysBack * 2) prior.push(d[valueKey]);
  });

  if (current.length < 1 || prior.length < 1) return { delta: null, label: '\u2014 insufficient data' };

  var avg = function(arr) { return arr.reduce(function(a,b){return a+b},0) / arr.length; };
  var currentAvg = avg(current);
  var priorAvg = avg(prior);
  var delta = currentAvg - priorAvg;
  var early = current.length < 4 || prior.length < 4;

  return { delta: delta, currentAvg: currentAvg, priorAvg: priorAvg, early: early };
}

function _renderDelta(delta, polarity, unit) {
  // polarity: 'higher_better', 'lower_better', 'neutral'
  if (delta == null) return '<span class="obs-delta-none">\u2014</span>';

  var absDelta = Math.abs(delta);
  // Flat threshold: change < 2% of the value or < 0.5 absolute
  if (absDelta < 0.5) return '<span class="obs-delta-flat">\u2192 flat</span>';

  var sign = delta > 0 ? '+' : '';
  var arrow = delta > 0 ? '\u2191' : '\u2193';
  var isGood = polarity === 'higher_better' ? delta > 0 :
               polarity === 'lower_better' ? delta < 0 : null;
  var cls = isGood === true ? 'obs-delta-up' :
            isGood === false ? 'obs-delta-down' : 'obs-delta-flat';

  return '<span class="' + cls + '">' + sign + absDelta.toFixed(1) + (unit || '') + ' ' + arrow + '</span>';
}

/* ── V3.1 Item 3: Subtitle ────────────────────────────────── */

function renderSubtitle(container, text) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el) return;
  el.innerHTML = '<p class="obs-subtitle">' + text + '</p>';
}

/* ── Section 1: Status Bar ─────────────────────────────────── */

/**
 * @param {string|HTMLElement} container
 * @param {Array} metrics — [{label, value, unit, delta, deltaUnit, polarity, context, inverted}]
 *   polarity: 'higher_better' | 'lower_better' | 'neutral' (default: 'higher_better')
 * @param {Object} opts — {lastUpdated: ISO string, subtitle: string}
 */
function renderStatusBar(container, metrics, opts) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el) return;
  opts = opts || {};

  var grid = _el('div', 'obs-status-grid');

  metrics.forEach(function(m) {
    var polarity = m.polarity || (m.inverted ? 'lower_better' : 'higher_better');
    var deltaHtml = _renderDelta(m.delta, polarity, m.deltaUnit || '');

    var cell = _el('div', 'obs-status-cell');
    cell.innerHTML =
      '<div class="obs-status-cell__label">' + (m.label || '') + '</div>' +
      '<div class="obs-status-cell__value">' + (m.value != null ? m.value : '\u2014') +
        (m.unit ? '<span style="font-size:14px;color:var(--text-muted);margin-left:4px">' + m.unit + '</span>' : '') + '</div>' +
      '<div class="obs-status-cell__delta">' + deltaHtml + '</div>' +
      '<div class="obs-status-cell__context">' + (m.context || '') + '</div>';
    grid.appendChild(cell);
  });

  el.innerHTML = '';
  el.className = 'obs-status';
  el.appendChild(grid);

  if (opts.lastUpdated) {
    var ts = _timeSince(opts.lastUpdated);
    var fresh = _el('div', 'obs-status-freshness');
    fresh.innerHTML =
      '<span>Updated ' + ts.text + '</span>' +
      '<span class="' + _freshnessDot(ts.hours) + '"></span>';
    el.appendChild(fresh);
  }
}

/* ── Section 2: Coach Analysis ─────────────────────────────── */

/**
 * @param {string|HTMLElement} container
 * @param {string} expertKey — 'sleep', 'glucose', etc.
 * @param {Object} coachMeta — {name, initials, title, color}
 */
function renderCoachAnalysis(container, expertKey, coachMeta) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el) return;

  el.className = 'obs-coach';
  el.innerHTML =
    '<div class="obs-coach-header">' +
      '<div class="obs-coach-avatar" style="background:' + (coachMeta.color || 'var(--accent)') + '">' + (coachMeta.initials || '??') + '</div>' +
      '<div class="obs-coach-meta">' +
        '<div class="obs-coach-name">' + (coachMeta.name || '') + '</div>' +
        '<div class="obs-coach-title">' + (coachMeta.title || '') + '</div>' +
        '<div class="obs-coach-generated" id="obs-coach-gen-' + expertKey + '"></div>' +
      '</div>' +
    '</div>' +
    '<div class="obs-coach-prose" id="obs-coach-prose-' + expertKey + '"><div style="font-family:var(--font-mono);font-size:10px;color:var(--text-faint);letter-spacing:0.1em">LOADING ANALYSIS...</div></div>' +
    '<div class="obs-coach-action" id="obs-coach-action-' + expertKey + '" style="display:none"></div>';

  // Try Coach Intelligence endpoint first, fall back to legacy ai_analysis
  fetch('/api/coach_analysis?domain=' + expertKey)
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      // Fall back to legacy endpoint if new one returns null analysis
      if (!data || !data.analysis) {
        return fetch('/api/ai_analysis?expert=' + expertKey)
          .then(function(r2) { return r2.ok ? r2.json() : null; });
      }
      return data;
    })
    .then(function(data) {
      if (!data) return;

      // Use coach_name from response if available (Coach Intelligence provides it)
      if (data.coach_name) {
        var nameEl = el.querySelector('.obs-coach-name');
        if (nameEl) nameEl.textContent = data.coach_name;
      }

      var proseEl = document.getElementById('obs-coach-prose-' + expertKey);
      var actionEl = document.getElementById('obs-coach-action-' + expertKey);
      var genEl = document.getElementById('obs-coach-gen-' + expertKey);

      if (data.analysis) {
        var paragraphs = data.analysis.split('\n\n').filter(function(p) { return p.trim(); });
        var proseHtml = paragraphs.map(function(p) { return '<p>' + p + '</p>'; }).join('');

        // Data availability indicator
        if (data.data_availability === 'observational_only') {
          proseHtml = '<div class="obs-coach-data-flag obs-coach-data-flag--early">\u26f6 Early data \u2014 observing patterns</div>' + proseHtml;
        }

        proseEl.innerHTML = proseHtml;
      } else {
        proseEl.innerHTML = '<p style="color:var(--text-faint)">Analysis generates daily. Check back soon.</p>';
      }

      if (data.key_recommendation && data.data_availability !== 'observational_only') {
        actionEl.style.display = '';
        actionEl.innerHTML =
          '<div class="obs-coach-action__label">This week\'s action</div>' +
          '<div class="obs-coach-action__text">' + data.key_recommendation + '</div>';
      }

      if (data.generated_at) {
        var genDate = new Date(data.generated_at);
        var dayName = genDate.toLocaleDateString('en-US', { weekday: 'long' });
        var dateFmt = genDate.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
        var expStart = new Date('2026-04-01');
        var expDay = Math.max(1, Math.floor((genDate - expStart) / 86400000) + 1);
        genEl.innerHTML = '<strong>' + dayName + ', ' + dateFmt + '</strong> \u00b7 Day ' + expDay + ' Observations';
      }

      // Continuity markers — subtle footer with thread, revision, cross-coach signals
      var markers = [];
      if (data.thread_reference) {
        markers.push('\ud83d\udccc ' + data.thread_reference);
      }
      if (data.revision_signal) {
        markers.push('\u21bb ' + data.revision_signal);
      }
      if (data.cross_coach_reference) {
        markers.push('\ud83d\udd17 ' + data.cross_coach_reference);
      }
      if (markers.length > 0) {
        var markerDiv = _el('div', 'obs-coach-continuity');
        markerDiv.innerHTML = markers.map(function(m) {
          return '<div class="obs-coach-continuity__item">' + m + '</div>';
        }).join('');
        el.appendChild(markerDiv);
      }

      // Elena quote
      if (data.elena_quote) {
        var quoteDiv = _el('div', 'obs-elena-quote');
        quoteDiv.innerHTML =
          '\u201c' + data.elena_quote + '\u201d' +
          '<div class="obs-elena-quote__attr">Elena Voss \u00b7 <a href="/chronicle/">Chronicle \u2192</a></div>';
        el.appendChild(quoteDiv);
      }

      // Journaling prompt (Mind page only)
      if (data.journaling_prompt) {
        var promptDiv = _el('div', 'obs-journaling-prompt');
        promptDiv.innerHTML =
          '<span class="obs-journaling-label">THIS WEEK\u2019S JOURNALING PROMPT</span>' +
          '<p>' + data.journaling_prompt + '</p>';
        el.appendChild(promptDiv);
      }

      // Subscribe CTA
      var cta = _el('div', 'obs-subscribe-inline');
      cta.innerHTML =
        '<span class="obs-subscribe-inline__text">Want this analysis weekly?</span>' +
        '<a class="obs-subscribe-inline__btn" href="/accountability/#subscribe">Subscribe</a>';
      el.appendChild(cta);
    })
    .catch(function() {
      var proseEl = document.getElementById('obs-coach-prose-' + expertKey);
      if (proseEl) proseEl.innerHTML = '<p style="color:var(--text-faint)">Analysis unavailable.</p>';
    });
}

/* ── Section 3: Trends ─────────────────────────────────────── */

function renderTrends(container, opts) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el) return;
  opts = opts || {};

  el.className = 'obs-trends';
  var chartPair = (opts.chartIds || []).map(function(id, i) {
    return '<div class="obs-trend-chart">' +
      '<div class="obs-trend-chart__label">' + ((opts.labels || [])[i] || '') + '</div>' +
      '<div id="' + id + '"></div>' +
    '</div>';
  }).join('');

  el.innerHTML =
    '<div class="obs-trends__header">' +
      '<div class="obs-trends__title">' + (opts.title || 'Trends') + '</div>' +
      '<div class="obs-time-toggles" id="obs-trend-toggles">' +
        '<button class="obs-time-toggle" data-days="7">7d</button>' +
        '<button class="obs-time-toggle active" data-days="30">30d</button>' +
        '<button class="obs-time-toggle" data-days="90">90d</button>' +
      '</div>' +
    '</div>' +
    '<div class="obs-trend-row">' + chartPair + '</div>';
}

/* ── Section 4: This Week's Detail ─────────────────────────── */

function renderWeekDetail(container, cards) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el || !cards || !cards.length) return;

  el.className = 'obs-detail';
  var grid = cards.map(function(c) {
    return '<div class="obs-detail-card">' +
      '<div class="obs-detail-card__label">' + (c.label || '') + '</div>' +
      '<div class="obs-detail-card__value"' + (c.colorClass ? ' class="' + c.colorClass + '"' : '') + '>' + (c.value != null ? c.value : '\u2014') + '</div>' +
      '<div class="obs-detail-card__context">' + (c.context || '') + '</div>' +
    '</div>';
  }).join('');

  el.innerHTML =
    '<div class="obs-detail__title">This Week\u2019s Detail</div>' +
    '<div class="obs-detail-grid">' + grid + '</div>';
}

/* ── Section 5: Cross-Domain ───────────────────────────────── */

function renderCrossDomain(container, links) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el || !links || !links.length) return;

  el.className = 'obs-cross';
  var cards = links.map(function(l) {
    return '<a href="' + l.link + '" class="obs-cross-link">' +
      '<div class="obs-cross-link__arrow">' + l.title + '</div>' +
      '<div class="obs-cross-link__finding">' + l.finding + '</div>' +
    '</a>';
  }).join('');

  el.innerHTML =
    '<div class="obs-cross__title">Cross-Domain Connections</div>' +
    '<div class="obs-cross-grid">' + cards + '</div>';
}

/* ── Section 6: Depth (Collapsible) ────────────────────────── */

/**
 * @param {string|HTMLElement} container
 * @param {Array} sections — [{label, id, content, teaser}]
 */
function renderDepth(container, sections) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el || !sections || !sections.length) return;

  el.className = 'obs-depth';
  var cards = sections.map(function(s) {
    var teaserHtml = s.teaser ? '<span class="obs-depth-teaser">' + s.teaser + '</span>' : '';
    return '<details class="obs-depth-section" id="depth-' + s.id + '">' +
      '<summary>' + s.label + teaserHtml + '</summary>' +
      '<div class="obs-depth-section__body">' + (s.content || '<p>Content loading...</p>') + '</div>' +
    '</details>';
  }).join('');

  el.innerHTML = '<div class="obs-depth-grid">' + cards + '</div>';
}

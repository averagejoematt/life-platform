/**
 * observatory-v3.js — Shared V3 observatory rendering module.
 * PB-09: Coach-led dashboard pattern.
 *
 * Named function exports (per Elena Reyes, Tech Board):
 *   renderStatusBar(container, metrics, data)
 *   renderCoachAnalysis(container, expertKey, coachMeta)
 *   renderTrends(container, chartConfigs, trendData)
 *   renderWeekDetail(container, detailCards, data)
 *   renderCrossDomain(container, links)
 *   renderDepth(container, sections, pageContent)
 *
 * Each page's HTML is a thin shell that defines a config object
 * and calls these functions after loading its API data.
 */

/* ── Helpers ───────────────────────────────────────────────── */

function _el(tag, cls, html) {
  var d = document.createElement(tag);
  if (cls) d.className = cls;
  if (html) d.innerHTML = html;
  return d;
}

function _deltaColor(val, inverted) {
  if (val == null || val === 0) return 'obs-delta-flat';
  var positive = inverted ? val < 0 : val > 0;
  return positive ? 'obs-delta-up' : 'obs-delta-down';
}

function _formatDelta(val, unit) {
  if (val == null) return '';
  var sign = val > 0 ? '+' : '';
  return sign + (typeof val === 'number' ? val.toFixed(1) : val) + (unit || '');
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

/* ── Section 1: Status Bar ─────────────────────────────────── */

/**
 * @param {string|HTMLElement} container — element ID or DOM node
 * @param {Array} metrics — [{key, label, unit, value, delta, deltaUnit, context, inverted}]
 * @param {Object} opts — {lastUpdated: ISO string}
 */
function renderStatusBar(container, metrics, opts) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el) return;
  opts = opts || {};

  var grid = _el('div', 'obs-status-grid');

  metrics.forEach(function(m) {
    var cell = _el('div', 'obs-status-cell');
    cell.innerHTML =
      '<div class="obs-status-cell__label">' + (m.label || '') + '</div>' +
      '<div class="obs-status-cell__value">' + (m.value != null ? m.value : '—') + (m.unit ? '<span style="font-size:14px;color:var(--text-muted);margin-left:4px">' + m.unit + '</span>' : '') + '</div>' +
      '<div class="obs-status-cell__delta ' + _deltaColor(m.delta, m.inverted) + '">' + _formatDelta(m.delta, m.deltaUnit || '') + '</div>' +
      '<div class="obs-status-cell__context">' + (m.context || '') + '</div>';
    grid.appendChild(cell);
  });

  el.innerHTML = '';
  el.className = 'obs-status';
  el.appendChild(grid);

  // Freshness indicator
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
      '</div>' +
    '</div>' +
    '<div class="obs-coach-prose" id="obs-coach-prose-' + expertKey + '"><div style="font-family:var(--font-mono);font-size:10px;color:var(--text-faint);letter-spacing:0.1em">LOADING ANALYSIS...</div></div>' +
    '<div class="obs-coach-action" id="obs-coach-action-' + expertKey + '" style="display:none"></div>' +
    '<div class="obs-coach-generated" id="obs-coach-gen-' + expertKey + '"></div>';

  // Fetch analysis
  fetch('/api/ai_analysis?expert=' + expertKey)
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      if (!data) return;
      var proseEl = document.getElementById('obs-coach-prose-' + expertKey);
      var actionEl = document.getElementById('obs-coach-action-' + expertKey);
      var genEl = document.getElementById('obs-coach-gen-' + expertKey);

      if (data.analysis) {
        // Split analysis into paragraphs
        var paragraphs = data.analysis.split('\n\n').filter(function(p) { return p.trim(); });
        proseEl.innerHTML = paragraphs.map(function(p) { return '<p>' + p + '</p>'; }).join('');
      } else {
        proseEl.innerHTML = '<p style="color:var(--text-faint)">Analysis generates weekly. Check back Monday.</p>';
      }

      if (data.key_recommendation) {
        actionEl.style.display = '';
        actionEl.innerHTML =
          '<div class="obs-coach-action__label">This week\'s action</div>' +
          '<div class="obs-coach-action__text">' + data.key_recommendation + '</div>';
      }

      if (data.generated_at) {
        var genDate = new Date(data.generated_at);
        genEl.textContent = 'Generated ' + genDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      }

      // Elena quote (after coach card)
      if (data.elena_quote) {
        var quoteDiv = _el('div', 'obs-elena-quote');
        quoteDiv.innerHTML =
          '"' + data.elena_quote + '"' +
          '<div class="obs-elena-quote__attr">Elena Voss · <a href="/chronicle/">Chronicle →</a></div>';
        el.appendChild(quoteDiv);
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

/* ── Section 3: Trends (container only — charts rendered by page) ── */

/**
 * @param {string|HTMLElement} container
 * @param {Object} opts — {title, chartIds: [id1, id2], labels: [label1, label2]}
 */
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

/**
 * @param {string|HTMLElement} container
 * @param {Array} cards — [{label, value, context, colorClass}]
 */
function renderWeekDetail(container, cards) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el || !cards || !cards.length) return;

  el.className = 'obs-detail';
  var grid = cards.map(function(c) {
    return '<div class="obs-detail-card">' +
      '<div class="obs-detail-card__label">' + (c.label || '') + '</div>' +
      '<div class="obs-detail-card__value"' + (c.colorClass ? ' class="' + c.colorClass + '"' : '') + '>' + (c.value != null ? c.value : '—') + '</div>' +
      '<div class="obs-detail-card__context">' + (c.context || '') + '</div>' +
    '</div>';
  }).join('');

  el.innerHTML =
    '<div class="obs-detail__title">This Week\'s Detail</div>' +
    '<div class="obs-detail-grid">' + grid + '</div>';
}

/* ── Section 5: Cross-Domain ───────────────────────────────── */

/**
 * @param {string|HTMLElement} container
 * @param {Array} links — [{title, finding, link}]
 */
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
 * @param {Array} sections — [{label, id, content}]
 */
function renderDepth(container, sections) {
  var el = typeof container === 'string' ? document.getElementById(container) : container;
  if (!el || !sections || !sections.length) return;

  el.className = 'obs-depth';
  var cards = sections.map(function(s) {
    return '<details class="obs-depth-section" id="depth-' + s.id + '">' +
      '<summary>' + s.label + '</summary>' +
      '<div class="obs-depth-section__body">' + (s.content || '<p>Content loading...</p>') + '</div>' +
    '</details>';
  }).join('');

  el.innerHTML =
    '<div class="obs-depth__title">Deep Dive</div>' +
    '<div class="obs-depth-grid">' + cards + '</div>';
}

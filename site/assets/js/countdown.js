/**
 * countdown.js — Global experiment countdown / Day N counter
 *
 * Before April 1, 2026: Shows "Experiment begins in X days"
 * After April 1, 2026:  Shows "Day N" of the experiment
 *
 * Injects into any element with class="experiment-counter"
 * Also exposes window.AMJ_EXPERIMENT for other scripts to consume.
 *
 * v1.0.0 — 2026-03-25
 */
(function() {
  'use strict';

  var EXPERIMENT_START = new Date('2026-04-01T00:00:00-07:00'); // PDT

  function daysBetween(a, b) {
    var msPerDay = 86400000;
    var utcA = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
    var utcB = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
    return Math.floor((utcB - utcA) / msPerDay);
  }

  var now = new Date();
  var daysSinceStart = daysBetween(EXPERIMENT_START, now);
  var isLive = daysSinceStart >= 0;
  var dayNumber = isLive ? daysSinceStart + 1 : 0; // Day 1 on April 1
  var daysUntil = isLive ? 0 : Math.abs(daysSinceStart);

  // Expose globally for other scripts
  window.AMJ_EXPERIMENT = {
    start: EXPERIMENT_START,
    isLive: isLive,
    dayNumber: dayNumber,
    daysUntil: daysUntil,
    phase: isLive ? 'live' : 'countdown'
  };

  // Inject into all counter elements
  var counters = document.querySelectorAll('.experiment-counter');
  counters.forEach(function(el) {
    var format = el.getAttribute('data-format') || 'full';

    if (isLive) {
      if (format === 'number') {
        el.textContent = dayNumber;
      } else if (format === 'short') {
        el.textContent = 'Day ' + dayNumber;
      } else {
        el.innerHTML = '<span class="counter-label">Day</span><span class="counter-value">' + dayNumber + '</span>';
      }
      el.classList.add('experiment-live');
    } else {
      if (format === 'number') {
        el.textContent = daysUntil;
      } else if (format === 'short') {
        el.textContent = daysUntil + ' day' + (daysUntil === 1 ? '' : 's') + ' to launch';
      } else {
        el.innerHTML = '<span class="counter-label">Experiment begins in</span><span class="counter-value">' + daysUntil + '</span><span class="counter-unit">day' + (daysUntil === 1 ? '' : 's') + '</span>';
      }
      el.classList.add('experiment-countdown');
    }
  });

  // Inject persistent "Day N" badge into top nav if it exists (once only)
  var nav = document.querySelector('.nav__links');
  if (nav && !document.querySelector('.nav-day-badge')) {
    var badge = document.createElement('span');
    badge.className = 'nav-day-badge';
    if (isLive) {
      badge.textContent = 'DAY ' + dayNumber;
      badge.title = 'Day ' + dayNumber + ' of the experiment';
    } else {
      badge.textContent = 'T-' + daysUntil;
      badge.title = daysUntil + ' days until launch';
    }
    nav.insertBefore(badge, nav.firstChild);
  }

})();

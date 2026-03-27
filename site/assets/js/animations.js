/*
  animations.js — Shared animation utilities for averagejoematt.com
  Design Brief DB-11/DB-12: Card hover lifts, staggered reveals, count-up
  Added: 2026-03-26

  Usage: <script src="/assets/js/animations.js" defer></script>
  No dependencies. Vanilla JS. Respects prefers-reduced-motion.
*/
(function() {
  'use strict';

  var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Scroll-triggered reveals ──────────────────────────── */
  function initReveals() {
    var targets = document.querySelectorAll('.reveal, .reveal-grid > *');
    if (!targets.length) return;

    if (prefersReduced) {
      targets.forEach(function(el) {
        el.classList.add('is-visible');
      });
      return;
    }

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    targets.forEach(function(el) { observer.observe(el); });
  }

  /* ── Number count-up ───────────────────────────────────── */
  function initCountUp() {
    var targets = document.querySelectorAll('[data-count-up]');
    if (!targets.length) return;

    if (prefersReduced) {
      targets.forEach(function(el) {
        el.textContent = el.getAttribute('data-count-up');
      });
      return;
    }

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          animateCount(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.3 });

    targets.forEach(function(el) { observer.observe(el); });
  }

  function animateCount(el) {
    var target = parseFloat(el.getAttribute('data-count-up'));
    var suffix = el.getAttribute('data-count-suffix') || '';
    var prefix = el.getAttribute('data-count-prefix') || '';
    var decimals = (target % 1 !== 0) ? 1 : 0;
    var duration = 800;
    var start = performance.now();

    function step(now) {
      var elapsed = now - start;
      var progress = Math.min(elapsed / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = target * eased;
      el.textContent = prefix + current.toFixed(decimals) + suffix;
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  }

  /* ── Signal bar fill animation ─────────────────────────── */
  function initSignalBars() {
    var fills = document.querySelectorAll('.signal-bar__fill[data-fill]');
    if (!fills.length) return;

    if (prefersReduced) {
      fills.forEach(function(el) {
        el.style.transform = 'scaleX(' + (parseFloat(el.getAttribute('data-fill')) / 100) + ')';
      });
      return;
    }

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          var pct = parseFloat(entry.target.getAttribute('data-fill')) / 100;
          entry.target.style.transform = 'scaleX(' + pct + ')';
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.2 });

    fills.forEach(function(el) {
      el.style.transform = 'scaleX(0)';
      observer.observe(el);
    });
  }

  /* ── Back to top visibility ────────────────────────────── */
  function initBackToTop() {
    var btn = document.querySelector('.back-to-top');
    if (!btn) return;

    var scrollThreshold = 400;
    var ticking = false;

    window.addEventListener('scroll', function() {
      if (!ticking) {
        requestAnimationFrame(function() {
          if (window.scrollY > scrollThreshold) {
            btn.classList.add('is-visible');
          } else {
            btn.classList.remove('is-visible');
          }
          ticking = false;
        });
        ticking = true;
      }
    });

    btn.addEventListener('click', function() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ── Init on DOM ready ─────────────────────────────────── */
  function init() {
    initReveals();
    initCountUp();
    initSignalBars();
    initBackToTop();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

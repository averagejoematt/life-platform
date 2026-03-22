/**
 * nav.js — Shared navigation component for averagejoematt.com
 * Handles: hamburger menu, bottom nav active state, theme toggle,
 *          GAM-01 "Since Your Last Visit" badges, GAM-02 Reading Path CTAs
 * v1.2.0 — 2026-03-21 — Phase 1 IA: 5-section nav, /chronicle/
 */
(function() {
  'use strict';

  // ── Hamburger toggle ──────────────────────────────────────
  var hamburger = document.querySelector('.nav__hamburger');
  var overlay = document.querySelector('.nav-overlay');
  var overlayClose = document.querySelector('.nav-overlay__close');
  var body = document.body;

  function openMenu() {
    if (overlay) {
      overlay.style.display = 'flex'; // show before opacity transition
      requestAnimationFrame(function() {
        overlay.classList.add('is-open');
      });
      body.style.overflow = 'hidden';
    }
  }
  function closeMenu() {
    if (overlay) {
      overlay.classList.remove('is-open');
      body.style.overflow = '';
      // Hide after opacity transition completes (250ms matches CSS transition)
      setTimeout(function() {
        if (!overlay.classList.contains('is-open')) {
          overlay.style.display = '';
        }
      }, 260);
    }
  }

  if (hamburger) hamburger.addEventListener('click', openMenu);
  if (overlayClose) overlayClose.addEventListener('click', closeMenu);
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeMenu();
    });
  }

  // ── Bottom nav active state ───────────────────────────────
  var path = window.location.pathname;
  var bottomLinks = document.querySelectorAll('.bottom-nav__link');
  bottomLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if (href === '/' && path === '/') {
      link.classList.add('active');
    } else if (href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    }
  });

  // ── Top nav active state ──────────────────────────────────
  var navLinks = document.querySelectorAll('.nav__link:not(.nav__cta)');
  navLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if (href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    }
  });

  // ── Overlay nav active state ──────────────────────────────
  var overlayLinks = document.querySelectorAll('.nav-overlay__link');
  overlayLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if ((href === '/' && path === '/') || (href !== '/' && path.startsWith(href))) {
      link.classList.add('active');
    }
  });

  // ── Desktop dropdown click support ────────────────────────
  // Hover handles desktop; click handles keyboard nav + touch fallback
  var dropdowns = document.querySelectorAll('.nav__dropdown');
  dropdowns.forEach(function(dd) {
    var btn = dd.querySelector('.nav__dropdown-btn');
    if (!btn) return;
    btn.addEventListener('click', function(e) {
      var isOpen = dd.classList.contains('is-open');
      // Close all dropdowns first
      dropdowns.forEach(function(d) { d.classList.remove('is-open'); });
      if (!isOpen) dd.classList.add('is-open');
      e.stopPropagation();
    });
  });
  // Close dropdowns when clicking outside
  document.addEventListener('click', function() {
    dropdowns.forEach(function(d) { d.classList.remove('is-open'); });
  });

  // ── Theme toggle ──────────────────────────────────────────
  var themeToggle = document.querySelector('.theme-toggle');
  if (themeToggle) {
    var saved = localStorage.getItem('amj-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);

    themeToggle.addEventListener('click', function() {
      var current = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('amj-theme', next);
    });
  }

  // ── Keyboard: Escape closes overlay ───────────────────────
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeMenu();
  });

  // ── Back to top button (U07) ───────────────────────────────
  var btt = document.createElement('button');
  btt.className = 'back-to-top';
  btt.setAttribute('aria-label', 'Back to top');
  btt.textContent = '↑';
  btt.addEventListener('click', function() { window.scrollTo({ top: 0, behavior: 'smooth' }); });
  document.body.appendChild(btt);
  window.addEventListener('scroll', function() {
    if (window.scrollY > 400) btt.classList.add('is-visible');
    else btt.classList.remove('is-visible');
  }, { passive: true });

  // ── Nav date ─────────────────────────────────────────────
  var navDate = document.getElementById('nav-date');
  if (navDate) {
    var d = new Date();
    navDate.textContent = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // ── GAM-01: Since Your Last Visit badges ─────────────────
  // Maps section root paths to their last-updated deploy date.
  // Update these dates when content in that section changes.
  var SECTION_LAST_UPDATED = {
    '/chronicle/':         '2026-03-21',
    '/chronicle/archive/': '2026-03-21',
    '/week/':              '2026-03-21',
    '/live/':              '2026-03-21',
    '/character/':         '2026-03-21',
    '/habits/':            '2026-03-21',
    '/discoveries/':       '2026-03-21',
    '/sleep/':             '2026-03-21',
    '/glucose/':           '2026-03-21',
  };

  // Bottom nav item → which section paths it represents
  var BADGE_MAP = {
    '/chronicle/': ['/chronicle/', '/chronicle/archive/', '/week/'],
    '/character/': ['/character/'],
    '/live/': ['/live/', '/habits/', '/discoveries/'],
  };

  try {
    var lastVisitKey = 'amj_last_visit';
    var lastVisit = localStorage.getItem(lastVisitKey);
    var nowIso = new Date().toISOString();

    if (lastVisit) {
      var lastVisitDate = new Date(lastVisit);

      Object.keys(BADGE_MAP).forEach(function(navHref) {
        var trackedPaths = BADGE_MAP[navHref];
        var hasNew = trackedPaths.some(function(p) {
          var updated = SECTION_LAST_UPDATED[p];
          return updated && new Date(updated) > lastVisitDate;
        });
        if (hasNew) {
          var navEl = document.querySelector('.bottom-nav__link[href="' + navHref + '"]');
          if (navEl) navEl.classList.add('has-badge');
        }
      });

      // Clear badge for the current section (user is looking at it)
      Object.keys(BADGE_MAP).forEach(function(navHref) {
        if (path.startsWith(navHref)) {
          var navEl = document.querySelector('.bottom-nav__link[href="' + navHref + '"]');
          if (navEl) navEl.classList.remove('has-badge');
        }
      });
    }

    // Always update last_visit after badge logic runs
    localStorage.setItem(lastVisitKey, nowIso);
  } catch (e) { /* localStorage blocked — degrade silently */ }

  // ── GAM-02: Reading Path CTAs ─────────────────────────────
  // Maps current page path → next recommended read.
  var READING_PATHS = {
    '/story/':              { href: '/live/',            title: 'See Today\'s Data →',      sub: 'What the sensors say right now' },
    '/about/':              { href: '/story/',           title: 'The Story →',              sub: 'Read the full transformation narrative' },
    '/live/':               { href: '/character/',       title: 'The Score →',              sub: 'How it all adds up' },
    '/character/':          { href: '/habits/',          title: 'The Habits →',             sub: 'The inputs that drive the score' },
    '/habits/':             { href: '/experiments/',     title: 'Experiments →',            sub: 'What\'s being actively tested' },
    '/accountability/':     { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the science works' },
    '/protocols/':          { href: '/live/',            title: 'The Results →',            sub: 'What these protocols produced' },
    '/experiments/':        { href: '/discoveries/',     title: 'Discoveries →',            sub: 'What the data proved' },
    '/discoveries/':        { href: '/intelligence/',    title: 'The Intelligence Layer →', sub: 'How the AI finds these patterns' },
    '/sleep/':              { href: '/glucose/',         title: 'Glucose Data →',           sub: '30-day CGM time-in-range' },
    '/glucose/':            { href: '/benchmarks/',      title: 'Benchmarks →',             sub: 'How Matthew compares to population norms' },
    '/benchmarks/':         { href: '/subscribe/',       title: 'Get Weekly Updates →',     sub: 'New data every week' },
    '/supplements/':        { href: '/protocols/',       title: 'All Protocols →',          sub: 'Sleep, training, nutrition, supplements' },
    '/platform/':           { href: '/cost/',            title: 'The Real Cost →',          sub: 'Running a full health OS for ~$13/month' },
    '/cost/':               { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the science works' },
    '/methodology/':        { href: '/intelligence/',    title: 'The Intelligence Layer →', sub: 'What the AI actually does' },
    '/intelligence/':       { href: '/discoveries/',     title: 'Discoveries →',            sub: 'What the data revealed' },
    '/board/':              { href: '/platform/',        title: 'How This Works →',         sub: 'The full platform architecture' },
    '/data/':               { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the data is processed' },
    '/tools/':              { href: '/ask/',             title: 'Ask the Data →',           sub: 'Query 19 sources of live data' },
    '/week/':               { href: '/subscribe/',       title: 'Get This Weekly →',        sub: 'Every week, in your inbox' },
    '/chronicle/':          { href: '/chronicle/archive/', title: 'All Entries →',          sub: 'The full chronicle archive' },
    '/chronicle/archive/':  { href: '/subscribe/',       title: 'Get the Weekly Brief →',   sub: 'Delivered every week' },
    '/ask/':                { href: '/platform/',        title: 'How This Works →',         sub: 'The platform behind the AI' },
  };

  var nextRead = READING_PATHS[path];
  if (nextRead) {
    var footer = document.querySelector('.footer-v2');
    if (footer) {
      var rp = document.createElement('div');
      rp.className = 'reading-path';

      var label = document.createElement('span');
      label.className = 'reading-path__label';
      label.textContent = 'Read Next';

      var link = document.createElement('a');
      link.className = 'reading-path__link';
      link.setAttribute('href', nextRead.href);

      var titleEl = document.createElement('span');
      titleEl.className = 'reading-path__title';
      titleEl.textContent = nextRead.title;

      var subEl = document.createElement('span');
      subEl.className = 'reading-path__sub';
      subEl.textContent = nextRead.sub;

      link.appendChild(titleEl);
      link.appendChild(subEl);
      rp.appendChild(label);
      rp.appendChild(link);
      footer.parentNode.insertBefore(rp, footer);
    }
  }

})();

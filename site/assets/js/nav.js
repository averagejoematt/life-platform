/**
 * nav.js — Shared navigation component for averagejoematt.com
 * Handles: hamburger menu, bottom nav active state, theme toggle,
 *          GAM-01 "Since Your Last Visit" badges, GAM-02 Reading Path CTAs
 * v2.0.0 — 2026-03-26 — Tier 2 IA: 5-section nav
 */
(function() {
  'use strict';

  // ── Hamburger toggle ──────────────────────────────────────
  var hamburger = document.querySelector('.nav__hamburger');
  var overlay = document.querySelector('.nav-overlay');
  var overlayClose = document.querySelector('.nav-overlay__close');
  var body = document.body;

  var savedScrollY = 0;

  function openMenu() {
    if (overlay) {
      savedScrollY = window.scrollY;
      overlay.style.display = 'flex';
      requestAnimationFrame(function() {
        overlay.classList.add('is-open');
      });
      body.style.overflow = 'hidden';
      body.style.position = 'fixed';
      body.style.top = '-' + savedScrollY + 'px';
      body.style.left = '0';
      body.style.right = '0';
    }
  }
  function closeMenu() {
    if (overlay) {
      overlay.classList.remove('is-open');
      body.style.overflow = '';
      body.style.position = '';
      body.style.top = '';
      body.style.left = '';
      body.style.right = '';
      window.scrollTo(0, savedScrollY);
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
  var dropdowns = document.querySelectorAll('.nav__dropdown');
  dropdowns.forEach(function(dd) {
    var btn = dd.querySelector('.nav__dropdown-btn');
    if (!btn) return;
    btn.addEventListener('click', function(e) {
      var isOpen = dd.classList.contains('is-open');
      dropdowns.forEach(function(d) { d.classList.remove('is-open'); });
      if (!isOpen) dd.classList.add('is-open');
      e.stopPropagation();
    });
  });
  document.addEventListener('click', function() {
    dropdowns.forEach(function(d) { d.classList.remove('is-open'); });
  });

  // ── Theme toggle (handled by components.js — removed duplicate from nav.js in v3.9.41) ──

  // ── Keyboard: Escape closes overlay ───────────────────────
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeMenu();
  });

  // ── Back to top button ────────────────────────────────────
  var btt = document.createElement('button');
  btt.className = 'back-to-top';
  btt.setAttribute('aria-label', 'Back to top');
  btt.textContent = '\u2191';
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
  var SECTION_LAST_UPDATED = {
    '/chronicle/':         '2026-03-26',
    '/chronicle/archive/': '2026-03-26',
    '/week/':              '2026-03-26',
    '/live/':              '2026-03-26',
    '/character/':         '2026-03-26',
    '/habits/':            '2026-03-26',
    '/discoveries/':       '2026-03-26',
    '/sleep/':             '2026-03-26',
    '/glucose/':           '2026-03-26',
    '/stack/':             '2026-03-26',
    '/platform/':          '2026-03-26',
  };

  // Bottom nav → which paths it owns (5-section IA)
  var BADGE_MAP = {
    '/':           ['/story/', '/about/'],
    '/live/':      ['/live/', '/character/', '/habits/', '/sleep/', '/glucose/', '/explorer/'],
    '/stack/':     ['/stack/', '/protocols/', '/experiments/', '/discoveries/', '/challenges/'],
    '/platform/':  ['/platform/', '/intelligence/', '/board/', '/tools/'],
    '/subscribe/': ['/chronicle/', '/chronicle/archive/', '/weekly/', '/subscribe/'],
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

      Object.keys(BADGE_MAP).forEach(function(navHref) {
        if (path.startsWith(navHref) && navHref !== '/') {
          var navEl = document.querySelector('.bottom-nav__link[href="' + navHref + '"]');
          if (navEl) navEl.classList.remove('has-badge');
        }
      });
    }

    localStorage.setItem(lastVisitKey, nowIso);
  } catch (e) { /* localStorage blocked */ }

  // ── GAM-02: Reading Path CTAs ─────────────────────────────
  var READING_PATHS = {
    '/story/':              { href: '/live/',            title: 'See Today\u2019s Data \u2192',      sub: 'What the sensors say right now' },
    '/about/':              { href: '/story/',           title: 'The Story \u2192',              sub: 'Read the full transformation narrative' },
    '/live/':               { href: '/character/',       title: 'The Score \u2192',              sub: 'How it all adds up' },
    '/character/':          { href: '/habits/',          title: 'The Habits \u2192',             sub: 'The inputs that drive the score' },
    '/habits/':             { href: '/experiments/',     title: 'Experiments \u2192',            sub: 'What\u2019s being actively tested' },
    '/accountability/':     { href: '/methodology/',     title: 'The Methodology \u2192',        sub: 'How the science works' },
    '/protocols/':          { href: '/live/',            title: 'The Results \u2192',            sub: 'What these protocols produced' },
    '/experiments/':        { href: '/discoveries/',     title: 'Discoveries \u2192',            sub: 'What the data proved' },
    '/discoveries/':        { href: '/intelligence/',    title: 'The Intelligence Layer \u2192', sub: 'How the AI finds these patterns' },
    '/sleep/':              { href: '/glucose/',         title: 'Glucose Data \u2192',           sub: '30-day CGM time-in-range' },
    '/glucose/':            { href: '/benchmarks/',      title: 'Benchmarks \u2192',             sub: 'How Matthew compares to population norms' },
    '/benchmarks/':         { href: '/subscribe/',       title: 'Get Weekly Updates \u2192',     sub: 'New data every week' },
    '/supplements/':        { href: '/protocols/',       title: 'All Protocols \u2192',          sub: 'Sleep, training, nutrition, supplements' },
    '/platform/':           { href: '/cost/',            title: 'The Real Cost \u2192',          sub: 'Running a full health OS for ~$13/month' },
    '/cost/':               { href: '/methodology/',     title: 'The Methodology \u2192',        sub: 'How the science works' },
    '/methodology/':        { href: '/intelligence/',    title: 'The Intelligence Layer \u2192', sub: 'What the AI actually does' },
    '/intelligence/':       { href: '/discoveries/',     title: 'Discoveries \u2192',            sub: 'What the data revealed' },
    '/board/':              { href: '/board/technical/', title: 'Technical Board \u2192',        sub: '12 personas keeping the architecture honest' },
    '/board/technical/':    { href: '/board/product/',   title: 'Product Board \u2192',          sub: '8 personas shaping what this site becomes' },
    '/board/product/':      { href: '/platform/',        title: 'How This Works \u2192',         sub: 'The full platform architecture' },
    '/data/':               { href: '/methodology/',     title: 'The Methodology \u2192',        sub: 'How the data is processed' },
    '/tools/':              { href: '/ask/',             title: 'Ask the Data \u2192',           sub: 'Query 19 sources of live data' },
    '/week/':               { href: '/subscribe/',       title: 'Get This Weekly \u2192',        sub: 'Every week, in your inbox' },
    '/chronicle/':          { href: '/chronicle/archive/', title: 'All Entries \u2192',          sub: 'The full chronicle archive' },
    '/chronicle/archive/':  { href: '/subscribe/',       title: 'Get the Weekly Brief \u2192',   sub: 'Delivered every week' },
    '/ask/':                { href: '/platform/',        title: 'How This Works \u2192',         sub: 'The platform behind the AI' },
    '/explorer/':           { href: '/discoveries/',     title: 'Validated Discoveries \u2192',  sub: 'Correlations that survived scrutiny' },
    '/weekly/':             { href: '/explorer/',        title: 'Explore the Data \u2192',       sub: 'Pick any two metrics and discover correlations' },
    '/achievements/':       { href: '/character/',       title: 'The Character Sheet \u2192',    sub: 'How it all adds up into one score' },
    '/stack/':              { href: '/protocols/',       title: 'Protocols \u2192',              sub: 'The strategy layer beneath the stack' },
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

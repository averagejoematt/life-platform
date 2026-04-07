/**
 * nav.js — Shared navigation component for averagejoematt.com
 * Handles: hamburger menu, bottom nav active state, theme toggle,
 *          GAM-01 "Since Your Last Visit" badges, GAM-02 Reading Path CTAs
 * v3.0.0 — 2026-03-27 — Decision 1: 6-section IA
 */
(function() {
  'use strict';

  // ── Hamburger toggle ──────────────────────────────────────
  var hamburger = document.querySelector('.nav__hamburger');
  var overlay = document.querySelector('.nav-overlay');
  var overlayClose = document.querySelector('.nav-overlay__close');
  var body = document.body;
  var html = document.documentElement;

  var savedScrollY = 0;

  // iOS Safari scroll-lock: prevent touchmove on anything outside the overlay
  function blockBackgroundTouch(e) {
    if (!overlay.contains(e.target)) {
      e.preventDefault();
    }
  }

  function openMenu() {
    if (overlay) {
      savedScrollY = window.scrollY;
      overlay.style.display = 'flex';
      requestAnimationFrame(function() {
        overlay.classList.add('is-open');
      });
      body.style.overflow = 'hidden';
      body.style.position = 'fixed';
      body.style.width = '100%';
      body.style.top = '-' + savedScrollY + 'px';
      body.style.left = '0';
      body.style.right = '0';
      body.style.touchAction = 'none';
      body.style.overscrollBehavior = 'none';
      html.style.overflow = 'hidden';
      html.style.touchAction = 'none';
      html.style.overscrollBehavior = 'none';
      document.addEventListener('touchmove', blockBackgroundTouch, { passive: false });
    }
  }
  function closeMenu() {
    if (overlay) {
      overlay.classList.remove('is-open');
      body.style.overflow = '';
      body.style.position = '';
      body.style.width = '';
      body.style.top = '';
      body.style.left = '';
      body.style.right = '';
      body.style.touchAction = '';
      body.style.overscrollBehavior = '';
      html.style.overflow = '';
      html.style.touchAction = '';
      html.style.overscrollBehavior = '';
      document.removeEventListener('touchmove', blockBackgroundTouch);
      window.scrollTo(0, savedScrollY);
      setTimeout(function() {
        if (!overlay.classList.contains('is-open')) {
          overlay.style.display = '';
        }
      }, 260);
    }
  }

  if (hamburger) hamburger.addEventListener('click', openMenu);
  // "More" bottom-nav button also opens the overlay (Decision 1b)
  var moreBtn = document.querySelector('.bottom-nav__more');
  if (moreBtn) {
    moreBtn.addEventListener('click', openMenu);
  } else {
    // Defensive: bottom nav may render after nav.js on slower devices
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('.bottom-nav__more');
      if (btn) openMenu();
    });
  }
  if (overlayClose) overlayClose.addEventListener('click', closeMenu);
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeMenu();
    });
  }

  // ── Bottom nav active state (6-section IA) ───────────────
  var path = window.location.pathname;
  // Map bottom nav hrefs to the full set of paths each owns
  var BOTTOM_NAV_OWNS = {
    '/':           ['/', '/story/', '/about/', '/achievements/'],
    '/sleep/':     ['/sleep/', '/glucose/', '/nutrition/', '/training/', '/physical/', '/mind/', '/benchmarks/', '/explorer/'],
    '/live/':      ['/live/', '/character/', '/habits/', '/accountability/'],
    '/chronicle/': ['/chronicle/', '/weekly/', '/ask/', '/subscribe/'],
  };
  var bottomLinks = document.querySelectorAll('.bottom-nav__link:not(.bottom-nav__more)');
  bottomLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    var owned = BOTTOM_NAV_OWNS[href] || [];
    var isActive = owned.some(function(p) {
      return (p === '/' && path === '/') || (p !== '/' && path.startsWith(p));
    });
    if (isActive) link.classList.add('active');
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

  // ── GAM-01 / DPR-1.20: Since Your Last Visit badges (per-page tracking) ──
  // Bottom nav → which paths it owns (6-section IA, Decision 1c)
  var BADGE_MAP = {
    '/':           ['/story/', '/about/', '/achievements/', '/first-person/'],
    '/sleep/':     ['/sleep/', '/glucose/', '/nutrition/', '/training/', '/physical/', '/mind/', '/benchmarks/', '/explorer/'],
    '/stack/':     ['/stack/', '/protocols/', '/supplements/', '/experiments/', '/challenges/', '/discoveries/'],
    '/live/':      ['/live/', '/character/', '/habits/', '/accountability/'],
    '/chronicle/': ['/chronicle/', '/chronicle/archive/', '/weekly/', '/ask/', '/subscribe/'],
  };

  try {
    var VISIT_KEY = 'amj_last_visits';
    var lastVisits = JSON.parse(localStorage.getItem(VISIT_KEY) || '{}');
    var currentPage = path.replace(/\/+$/, '') || '/';

    // Fetch page freshness from API (non-blocking)
    fetch('/api/vitals').then(function(r) { return r.ok ? r.json() : null; }).then(function(data) {
      if (!data) return;
      var freshness = data.page_freshness || {};
      Object.keys(BADGE_MAP).forEach(function(navHref) {
        var trackedPaths = BADGE_MAP[navHref];
        var hasNew = trackedPaths.some(function(p) {
          var pageKey = p.replace(/\/+$/, '') || '/';
          var updated = freshness[pageKey] || freshness[p];
          var lastSeen = lastVisits[pageKey] || '1970-01-01';
          return updated && updated > lastSeen;
        });
        if (hasNew) {
          var navEl = document.querySelector('.bottom-nav__link[href="' + navHref + '"]');
          if (navEl) navEl.classList.add('has-badge');
        }
      });
      // Clear badge for current section
      Object.keys(BADGE_MAP).forEach(function(navHref) {
        if (path.startsWith(navHref) && navHref !== '/') {
          var navEl = document.querySelector('.bottom-nav__link[href="' + navHref + '"]');
          if (navEl) navEl.classList.remove('has-badge');
        }
      });
    }).catch(function() {});

    // Record visit for current page
    lastVisits[currentPage] = new Date().toISOString();
    localStorage.setItem(VISIT_KEY, JSON.stringify(lastVisits));
  } catch (e) { /* localStorage blocked */ }

  // ── GAM-02: Reading Path CTAs (Decision 1d — 6-section IA) ─
  var READING_PATHS = {
    // The Story flow
    '/story/':              { href: '/live/',             title: 'See Today\u2019s Data \u2192',      sub: 'What the sensors say right now' },
    '/about/':              { href: '/story/',            title: 'The Story \u2192',              sub: 'Read the full transformation narrative' },
    '/achievements/':       { href: '/character/',        title: 'The Score \u2192',              sub: 'How it all adds up into one score' },
    // The Evidence flow
    '/sleep/':              { href: '/glucose/',          title: 'Glucose Data \u2192',           sub: '30-day CGM time-in-range' },
    '/glucose/':            { href: '/nutrition/',        title: 'Nutrition Data \u2192',          sub: 'Macro tracking, protein targets, TDEE' },
    '/nutrition/':          { href: '/training/',         title: 'Training Data \u2192',           sub: 'Workouts, zone 2, strength progress' },
    '/training/':           { href: '/physical/',          title: 'Physical Data \u2192',           sub: 'Weight trajectory and body composition' },
    '/physical/':           { href: '/mind/',             title: 'Inner Life \u2192',             sub: 'The pillar that determines all the others' },
    '/mind/':               { href: '/benchmarks/',       title: 'The Standards \u2192',           sub: 'How Matthew compares to population norms' },
    '/benchmarks/':         { href: '/explorer/',         title: 'Explore the Data \u2192',        sub: 'Cross-domain correlations and patterns' },
    '/explorer/':           { href: '/discoveries/',      title: 'Validated Discoveries \u2192',   sub: 'Correlations that survived scrutiny' },
    // The Pulse flow
    '/live/':               { href: '/character/',        title: 'The Score \u2192',              sub: 'How it all adds up' },
    '/character/':          { href: '/habits/',           title: 'The Habits \u2192',             sub: 'The inputs that drive the score' },
    '/habits/':             { href: '/accountability/',   title: 'Accountability \u2192',          sub: 'The public commitment' },
    '/accountability/':     { href: '/sleep/',            title: 'The Evidence \u2192',            sub: 'Start with sleep data' },
    // The Practice flow
    '/stack/':              { href: '/protocols/',        title: 'Protocols \u2192',              sub: 'The strategy layer beneath the stack' },
    '/protocols/':          { href: '/experiments/',      title: 'Experiments \u2192',            sub: 'What\u2019s being actively tested' },
    '/supplements/':        { href: '/protocols/',        title: 'All Protocols \u2192',          sub: 'Sleep, training, nutrition, supplements' },
    '/experiments/':        { href: '/challenges/',       title: 'Challenges \u2192',             sub: 'Action-oriented goals from the data' },
    '/challenges/':         { href: '/discoveries/',      title: 'Discoveries \u2192',            sub: 'What the data proved' },
    '/discoveries/':        { href: '/intelligence/',     title: 'The Intelligence Layer \u2192',  sub: 'How the AI finds these patterns' },
    // The Platform flow
    '/platform/':           { href: '/intelligence/',     title: 'The AI \u2192',                 sub: 'What the intelligence layer actually does' },
    '/intelligence/':       { href: '/board/',            title: 'AI Board \u2192',               sub: 'The advisory personas shaping this platform' },
    '/board/':              { href: '/board/technical/',  title: 'Technical Board \u2192',        sub: '12 personas keeping the architecture honest' },
    '/board/technical/':    { href: '/board/product/',    title: 'Product Board \u2192',          sub: '8 personas shaping what this site becomes' },
    '/board/product/':      { href: '/methodology/',      title: 'Methodology \u2192',            sub: 'How the science works' },
    '/methodology/':        { href: '/cost/',             title: 'The Real Cost \u2192',          sub: 'Running a full health OS for $19/month' },
    '/cost/':               { href: '/tools/',            title: 'Tools \u2192',                  sub: 'Every tool in the platform' },
    '/tools/':              { href: '/builders/',         title: 'For Builders \u2192',           sub: 'Build your own health platform' },
    '/builders/':           { href: '/subscribe/',        title: 'Subscribe \u2192',              sub: 'Follow the experiment' },
    // The Chronicle flow
    '/chronicle/':          { href: '/chronicle/archive/', title: 'All Entries \u2192',           sub: 'The full chronicle archive' },
    '/chronicle/archive/':  { href: '/subscribe/',        title: 'Get the Weekly Brief \u2192',   sub: 'Delivered every week' },
    '/weekly/':             { href: '/ask/',              title: 'Ask the Data \u2192',           sub: 'Query 26 sources of live data' },
    '/ask/':                { href: '/subscribe/',        title: 'Subscribe \u2192',              sub: 'Follow the experiment' },
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

/**
 * components.js — Shared structural components for averagejoematt.com
 *
 * Injects: nav, mobile overlay, footer, bottom-nav, subscribe CTA
 * into placeholder elements on each page.
 *
 * USAGE: Pages include a thin shell:
 *   <div id="amj-nav"></div>
 *   ... page content ...
 *   <div id="amj-subscribe"></div>   (optional)
 *   <div id="amj-bottom-nav"></div>
 *   <div id="amj-footer"></div>
 *   <script src="/assets/js/site_constants.js"></script>
 *   <script src="/assets/js/components.js"></script>
 *   <script src="/assets/js/nav.js"></script>
 *
 * WHY: Editing nav/footer/CTA structure requires changing 1 file instead of 54.
 *
 * v4.0.0 — 2026-03-27 — Offsite Decision 1: 6-section IA
 *   The Story | The Evidence | The Pulse | The Practice | The Platform | The Chronicle
 */
(function() {
  'use strict';

  var path = window.location.pathname;

  // ── Section mapping — 6-section IA (Decision 1a) ──────────
  var SECTIONS = [
    { label: 'The Story', items: [
      { href: '/',               text: 'Home' },
      { href: '/story/',         text: 'My Story' },
      { href: '/about/',         text: 'The Mission' },
      { href: '/achievements/',  text: 'Milestones' },
      { href: '/first-person/',  text: 'First Person' },
    ]},
    { label: 'The Evidence', items: [
      { href: '/sleep/',       text: 'Sleep' },
      { href: '/glucose/',     text: 'Glucose' },
      { href: '/nutrition/',   text: 'Nutrition' },
      { href: '/training/',    text: 'Training' },
      { href: '/mind/',        text: 'Inner Life' },
      { href: '/labs/',        text: 'Labs' },
      { href: '/benchmarks/',  text: 'Benchmarks' },
      { href: '/explorer/',    text: 'Data Explorer' },
    ]},
    { label: 'The Pulse', items: [
      { href: '/live/',           text: 'Today' },
      { href: '/character/',      text: 'The Score' },
      { href: '/habits/',         text: 'Habits' },
      { href: '/accountability/', text: 'Accountability' },
    ]},
    { label: 'The Practice', groups: [
      { heading: 'The System', items: [
        { href: '/stack/',       text: 'The Stack' },
        { href: '/protocols/',   text: 'Protocols' },
        { href: '/supplements/', text: 'Supplements' },
      ]},
      { heading: 'The Pipeline', items: [
        { href: '/experiments/', text: 'Experiments' },
        { href: '/challenges/',  text: 'Challenges' },
        { href: '/discoveries/', text: 'Discoveries' },
      ]},
    ]},
    { label: 'The Platform', items: [
      { href: '/platform/',     text: 'How It Works' },
      { href: '/intelligence/', text: 'The AI' },
      { href: '/board/',        text: 'AI Board' },
      { href: '/methodology/',  text: 'Methodology' },
      { href: '/cost/',         text: 'Cost' },
      { href: '/tools/',        text: 'Tools' },
      { href: '/builders/',     text: 'For Builders' },
    ]},
    { label: 'The Chronicle', items: [
      { href: '/chronicle/', text: 'Chronicle Archive' },
      { href: '/weekly/',    text: 'Weekly Snapshots' },
      { href: '/recap/',     text: 'Weekly Recap' },
      { href: '/ask/',       text: 'Ask the Data' },
      { href: '/subscribe/', text: 'Subscribe' },
    ]},
  ];

  // ── Helper: get all link items from a section (flat or grouped) ──
  function getSectionItems(sec) {
    if (sec.items) return sec.items;
    if (sec.groups) {
      var all = [];
      sec.groups.forEach(function(g) { all = all.concat(g.items); });
      return all;
    }
    return [];
  }

  function sectionOwnsPath(section, p) {
    if (section.label === 'The Story' && p === '/') return true;
    return getSectionItems(section).some(function(item) {
      return p === item.href || (item.href !== '/' && p.startsWith(item.href));
    });
  }

  function isItemActive(href, p) {
    return (p === href || (href !== '/' && p.startsWith(href)));
  }

  // ── NAV ────────────────────────────────────────────────────
  function buildNav() {
    var html = '<nav class="nav">';
    html += '<a href="/" class="nav__brand">AJM</a>';
    html += '<div class="nav__links">';

    SECTIONS.forEach(function(sec) {
      var isActive = sectionOwnsPath(sec, path) ? ' is-active' : '';
      html += '<div class="nav__dropdown' + isActive + '">';
      html += '<button class="nav__dropdown-btn">' + sec.label + '</button>';
      html += '<div class="nav__dropdown-menu">';

      if (sec.groups) {
        sec.groups.forEach(function(group, gi) {
          if (gi > 0) html += '<div class="nav__dropdown-divider"></div>';
          html += '<div class="nav__dropdown-heading">' + group.heading + '</div>';
          group.items.forEach(function(item) {
            var itemActive = isItemActive(item.href, path) ? ' active' : '';
            html += '<a href="' + item.href + '" class="nav__dropdown-item' + itemActive + '">' + item.text + '</a>';
          });
        });
      } else {
        sec.items.forEach(function(item) {
          var itemActive = isItemActive(item.href, path) ? ' active' : '';
          html += '<a href="' + item.href + '" class="nav__dropdown-item' + itemActive + '">' + item.text + '</a>';
        });
      }

      html += '</div></div>';
    });

    html += '<button class="theme-toggle" id="theme-toggle" aria-label="Toggle light/dark mode" title="Toggle theme"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg></button>';
    html += '<a href="/subscribe/" class="nav__link nav__cta">Subscribe \u2192</a>';
    html += '</div>';
    html += '<button class="nav__hamburger" aria-label="Open menu"><span></span><span></span><span></span></button>';
    html += '<div class="nav__status"><div class="pulse"></div><span id="nav-date"></span></div>';
    html += '</nav>';

    // Mobile overlay
    html += '<div class="nav-overlay"><div class="nav-overlay__panel">';
    html += '<button class="nav-overlay__close" aria-label="Close menu">&times;</button>';
    SECTIONS.forEach(function(sec) {
      html += '<div class="nav-overlay__section">';
      html += '<div class="nav-overlay__heading">' + sec.label + '</div>';

      if (sec.groups) {
        sec.groups.forEach(function(group) {
          html += '<div class="nav-overlay__subheading">' + group.heading + '</div>';
          group.items.forEach(function(item) {
            var cls = 'nav-overlay__link';
            if (item.href === '/subscribe/') cls += ' nav-overlay__link--cta';
            if (isItemActive(item.href, path)) cls += ' active';
            html += '<a href="' + item.href + '" class="' + cls + '">' + item.text + '</a>';
          });
        });
      } else {
        sec.items.forEach(function(item) {
          var cls = 'nav-overlay__link';
          if (item.href === '/subscribe/') cls += ' nav-overlay__link--cta';
          if (isItemActive(item.href, path)) cls += ' active';
          html += '<a href="' + item.href + '" class="' + cls + '">' + item.text + '</a>';
        });
      }

      if (sec.label === 'The Chronicle') {
        html += '<a href="/rss.xml" class="nav-overlay__link">RSS</a>';
        html += '<a href="/privacy/" class="nav-overlay__link">Privacy</a>';
      }
      html += '</div>';
    });
    html += '</div></div>';

    return html;
  }

  // ── FOOTER ─────────────────────────────────────────────────
  function buildFooter() {
    var html = '<footer class="footer-v2"><div class="footer-v2__grid">';

    var footerCols = [
      { heading: 'The Story', links: [
        { href: '/', text: 'Home' },
        { href: '/story/', text: 'My Story' },
        { href: '/about/', text: 'The Mission' },
        { href: '/achievements/', text: 'Milestones' },
      ]},
      { heading: 'The Evidence', links: [
        { href: '/sleep/', text: 'Sleep' },
        { href: '/glucose/', text: 'Glucose' },
        { href: '/nutrition/', text: 'Nutrition' },
        { href: '/training/', text: 'Training' },
        { href: '/mind/', text: 'Inner Life' },
        { href: '/labs/', text: 'Labs' },
        { href: '/benchmarks/', text: 'Benchmarks' },
        { href: '/explorer/', text: 'Data Explorer' },
      ]},
      { heading: 'The Pulse', links: [
        { href: '/live/', text: 'Today' },
        { href: '/character/', text: 'The Score' },
        { href: '/habits/', text: 'Habits' },
        { href: '/accountability/', text: 'Accountability' },
      ]},
      { heading: 'The Practice', links: [
        { href: '/stack/', text: 'The Stack' },
        { href: '/protocols/', text: 'Protocols' },
        { href: '/supplements/', text: 'Supplements' },
        { href: '/experiments/', text: 'Experiments' },
        { href: '/challenges/',  text: 'Challenges' },
        { href: '/discoveries/', text: 'Discoveries' },
      ]},
      { heading: 'The Platform', links: [
        { href: '/platform/', text: 'How It Works' },
        { href: '/intelligence/', text: 'The AI' },
        { href: '/board/', text: 'AI Board' },
        { href: '/methodology/', text: 'Methodology' },
        { href: '/cost/', text: 'Cost' },
        { href: '/tools/', text: 'Tools' },
        { href: '/builders/', text: 'For Builders' },
      ]},
      { heading: 'The Chronicle', links: [
        { href: '/chronicle/', text: 'Chronicle Archive' },
        { href: '/weekly/', text: 'Weekly Snapshots' },
        { href: '/recap/', text: 'Weekly Recap' },
        { href: '/ask/', text: 'Ask the Data' },
        { href: '/subscribe/', text: 'Subscribe' },
      ]},
      { heading: 'Internal', links: [
        { href: '/status/', text: 'System Status', id: 'footer-status-link' },
        { href: 'https://dash.averagejoematt.com', text: 'Clinician View', locked: true },
        { href: 'https://buddy.averagejoematt.com', text: 'Buddy Dashboard', locked: true },
        { href: 'https://discord.gg/T4Ndt2WsU', text: 'Join the community', external: true, community: true },
        { href: '/rss.xml', text: 'RSS Feed' },
        { href: '/privacy/', text: 'Privacy' },
      ]},
    ];

    footerCols.forEach(function(col) {
      html += '<div class="footer-v2__col">';
      html += '<div class="footer-v2__heading">' + col.heading + '</div>';
      col.links.forEach(function(link) {
        if (link.community) {
          html += '<a href="' + link.href + '" class="footer-community-link" target="_blank" rel="noopener"><span class="community-glyph">\u2317</span>' + link.text + '</a>';
        } else {
          var linkId = link.id ? ' id="' + link.id + '"' : '';
          var extAttrs = link.external ? ' target="_blank" rel="noopener"' : '';
          var lockIcon = link.locked
            ? ' <svg style="width:10px;height:10px;opacity:.45;vertical-align:middle;margin-left:2px" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="8" height="6" rx="1"/><path d="M4 5V3.5a2 2 0 0 1 4 0V5"/></svg>'
            : '';
          html += '<a href="' + link.href + '" class="footer-v2__link"' + linkId + extAttrs + '>' + link.text + lockIcon + '</a>';
        }
      });
      html += '</div>';
    });

    html += '</div>';
    html += '<div class="footer-v2__bottom">';
    html += '<span class="footer-v2__brand">AJM</span>';
    html += '<span class="footer-v2__copy">// updated daily by life-platform</span>';
    html += '</div></footer>';

    return html;
  }

  // ── BOTTOM NAV (mobile) — 4 sections + More (Decision 1b) ─
  function buildBottomNav() {
    var items = [
      { href: '/',           label: 'Story',     icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
      { href: '/sleep/',     label: 'Evidence',  icon: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>' },
      { href: '/live/',      label: 'Pulse',     icon: '<circle cx="12" cy="12" r="3" fill="currentColor"/><circle cx="12" cy="12" r="7"/>' },
      { href: '/chronicle/', label: 'Chronicle', icon: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>' },
    ];

    var html = '<nav class="bottom-nav" aria-label="Mobile navigation">';
    items.forEach(function(item) {
      html += '<a href="' + item.href + '" class="bottom-nav__link">';
      html += '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' + item.icon + '</svg>';
      html += '<span>' + item.label + '</span></a>';
    });
    // "More" button opens the full overlay (The Practice + The Platform)
    html += '<button class="bottom-nav__link bottom-nav__more" aria-label="More sections">';
    html += '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>';
    html += '<span>More</span></button>';
    html += '</nav>';
    return html;
  }

  // ── SUBSCRIBE CTA ──────────────────────────────────────────
  function buildSubscribeCTA() {
    var slug = path.replace(/\//g, '').replace(/-/g, '') || 'home';

    var ctaHeadline = 'Get the data, every week.';
    var ctaBody = 'Real numbers from <span data-const="platform.data_sources">25</span> data sources. No highlight reel. Every Wednesday, in your inbox.';
    if (path.startsWith('/chronicle') || path.startsWith('/journal')) {
      ctaHeadline = "Follow Elena's weekly chronicle.";
      ctaBody = 'Every Wednesday, a new dispatch. The real week \u2014 including the bad ones.';
    } else if (path.startsWith('/story/')) {
      ctaHeadline = 'Follow the journey.';
      ctaBody = 'The story continues every week. Subscribe for the next chapter.';
    } else if (path === '/' || path === '/index.html') {
      ctaHeadline = 'Follow the experiment from Day 1.';
      ctaBody = 'Real numbers from <span data-const="platform.data_sources">25</span> data sources. No highlight reel. Every Wednesday, in your inbox.';
    } else if (path.startsWith('/sleep') || path.startsWith('/glucose') || path.startsWith('/nutrition') || path.startsWith('/training') || path.startsWith('/live') || path.startsWith('/character') || path.startsWith('/explorer')) {
      ctaHeadline = 'Get AI-powered insights weekly.';
      ctaBody = 'This data feeds a weekly digest with board commentary. No noise, just signal.';
    }

    var html = '<section class="email-cta-footer reveal" style="padding:var(--space-16) var(--page-padding);border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:var(--surface);text-align:center;">';
    html += '<p style="font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--c-amber-500);margin-bottom:var(--space-4)">The Measured Life</p>';
    html += '<h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-4)">' + ctaHeadline + '</h3>';
    html += '<p style="font-size:var(--text-base);color:var(--text-muted);max-width:480px;margin:0 auto var(--space-8);line-height:var(--lh-body)">';
    html += ctaBody + '<br>';
    html += '<a href="/chronicle/sample/" style="color:var(--c-amber-400);text-decoration:none;font-size:var(--text-xs)">See a sample issue \u2192</a></p>';
    html += '<div style="display:flex;gap:var(--space-2);max-width:400px;margin:0 auto">';
    html += '<input id="cta-email-' + slug + '" type="email" placeholder="your@email.com" style="flex:1;background:var(--bg);border:1px solid var(--cta);color:var(--text);font-family:var(--font-mono);font-size:var(--text-xs);padding:var(--space-3) var(--space-4);outline:none;transition:border-color var(--dur-fast);" onfocus="this.style.borderColor=\'var(--c-coral-400)\'" onblur="this.style.borderColor=\'var(--cta)\'">';
    html += '<button onclick="amjSubscribe(\'' + slug + '\')" class="btn btn--cta" style="white-space:nowrap">Subscribe</button>';
    html += '</div>';
    html += '<p id="cta-msg-' + slug + '" style="font-size:var(--text-2xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3);min-height:1em"></p>';
    html += '</section>';
    return html;
  }

  // ── SUBSCRIBE HELPER (shared across all pages) ─────────────
  if (!window.amjSubscribe) {
    window.amjSubscribe = async function(slug) {
      var email = document.getElementById('cta-email-' + slug).value.trim();
      var msg = document.getElementById('cta-msg-' + slug);
      var btn = document.querySelector('#amj-subscribe button, [onclick*="amjSubscribe"]');
      if (!email || !email.includes('@')) {
        msg.textContent = 'Enter a valid email address.';
        msg.style.color = 'var(--c-yellow-status)';
        return;
      }
      if (btn) btn.disabled = true;
      msg.textContent = 'Subscribing\u2026';
      msg.style.color = 'var(--text-muted)';
      try {
        var res = await fetch('/api/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email, source: slug + '_cta' }),
        });
        var data = await res.json();
        if (res.ok) {
          msg.textContent = '\u2713 Check your inbox to confirm.';
          msg.style.color = 'var(--c-amber-500)';
          document.getElementById('cta-email-' + slug).value = '';
        } else {
          msg.textContent = data.error || 'Something went wrong.';
          msg.style.color = 'var(--c-yellow-status)';
        }
      } catch (e) {
        msg.textContent = 'Network error \u2014 try again.';
        msg.style.color = 'var(--c-yellow-status)';
      } finally {
        if (btn) btn.disabled = false;
      }
    };
  }

  // ── SECTION SUB-NAV — consistent across all sections ──────
  function buildSectionNav() {
    // Find which section owns the current path
    var currentSection = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (sectionOwnsPath(SECTIONS[i], path)) {
        currentSection = SECTIONS[i];
        break;
      }
    }
    if (!currentSection) return '';

    var items = getSectionItems(currentSection);
    // Don't show sub-nav if section has fewer than 3 pages or we're on the homepage
    if (items.length < 3 || path === '/') return '';

    // Phase 2: Track visited pages in localStorage
    var VISITED_KEY = 'amj_visited_pages';
    var visited = {};
    try { visited = JSON.parse(localStorage.getItem(VISITED_KEY) || '{}'); } catch(e) {}
    if (!visited[path]) {
      visited[path] = Date.now();
      localStorage.setItem(VISITED_KEY, JSON.stringify(visited));
    }

    var html = '<style>.section-nav{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-4) var(--page-padding);border-bottom:1px solid var(--border);background:var(--surface);font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);overflow-x:auto;-webkit-overflow-scrolling:touch}.section-nav__step{color:var(--text-faint);text-decoration:none;text-transform:uppercase;white-space:nowrap;padding:var(--space-1) var(--space-3);border:1px solid transparent;transition:color .15s}.section-nav__step:hover{color:var(--text-muted)}.section-nav__step.active{color:var(--accent);border-color:var(--accent-dim)}.section-nav__step.visited::before{content:"\2713 ";font-size:9px;opacity:0.6}.section-nav__sep{color:var(--border)}</style>';
    html += '<nav class="section-nav" aria-label="' + currentSection.label + '">';
    items.forEach(function(item, i) {
      if (i > 0) html += '<span class="section-nav__sep">\u00B7</span>';
      var isActive = isItemActive(item.href, path);
      var isVisited = !isActive && visited[item.href];
      var cls = 'section-nav__step';
      if (isActive) cls += ' active';
      else if (isVisited) cls += ' visited';
      html += '<a href="' + item.href + '" class="' + cls + '">' + item.text + '</a>';
    });
    html += '</nav>';
    return html;
  }

  // ── INJECT ─────────────────────────────────────────────────
  var navMount       = document.getElementById('amj-nav');
  var footerMount    = document.getElementById('amj-footer');
  var bottomNavMount = document.getElementById('amj-bottom-nav');
  var subscribeMount = document.getElementById('amj-subscribe');
  var hierNavMount   = document.getElementById('amj-hierarchy-nav');

  if (navMount) {
    navMount.innerHTML = buildNav();
    // NAV-SPACER: Push page content below the fixed nav.
    // This is the single source of truth for nav clearance.
    // Pages should NOT use calc(var(--nav-height) + ...) in their headers.
    var spacer = document.createElement('div');
    spacer.className = 'nav-spacer';
    navMount.parentNode.insertBefore(spacer, navMount.nextSibling);
  }
  if (hierNavMount)   hierNavMount.innerHTML = buildSectionNav();
  if (subscribeMount) subscribeMount.innerHTML = buildSubscribeCTA();
  if (bottomNavMount) bottomNavMount.innerHTML = buildBottomNav();
  if (footerMount)    footerMount.innerHTML = buildFooter();

  // Wire enter key on subscribe input
  if (subscribeMount) {
    var inp = subscribeMount.querySelector('input[type="email"]');
    if (inp) {
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          var btn = subscribeMount.querySelector('button');
          if (btn) btn.click();
        }
      });
    }
  }

  // ── THEME TOGGLE ─────────────────────────────────────────
  (function() {
    var saved = localStorage.getItem('amj-theme');
    if (saved === 'light') document.documentElement.setAttribute('data-theme', 'light');

    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function updateIcon() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      btn.innerHTML = isLight
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
      btn.title = isLight ? 'Switch to dark mode' : 'Switch to light mode';
    }
    updateIcon();

    btn.addEventListener('click', function() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      if (isLight) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('amj-theme', 'dark');
      } else {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('amj-theme', 'light');
      }
      updateIcon();
    });
  })();

  // Auto-load countdown.js if not already included
  if (!window.AMJ_EXPERIMENT) {
    var cdScript = document.createElement('script');
    cdScript.src = '/assets/js/countdown.js';
    cdScript.async = false;
    document.body.appendChild(cdScript);
  }

  // ── Status dot: fetch /api/status/summary and update footer link ──
  (function() {
    var statusLink = document.getElementById('footer-status-link');
    if (!statusLink) return;

    var dot = document.createElement('span');
    dot.style.cssText = 'display:inline-block;width:6px;height:6px;border-radius:50%;background:#888780;margin-right:5px;vertical-align:middle;transition:background .3s';
    statusLink.insertBefore(dot, statusLink.firstChild);

    fetch('/api/status/summary')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) return;
        var colors = { green: '#639922', yellow: '#BA7517', red: '#E24B4A' };
        dot.style.background = colors[data.overall] || '#888780';
        dot.title = data.overall === 'green' ? 'All systems operational'
                  : data.overall === 'yellow' ? 'Degraded performance'
                  : 'Service disruption';
      })
      .catch(function() {});
  })();

})();

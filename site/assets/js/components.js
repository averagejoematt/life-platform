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
 *   The Story | The Data | The Pulse | The Practice | The Platform | The Chronicle
 */
(function() {
  'use strict';

  var path = window.location.pathname;

  // ── Section mapping — 6-section IA (Decision 1a) ──────────
  var SECTIONS = [
    { label: 'The Story', items: [
      { href: '/',               text: 'Home' },
      { href: '/story/',         text: 'My Story' },
      { href: '/mission/',       text: 'The Mission' },
      { href: '/achievements/',  text: 'Milestones' },
      { href: '/field-notes/',   text: 'Field Notes' },
      { href: '/first-person/',  text: 'First Person' },
    ]},
    { label: 'The Data', items: [
      { href: '/sleep/',       text: 'Sleep' },
      { href: '/glucose/',     text: 'Glucose' },
      { href: '/nutrition/',   text: 'Nutrition' },
      { href: '/training/',    text: 'Training' },
      { href: '/physical/',   text: 'Physical' },
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
      { href: '/chronicle/', text: 'Chronicle' },
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
    // PB-R1: Character level badge — populated by JS after public_stats fetch
    html += '<a href="/character/" class="nav__level" id="nav-level" style="display:none" title="Character Sheet"></a>';
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
    // Internal links
    html += '<div class="nav-overlay__section">';
    html += '<div class="nav-overlay__heading">Internal</div>';
    html += '<a href="/status/" class="nav-overlay__link">System Status</a>';
    html += '<a href="/accountability/" class="nav-overlay__link">Buddy Dashboard</a>';
    html += '<a href="https://discord.gg/T4Ndt2WsU" class="nav-overlay__link" target="_blank" rel="noopener">Join the community</a>';
    html += '<a href="/ledger/" class="nav-overlay__link">Snake Fund</a>';
    html += '</div>';
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
        { href: '/mission/', text: 'The Mission' },
        { href: '/achievements/', text: 'Milestones' },
        { href: '/field-notes/', text: 'Field Notes' },
      ]},
      { heading: 'The Data', links: [
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
        { href: '/chronicle/', text: 'Chronicle' },
        { href: '/weekly/', text: 'Weekly Snapshots' },
        { href: '/recap/', text: 'Weekly Recap' },
        { href: '/ask/', text: 'Ask the Data' },
        { href: '/subscribe/', text: 'Subscribe' },
      ]},
      { heading: 'Internal', links: [
        { href: '/status/', text: 'System Status', id: 'footer-status-link' },
        { href: 'https://dash.averagejoematt.com/clinical.html', text: 'Clinician View', locked: true, external: true },
        { href: '/accountability/', text: 'Buddy Dashboard' },
        { href: 'https://discord.gg/T4Ndt2WsU', text: 'Join the community', external: true, community: true },
        { href: '/rss.xml', text: 'RSS Feed' },
        { href: '/ledger/', text: 'Snake Fund' },
        { href: '/privacy/', text: 'Privacy' },
      ]},
    ];

    footerCols.forEach(function(col) {
      html += '<div class="footer-v2__col">';
      html += '<div class="footer-v2__heading">' + col.heading + '</div>';
      col.links.forEach(function(link) {
        if (link.community) {
          html += '<a href="' + link.href + '" class="footer-community-link" target="_blank" rel="noopener" style="font-weight:600"><span class="community-glyph">\u2317</span>' + link.text + '</a>';
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

    var ctaCopy = {
      '/sleep/':       { h: 'Get sleep intelligence weekly.', b: 'Real architecture data from Whoop \u00D7 Eight Sleep. No sleep tips \u2014 sleep science.' },
      '/glucose/':     { h: 'Get metabolic insights weekly.', b: 'CGM data, meal responses, and glucose patterns. What your metabolism is actually doing.' },
      '/nutrition/':   { h: 'Get nutrition data weekly.', b: 'Macros, protein distribution, and adherence rates. The real food log.' },
      '/training/':    { h: 'Get training intelligence weekly.', b: 'CTL, Zone 2, centenarian benchmarks. What training for longevity looks like.' },
      '/mind/':        { h: 'Get inner life insights weekly.', b: 'Journal patterns, mood trajectories, and what the data says about the mind.' },
      '/chronicle/':   { h: 'Follow the story weekly.', b: 'Every Wednesday, a new dispatch. The real week \u2014 including the bad ones.' },
      '/experiments/': { h: 'Get experiment updates.', b: 'N=1 results as they happen. What worked, what didn\'t, and what\'s next.' },
      '/labs/':        { h: 'Follow the biomarker journey.', b: 'Lab results over time. The ground truth behind the wearables.' },
      '/builders/':    { h: 'Follow the build.', b: 'How one person built a 116-tool AI health platform with Claude. Real decisions, real cost.' },
      '/story/':       { h: 'Follow the journey.', b: 'The story continues every week. Subscribe for the next chapter.' },
    };
    var match = null;
    for (var p2 in ctaCopy) { if (path.startsWith(p2)) { match = ctaCopy[p2]; break; } }
    if (path === '/' || path === '/index.html') {
      match = { h: 'Follow the experiment from Day 1.', b: 'Real numbers from 26 data sources. No highlight reel. Every Wednesday, in your inbox.' };
    }
    var ctaHeadline = match ? match.h : 'Get the data, every week.';
    var ctaBody = match ? match.b : 'Real numbers from 26 data sources. No highlight reel. Every Wednesday, in your inbox.';

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

    var html = '<style>.section-nav{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-4) var(--page-padding);border-bottom:1px solid var(--border);background:var(--surface);font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);overflow-x:auto;-webkit-overflow-scrolling:touch}.section-nav__step{color:var(--text-faint);text-decoration:none;text-transform:uppercase;white-space:nowrap;padding:var(--space-1) var(--space-3);border:1px solid transparent;transition:color .15s}.section-nav__step:hover{color:var(--text-muted)}.section-nav__step.active{color:var(--accent);border-color:var(--accent-dim)}.section-nav__step.visited::before{content:"\\2713 ";font-size:var(--text-3xs);opacity:0.6}.section-nav__sep{color:var(--border)}</style>';
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

  // ── SEO: Canonical URL (injected on every page) ──────────
  (function() {
    if (document.querySelector('link[rel="canonical"]')) return;
    var link = document.createElement('link');
    link.rel = 'canonical';
    link.href = 'https://averagejoematt.com' + window.location.pathname;
    document.head.appendChild(link);
  })();

  // ── SEO: RSS feed discovery (ensure every page declares it) ──
  (function() {
    if (document.querySelector('link[type="application/rss+xml"]')) return;
    var link = document.createElement('link');
    link.rel = 'alternate';
    link.type = 'application/rss+xml';
    link.title = 'The Measured Life';
    link.href = '/rss.xml';
    document.head.appendChild(link);
  })();

  // ── Performance: Font preload for critical fonts ──────────
  (function() {
    var fonts = [
      { href: '/assets/fonts/bebas-neue-400.woff2', type: 'font/woff2' },
      { href: '/assets/fonts/space-mono-400.woff2', type: 'font/woff2' },
    ];
    fonts.forEach(function(f) {
      var link = document.createElement('link');
      link.rel = 'preload';
      link.as = 'font';
      link.type = f.type;
      link.href = f.href;
      link.crossOrigin = 'anonymous';
      document.head.appendChild(link);
    });
  })();

  // ── Analytics: Google Analytics 4 ─────────────────────────
  // Replace G-JTKC4L8EBN with your GA4 Measurement ID from analytics.google.com
  (function() {
    var GA_ID = 'G-JTKC4L8EBN';
    if (GA_ID === 'G-JTKC4L8EBN') return; // placeholder — won't load until ID is set
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    function gtag() { window.dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag('js', new Date());
    gtag('config', GA_ID, { send_page_view: true });
  })();

  // ── PB-R1: Populate nav level badge from public_stats ────
  (function() {
    function showBadge(level, emoji) {
      var el = document.getElementById('nav-level');
      if (!el || !level) return;
      el.textContent = 'Lv ' + level + (emoji ? ' ' + emoji : '');
      el.style.display = '';
    }

    function checkGlobal() {
      // Homepage stores stats in window.__amjStats
      if (window.__amjStats && window.__amjStats.character) {
        var ch = window.__amjStats.character;
        showBadge(ch.level, ch.tier_emoji);
        return true;
      }
      return false;
    }

    // On non-homepage pages, fetch public_stats directly
    if (!checkGlobal()) {
      setTimeout(function() {
        if (checkGlobal()) return;
        fetch('/public_stats.json?t=' + Date.now(), { cache: 'no-store' })
          .then(function(r) { return r.ok ? r.json() : null; })
          .then(function(d) {
            if (d && d.character) {
              showBadge(d.character.level, d.character.tier_emoji);
            }
          })
          .catch(function() {});
      }, 500);
    }
  })();

  // ── P1-5: Share affordance ──────────────────────────────────
  (function() {
    var btn = document.createElement('button');
    btn.className = 'amj-share-btn';
    btn.innerHTML = '\u2197 Share';
    btn.style.cssText = 'position:fixed;bottom:80px;right:24px;z-index:90;background:var(--surface,#111);border:1px solid var(--border,rgba(255,255,255,0.06));color:var(--text-faint,rgba(255,255,255,0.4));font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);letter-spacing:1px;padding:8px 14px;cursor:pointer;opacity:0;transition:opacity 0.3s,background 0.2s;';
    document.body.appendChild(btn);
    setTimeout(function() { btn.style.opacity = '1'; }, 2000);

    btn.addEventListener('click', function() {
      var title = document.title;
      var url = window.location.href;
      if (navigator.share) {
        navigator.share({ title: title, url: url }).catch(function() {});
      } else {
        navigator.clipboard.writeText(url).then(function() {
          btn.textContent = 'Copied!';
          btn.style.color = 'var(--c-green-500,#22c55e)';
          setTimeout(function() {
            btn.innerHTML = '\u2197 Share';
            btn.style.color = 'var(--text-faint,rgba(255,255,255,0.4))';
          }, 2000);
        }).catch(function() {});
      }
    });
  })();

  // ── P0-1: Start Here visitor routing modal ──────────────────
  // Shows on first homepage visit if no amj_visited cookie exists.
  (function() {
    if (path !== '/' && path !== '/index.html') return;
    if (document.cookie.indexOf('amj_visited=1') !== -1) return;

    var overlay = document.createElement('div');
    overlay.id = 'amj-start-here';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(8,12,10,0.95);display:flex;align-items:center;justify-content:center;padding:24px;opacity:0;transition:opacity 0.4s ease;';

    var content = '<div style="max-width:960px;width:100%;">' +
      '<div style="text-align:center;margin-bottom:40px;">' +
        '<div style="font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);letter-spacing:3px;text-transform:uppercase;color:var(--c-green-500,#22c55e);margin-bottom:16px;">Welcome to The Measured Life</div>' +
        '<div style="font-family:var(--font-display,Georgia,serif);font-size:clamp(24px,3.5vw,36px);color:#e8e8e8;line-height:1.2;">Where would you like to start?</div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;" id="amj-sh-cards">' +
        // Card 1: The Journey
        '<a href="/story/" class="amj-sh-card" style="display:block;padding:32px 24px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-left:3px solid var(--c-green-500,#22c55e);text-decoration:none;transition:border-color 0.2s,background 0.2s;">' +
          '<div style="font-family:var(--font-display,Georgia,serif);font-size:var(--text-xl,20px);color:#e8e8e8;margin-bottom:8px;">The Journey</div>' +
          '<div style="font-size:14px;color:rgba(255,255,255,0.5);line-height:1.6;">Follow one person\'s health transformation &mdash; honest, public, no filter.</div>' +
          '<div style="margin-top:16px;font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);color:var(--c-green-500,#22c55e);letter-spacing:1px;">Start here &rarr;</div>' +
        '</a>' +
        // Card 2: The Data
        '<a href="/explorer/" class="amj-sh-card" style="display:block;padding:32px 24px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-left:3px solid var(--c-amber-500,#f59e0b);text-decoration:none;transition:border-color 0.2s,background 0.2s;">' +
          '<div style="font-family:var(--font-display,Georgia,serif);font-size:var(--text-xl,20px);color:#e8e8e8;margin-bottom:8px;">The Data</div>' +
          '<div style="font-size:14px;color:rgba(255,255,255,0.5);line-height:1.6;">Explore 26 data sources, N=1 experiments, and live correlations.</div>' +
          '<div style="margin-top:16px;font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);color:var(--c-amber-500,#f59e0b);letter-spacing:1px;">Explore &rarr;</div>' +
        '</a>' +
        // Card 3: How It's Built
        '<a href="/builders/" class="amj-sh-card" style="display:block;padding:32px 24px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-left:3px solid var(--lb-accent,#06b6d4);text-decoration:none;transition:border-color 0.2s,background 0.2s;">' +
          '<div style="font-family:var(--font-display,Georgia,serif);font-size:var(--text-xl,20px);color:#e8e8e8;margin-bottom:8px;">How It\'s Built</div>' +
          '<div style="font-size:14px;color:rgba(255,255,255,0.5);line-height:1.6;">One person built this with Claude. See the full blueprint.</div>' +
          '<div style="margin-top:16px;font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);color:var(--lb-accent,#06b6d4);letter-spacing:1px;">See the stack &rarr;</div>' +
        '</a>' +
      '</div>' +
      '<div style="text-align:center;margin-top:32px;">' +
        '<button id="amj-sh-skip" style="background:none;border:none;cursor:pointer;font-family:var(--font-mono,monospace);font-size:var(--text-xs,11px);color:rgba(255,255,255,0.3);letter-spacing:1px;padding:8px 16px;">Skip &mdash; take me to the homepage</button>' +
      '</div>' +
    '</div>';

    overlay.innerHTML = content;
    document.body.appendChild(overlay);

    // Responsive: stack cards on mobile
    var style = document.createElement('style');
    style.textContent = '@media(max-width:768px){#amj-sh-cards{grid-template-columns:1fr !important;}}' +
      '.amj-sh-card:hover{background:rgba(255,255,255,0.06) !important;border-color:rgba(255,255,255,0.12) !important;}';
    document.head.appendChild(style);

    // Fade in
    requestAnimationFrame(function() {
      requestAnimationFrame(function() { overlay.style.opacity = '1'; });
    });

    function dismiss() {
      document.cookie = 'amj_visited=1;max-age=31536000;path=/;SameSite=Lax';
      overlay.style.opacity = '0';
      setTimeout(function() { overlay.remove(); }, 400);
    }

    // Dismiss on card click or skip
    overlay.querySelectorAll('.amj-sh-card').forEach(function(card) {
      card.addEventListener('click', function() {
        document.cookie = 'amj_visited=1;max-age=31536000;path=/;SameSite=Lax';
        // Navigation happens via href
      });
    });
    document.getElementById('amj-sh-skip').addEventListener('click', dismiss);
  })();

})();

/**
 * renderAIAnalysisCard — Reusable AI expert voice card for observatory pages.
 * Fetches /api/ai_analysis?expert=<key> and renders a styled prose card.
 */
function renderAIAnalysisCard(containerId, expertKey, config) {
  var el = document.getElementById(containerId);
  if (!el) return;

  var EXPERTS = {
    mind:      { name: "Dr. Conti's Observations",       color: '#a78bfa' },
    nutrition: { name: "Dr. Webb's Analysis",            color: '#f59e0b' },
    training:  { name: "Coach's Notes — Dr. Sarah Chen", color: '#ef4444' },
    physical:  { name: "Dr. Victor Reyes's Assessment",  color: '#60a5fa' }
  };

  var expert = EXPERTS[expertKey];
  if (!expert) return;

  el.innerHTML = '<div style="font-family:monospace;font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:0.1em">LOADING ' + expert.name.toUpperCase() + '...</div>';

  fetch('/api/ai_analysis?expert=' + expertKey)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data.analysis) {
        el.innerHTML = '<div style="font-family:var(--font-serif);font-size:13px;color:rgba(255,255,255,0.3)">Analysis generates weekly. Check back Monday.</div>';
        return;
      }

      var date = data.generated_at ? new Date(data.generated_at).toLocaleDateString('en-US', {month:'long', day:'numeric', year:'numeric'}) : '';
      var dataSources = (config && config.dataSources) || '30 days of data';

      el.innerHTML =
        '<div style="border-left:3px solid ' + expert.color + ';padding:20px 24px;background:rgba(255,255,255,0.02)">' +
          '<div style="font-family:monospace;font-size:11px;color:' + expert.color + ';letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px">' + expert.name + '</div>' +
          '<div style="font-family:var(--font-serif);font-size:15px;line-height:1.75;color:rgba(255,255,255,0.82)">' +
            data.analysis.split('\n\n').map(function(p) { return '<p style="margin-top:12px">' + p + '</p>'; }).join('') +
          '</div>' +
          '<div style="margin-top:16px;font-family:monospace;font-size:10px;color:rgba(255,255,255,0.25);letter-spacing:0.08em">' +
            'Generated ' + date + ' · Based on ' + dataSources +
          '</div>' +
        '</div>';
    })
    .catch(function() {
      el.innerHTML = '<div style="font-family:var(--font-serif);font-size:13px;color:rgba(255,255,255,0.3)">Analysis unavailable.</div>';
    });
}

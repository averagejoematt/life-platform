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
 * v1.0.0 — 2026-03-24
 */
(function() {
  'use strict';

  var path = window.location.pathname;

  // ── Section mapping — which dropdown owns which paths ──────
  var SECTIONS = [
    { label: 'The Story', items: [
      { href: '/story/',  text: 'My Story' },
      { href: '/about/',  text: 'The Mission' },
    ]},
    { label: 'The Data', items: [
      { href: '/live/',           text: 'Live' },
      { href: '/character/',      text: 'Character Sheet' },
      { href: '/habits/',         text: 'Habits' },
      { href: '/accountability/', text: 'Progress' },
      { href: '/sleep/',          text: 'Sleep' },
      { href: '/glucose/',        text: 'Glucose' },
      { href: '/supplements/',    text: 'Supplements' },
      { href: '/benchmarks/',     text: 'Benchmarks' },
      { href: '/explorer/',       text: 'Explorer' },
      { href: '/achievements/',   text: 'Milestones' },
    ]},
    { label: 'The Science', items: [
      { href: '/protocols/',    text: 'Protocols' },
      { href: '/experiments/',  text: 'Experiments' },
      { href: '/discoveries/',  text: 'Discoveries' },
    ]},
    { label: 'The Build', items: [
      { href: '/platform/',     text: 'Platform' },
      { href: '/intelligence/', text: 'Intelligence' },
      { href: '/board/',        text: 'AI Board' },
      { href: '/cost/',         text: 'Cost' },
      { href: '/methodology/',  text: 'Methodology' },
      { href: '/tools/',        text: 'Tools' },
    ]},
    { label: 'Follow', items: [
      { href: '/chronicle/', text: 'Weekly Journal' },
      { href: '/weekly/',    text: 'Weekly Snapshots' },
      { href: '/subscribe/', text: 'Subscribe' },
      { href: '/ask/',       text: 'Ask the Data' },
    ]},
  ];

  // Home path also belongs to The Story for active-state purposes
  function sectionOwnsPath(section, p) {
    if (section.label === 'The Story' && p === '/') return true;
    return section.items.some(function(item) {
      return p === item.href || p.startsWith(item.href);
    });
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
      sec.items.forEach(function(item) {
        var itemActive = (path === item.href || (item.href !== '/' && path.startsWith(item.href))) ? ' active' : '';
        html += '<a href="' + item.href + '" class="nav__dropdown-item' + itemActive + '">' + item.text + '</a>';
      });
      html += '</div></div>';
    });

    html += '<a href="/subscribe/" class="nav__link nav__cta">Subscribe →</a>';
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
      sec.items.forEach(function(item) {
        var cls = 'nav-overlay__link';
        if (item.href === '/subscribe/') cls += ' nav-overlay__link--cta';
        if (path === item.href || (item.href !== '/' && path.startsWith(item.href))) cls += ' active';
        html += '<a href="' + item.href + '" class="' + cls + '">' + item.text + '</a>';
      });
      // Add extra links in Follow section
      if (sec.label === 'Follow') {
        html += '<a href="/rss.xml" class="nav-overlay__link">RSS</a>';
        html += '<a href="/privacy/" class="nav-overlay__link">Privacy</a>';
      }
    });
    html += '</div></div>';

    return html;
  }

  // ── FOOTER ─────────────────────────────────────────────────
  function buildFooter() {
    var html = '<footer class="footer-v2"><div class="footer-v2__grid">';

    // Footer columns match sections but with some additions
    var footerCols = [
      { heading: 'The Story', links: [
        { href: '/', text: 'Home' },
        { href: '/story/', text: 'My Story' },
        { href: '/about/', text: 'The Mission' },
      ]},
      { heading: 'The Data', links: [
        { href: '/live/', text: 'Live' },
        { href: '/character/', text: 'Character Sheet' },
        { href: '/habits/', text: 'Habits' },
        { href: '/accountability/', text: 'Progress' },
        { href: '/explorer/', text: 'Explorer' },
        { href: '/achievements/', text: 'Milestones' },
      ]},
      { heading: 'The Science', links: [
        { href: '/protocols/', text: 'Protocols' },
        { href: '/experiments/', text: 'Experiments' },
        { href: '/discoveries/', text: 'Discoveries' },
        { href: '/sleep/', text: 'Sleep' },
        { href: '/glucose/', text: 'Glucose' },
        { href: '/supplements/', text: 'Supplements' },
        { href: '/benchmarks/', text: 'Benchmarks' },
      ]},
      { heading: 'The Build', links: [
        { href: '/platform/', text: 'Platform' },
        { href: '/intelligence/', text: 'Intelligence' },
        { href: '/board/', text: 'AI Board' },
        { href: '/cost/', text: 'Cost' },
        { href: '/methodology/', text: 'Methodology' },
        { href: '/tools/', text: 'Tools' },
      ]},
      { heading: 'Follow', links: [
        { href: '/chronicle/', text: 'Weekly Journal' },
        { href: '/weekly/', text: 'Weekly Snapshots' },
        { href: '/subscribe/', text: 'Subscribe' },
        { href: '/ask/', text: 'Ask the Data' },
        { href: '/rss.xml', text: 'RSS' },
        { href: '/privacy/', text: 'Privacy' },
      ]},
    ];

    footerCols.forEach(function(col) {
      html += '<div class="footer-v2__col">';
      html += '<div class="footer-v2__heading">' + col.heading + '</div>';
      col.links.forEach(function(link) {
        html += '<a href="' + link.href + '" class="footer-v2__link">' + link.text + '</a>';
      });
      html += '</div>';
    });

    html += '</div>';
    html += '<div class="footer-v2__bottom">';
    html += '<span class="footer-v2__brand">AMJ</span>';
    html += '<span class="footer-v2__copy">// updated daily by life-platform</span>';
    html += '</div></footer>';

    return html;
  }

  // ── BOTTOM NAV (mobile) ────────────────────────────────────
  function buildBottomNav() {
    var items = [
      { href: '/',           label: 'Home',      icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
      { href: '/live/',      label: 'Live',      icon: '<circle cx="12" cy="12" r="3" fill="currentColor"/><circle cx="12" cy="12" r="7"/>' },
      { href: '/character/', label: 'Character', icon: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>' },
      { href: '/chronicle/', label: 'Chronicle', icon: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>' },
      { href: '/ask/',       label: 'Ask',       icon: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>' },
    ];

    var html = '<nav class="bottom-nav" aria-label="Mobile navigation">';
    items.forEach(function(item) {
      html += '<a href="' + item.href + '" class="bottom-nav__link">';
      html += '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' + item.icon + '</svg>';
      html += '<span>' + item.label + '</span></a>';
    });
    html += '</nav>';
    return html;
  }

  // ── SUBSCRIBE CTA ──────────────────────────────────────────
  function buildSubscribeCTA() {
    var slug = path.replace(/\//g, '').replace(/-/g, '') || 'home';
    var html = '<section class="email-cta-footer reveal" style="padding:var(--space-16) var(--page-padding);border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:var(--surface);text-align:center;">';
    html += '<p style="font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--c-amber-500);margin-bottom:var(--space-4)">// the weekly signal</p>';
    html += '<h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-4)">Get the data, every week.</h3>';
    html += '<p style="font-size:var(--text-base);color:var(--text-muted);max-width:480px;margin:0 auto var(--space-8);line-height:var(--lh-body)">';
    html += 'Real numbers from 19 data sources. No highlight reel. Every Wednesday, in your inbox.<br>';
    html += '<a href="/chronicle/sample/" style="color:var(--c-amber-400);text-decoration:none;font-size:var(--text-xs)">See a sample issue →</a></p>';
    html += '<div style="display:flex;gap:var(--space-2);max-width:400px;margin:0 auto">';
    html += '<input id="cta-email-' + slug + '" type="email" placeholder="your@email.com" style="flex:1;background:var(--bg);border:1px solid var(--c-amber-500);color:var(--text);font-family:var(--font-mono);font-size:var(--text-xs);padding:var(--space-3) var(--space-4);outline:none;transition:border-color var(--dur-fast);" onfocus="this.style.borderColor=\'var(--c-amber-400)\'" onblur="this.style.borderColor=\'var(--c-amber-500)\'">';
    html += '<button onclick="amjSubscribe(\'' + slug + '\')" class="btn btn--primary" style="background:var(--c-amber-500);border-color:var(--c-amber-500);white-space:nowrap;color:var(--bg)">Subscribe</button>';
    html += '</div>';
    html += '<p id="cta-msg-' + slug + '" style="font-size:var(--text-2xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3);min-height:1em"></p>';
    html += '</section>';
    return html;
  }

  // ── READING PATH CTA ──────────────────────────────────────
  function buildReadingPath() {
    var paths = (window.AMJ && window.AMJ.reading_paths) || {};
    var next = paths[path];
    if (!next) return '';

    var html = '<section class="reading-path" style="padding:var(--space-10) var(--page-padding);border-top:1px solid var(--border);text-align:center;">';
    html += '<span style="font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-faint);display:block;margin-bottom:var(--space-3)">Continue the story</span>';
    html += '<a href="' + next.href + '" style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--accent);text-decoration:none;letter-spacing:var(--ls-display);">' + next.title + '</a>';
    html += '<p style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-2)">' + next.sub + '</p>';
    html += '</section>';
    return html;
  }

  // ── SUBSCRIBE HELPER (shared across all pages) ─────────────
  if (!window.amjSubscribe) {
    window.amjSubscribe = async function(slug) {
      var email = document.getElementById('cta-email-' + slug).value.trim();
      var msg = document.getElementById('cta-msg-' + slug);
      if (!email || !email.includes('@')) {
        msg.textContent = 'Enter a valid email address.';
        msg.style.color = 'var(--c-yellow-status)';
        return;
      }
      msg.textContent = 'Subscribing…';
      msg.style.color = 'var(--text-muted)';
      try {
        var res = await fetch('/api/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email, source: slug + '_cta' }),
        });
        var data = await res.json();
        if (res.ok) {
          msg.textContent = '✓ Check your inbox to confirm.';
          msg.style.color = 'var(--c-amber-500)';
          document.getElementById('cta-email-' + slug).value = '';
        } else {
          msg.textContent = data.error || 'Something went wrong.';
          msg.style.color = 'var(--c-yellow-status)';
        }
      } catch (e) {
        msg.textContent = 'Network error — try again.';
        msg.style.color = 'var(--c-yellow-status)';
      }
    };
  }

  // ── INJECT ─────────────────────────────────────────────────
  var navMount       = document.getElementById('amj-nav');
  var footerMount    = document.getElementById('amj-footer');
  var bottomNavMount = document.getElementById('amj-bottom-nav');
  var subscribeMount = document.getElementById('amj-subscribe');
  var readingMount   = document.getElementById('amj-reading-path');

  if (navMount)       navMount.innerHTML = buildNav();
  if (subscribeMount) subscribeMount.innerHTML = buildSubscribeCTA();
  if (readingMount)   readingMount.innerHTML = buildReadingPath();
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

})();

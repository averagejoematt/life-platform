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
 * v2.0.0 — 2026-03-24 — Board-approved 6-section restructure
 *   Story | Pulse | Evidence | Method | Build | Follow
 */
(function() {
  'use strict';

  var path = window.location.pathname;

  // ── Section mapping — which dropdown owns which paths ──────
  // Items can be plain { href, text } or grouped with { heading, items }
  var SECTIONS = [
    { label: 'Story', items: [
      { href: '/',       text: 'Home' },
      { href: '/story/', text: 'My Story' },
      { href: '/about/', text: 'The Mission' },
    ]},
    { label: 'Pulse', items: [
      { href: '/live/',           text: 'Today' },
      { href: '/character/',      text: 'Character' },
      { href: '/habits/',         text: 'Habits' },
      { href: '/accountability/', text: 'Accountability' },
      { href: '/achievements/',   text: 'Milestones' },
    ]},
    { label: 'Evidence', items: [
      { href: '/sleep/',      text: 'Sleep' },
      { href: '/glucose/',    text: 'Glucose' },
      { href: '/nutrition/',  text: 'Nutrition' },
      { href: '/training/',   text: 'Training' },
      { href: '/mind/',       text: 'Inner Life' },
      { href: '/benchmarks/',text: 'Benchmarks' },
      { href: '/explorer/',  text: 'Data Explorer' },
    ]},
    { label: 'Method', groups: [
      { heading: 'What I Do', items: [
        { href: '/stack/',       text: 'The Stack' },
        { href: '/protocols/',   text: 'Protocols' },
        { href: '/supplements/', text: 'Supplements' },
      ]},
      { heading: 'What I Tested', items: [
        { href: '/experiments/', text: 'Active Tests' },
        { href: '/challenges/',  text: 'The Arena' },
        { href: '/discoveries/', text: 'Discoveries' },
      ]},
    ]},
    { label: 'Build', items: [
      { href: '/platform/',     text: 'Platform' },
      { href: '/intelligence/', text: 'The AI' },
      { href: '/board/',        text: 'AI Board' },
      { href: '/cost/',         text: 'Cost' },
      { href: '/methodology/',  text: 'Methodology' },
      { href: '/tools/',        text: 'Tools' },
      { href: '/builders/',     text: 'For Builders' },
    ]},
    { label: 'Follow', items: [
      { href: '/chronicle/', text: 'Chronicle' },
      { href: '/weekly/',    text: 'Weekly Snapshots' },
      { href: '/subscribe/', text: 'Subscribe' },
      { href: '/ask/',       text: 'Ask the Data' },
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

  // Home path also belongs to Story for active-state purposes
  function sectionOwnsPath(section, p) {
    if (section.label === 'Story' && p === '/') return true;
    return getSectionItems(section).some(function(item) {
      return p === item.href || p.startsWith(item.href);
    });
  }

  // ── Helper: check if item is active ──
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
        // Grouped dropdown with sub-headers
        sec.groups.forEach(function(group, gi) {
          if (gi > 0) html += '<div class="nav__dropdown-divider"></div>';
          html += '<div class="nav__dropdown-heading">' + group.heading + '</div>';
          group.items.forEach(function(item) {
            var itemActive = isItemActive(item.href, path) ? ' active' : '';
            html += '<a href="' + item.href + '" class="nav__dropdown-item' + itemActive + '">' + item.text + '</a>';
          });
        });
      } else {
        // Flat dropdown
        sec.items.forEach(function(item) {
          var itemActive = isItemActive(item.href, path) ? ' active' : '';
          html += '<a href="' + item.href + '" class="nav__dropdown-item' + itemActive + '">' + item.text + '</a>';
        });
      }

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

      // Add extra links in Follow section
      if (sec.label === 'Follow') {
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
      { heading: 'Story', links: [
        { href: '/', text: 'Home' },
        { href: '/story/', text: 'My Story' },
        { href: '/about/', text: 'The Mission' },
      ]},
      { heading: 'Pulse', links: [
        { href: '/live/', text: 'Today' },
        { href: '/character/', text: 'Character' },
        { href: '/habits/', text: 'Habits' },
        { href: '/accountability/', text: 'Accountability' },
        { href: '/achievements/', text: 'Milestones' },
      ]},
      { heading: 'Evidence', links: [
        { href: '/sleep/', text: 'Sleep' },
        { href: '/glucose/', text: 'Glucose' },
        { href: '/nutrition/', text: 'Nutrition' },
        { href: '/training/', text: 'Training' },
        { href: '/mind/', text: 'Inner Life' },
        { href: '/benchmarks/', text: 'Benchmarks' },
        { href: '/explorer/', text: 'Data Explorer' },
      ]},
      { heading: 'Method', links: [
        { href: '/stack/', text: 'The Stack' },
        { href: '/protocols/', text: 'Protocols' },
        { href: '/supplements/', text: 'Supplements' },
        { href: '/experiments/', text: 'Active Tests' },
        { href: '/challenges/', text: 'The Arena' },
        { href: '/discoveries/', text: 'Discoveries' },
      ]},
      { heading: 'Build', links: [
        { href: '/platform/', text: 'Platform' },
        { href: '/intelligence/', text: 'The AI' },
        { href: '/board/', text: 'AI Board' },
        { href: '/cost/', text: 'Cost' },
        { href: '/methodology/', text: 'Methodology' },
        { href: '/tools/', text: 'Tools' },
        { href: '/builders/', text: 'For Builders' },
      ]},
      { heading: 'Follow', links: [
        { href: '/chronicle/', text: 'Chronicle' },
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
    html += '<span class="footer-v2__brand">AJM</span>';
    html += '<span class="footer-v2__copy">// updated daily by life-platform</span>';
    html += '</div></footer>';

    return html;
  }

  // ── BOTTOM NAV (mobile) ────────────────────────────────────
  function buildBottomNav() {
    var items = [
      { href: '/',           label: 'Home',      icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
      { href: '/live/',      label: 'Today',     icon: '<circle cx="12" cy="12" r="3" fill="currentColor"/><circle cx="12" cy="12" r="7"/>' },
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

    // Contextual CTA messaging
    var ctaHeadline = 'Get the data, every week.';
    var ctaBody = 'Real numbers from <span data-const="platform.data_sources">19</span> data sources. No highlight reel. Every Wednesday, in your inbox.';
    if (path.startsWith('/chronicle') || path.startsWith('/journal')) {
      ctaHeadline = "Follow Elena's weekly chronicle.";
      ctaBody = 'Every Wednesday, a new dispatch. The real week — including the bad ones.';
    } else if (path.startsWith('/story/')) {
      ctaHeadline = 'Follow the journey.';
      ctaBody = 'The story continues every week. Subscribe for the next chapter.';
    } else if (path === '/' || path === '/index.html') {
      ctaHeadline = 'Follow the experiment from Day 1.';
      ctaBody = 'Real numbers from <span data-const="platform.data_sources">19</span> data sources. No highlight reel. Every Wednesday, in your inbox.';
    } else if (path.startsWith('/sleep') || path.startsWith('/glucose') || path.startsWith('/nutrition') || path.startsWith('/training') || path.startsWith('/live') || path.startsWith('/character') || path.startsWith('/explorer')) {
      ctaHeadline = 'Get AI-powered insights weekly.';
      ctaBody = 'This data feeds a weekly digest with board commentary. No noise, just signal.';
    }

    var html = '<section class="email-cta-footer reveal" style="padding:var(--space-16) var(--page-padding);border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:var(--surface);text-align:center;">';
    html += '<p style="font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--c-amber-500);margin-bottom:var(--space-4)">// the weekly signal</p>';
    html += '<h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-4)">' + ctaHeadline + '</h3>';
    html += '<p style="font-size:var(--text-base);color:var(--text-muted);max-width:480px;margin:0 auto var(--space-8);line-height:var(--lh-body)">';
    html += ctaBody + '<br>';
    html += '<a href="/chronicle/sample/" style="color:var(--c-amber-400);text-decoration:none;font-size:var(--text-xs)">See a sample issue →</a></p>';
    html += '<div style="display:flex;gap:var(--space-2);max-width:400px;margin:0 auto">';
    html += '<input id="cta-email-' + slug + '" type="email" placeholder="your@email.com" style="flex:1;background:var(--bg);border:1px solid var(--c-amber-500);color:var(--text);font-family:var(--font-mono);font-size:var(--text-xs);padding:var(--space-3) var(--space-4);outline:none;transition:border-color var(--dur-fast);" onfocus="this.style.borderColor=\'var(--c-amber-400)\'" onblur="this.style.borderColor=\'var(--c-amber-500)\'">';
    html += '<button onclick="amjSubscribe(\'' + slug + '\')" class="btn btn--primary" style="background:var(--c-amber-500);border-color:var(--c-amber-500);white-space:nowrap;color:var(--bg)">Subscribe</button>';
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
  // ── HIERARCHY NAV (replaces pipeline nav on method pages) ──────
  var HIER_ITEMS = [
    { href: '/stack/',       label: 'The Stack',    sub: 'the map',      rel: '' },
    { href: '/protocols/',   label: 'Protocols',    sub: 'strategy',     rel: 'contains' },
    { href: '/habits/',      label: 'Habits',       sub: 'daily actions',rel: '·' },
    { href: '/experiments/', label: 'Experiments',   sub: 'tests',        rel: '·' },
    { href: '/challenges/',  label: 'The Arena',     sub: 'challenges',   rel: '·' },
    { href: '/discoveries/', label: 'Discoveries',  sub: 'evidence',     rel: '→' },
    { href: '/supplements/', label: 'Supplements',  sub: 'the stack',    rel: '·' },
    { href: '/achievements/',label: 'Milestones',   sub: 'outcomes',     rel: '·' },
  ];

  var HIER_CONTEXT = {
    '/stack/':        'The complete picture — every protocol, habit, experiment, and supplement organized by domain.',
    '/protocols/':    'Protocols are the <strong>strategy layer</strong>. Each one contains <a href="/habits/">daily habits</a> that execute it, and may spawn <a href="/experiments/">experiments</a> to test variations.',
    '/habits/':       'Habits are the <strong>daily execution layer</strong> of each <a href="/protocols/">protocol</a>. Sustained habits unlock <a href="/achievements/">milestones</a> and feed your <a href="/character/">character score</a>.',
    '/experiments/':  'Experiments are <strong>time-bounded tests</strong> of <a href="/protocols/">protocol</a> variations. Each has a hypothesis, defined duration, and produces data that becomes a <a href="/discoveries/">discovery</a>.',
    '/challenges/':   'Challenges are <strong>action-oriented goals</strong> generated from journal patterns, data signals, and confirmed <a href="/experiments/">experiments</a>. Complete them to earn XP and level up your <a href="/character/">character</a>.',
    '/discoveries/':  'Discoveries are <strong>validated insights</strong> from completed <a href="/experiments/">experiments</a>. Confirmed findings feed back into <a href="/protocols/">protocols</a>.',
    '/supplements/':  'Supplements <strong>support the protocols</strong>. Each one has a rationale, evidence tier, and links to the <a href="/protocols/">protocol</a> it serves.',
    '/achievements/': 'Milestones are <strong>thresholds unlocked</strong> by sustained <a href="/habits/">habit</a> execution, <a href="/experiments/">experiment</a> completion, and <a href="/character/">character</a> growth. Computed from live data.',
  };

  function buildHierarchyNav() {
    var html = '<nav style="display:flex;align-items:stretch;border-bottom:1px solid var(--border);font-family:var(--font-mono);font-size:var(--text-2xs);overflow-x:auto;-webkit-overflow-scrolling:touch;">';
    HIER_ITEMS.forEach(function(item, i) {
      if (i > 0 && item.rel) {
        html += '<span style="display:flex;align-items:center;padding:0 4px;color:var(--text-faint);font-size:9px;background:var(--surface);white-space:nowrap;">' + item.rel + '</span>';
      }
      var isActive = (path === item.href || (item.href !== '/' && path.startsWith(item.href)));
      var bg = isActive ? 'var(--bg)' : 'var(--surface)';
      var color = isActive ? 'var(--accent)' : 'var(--text-faint)';
      var border = isActive ? 'border-bottom:2px solid var(--accent);' : '';
      html += '<a href="' + item.href + '" style="padding:8px 10px;display:flex;flex-direction:column;align-items:center;gap:1px;text-decoration:none;color:' + color + ';background:' + bg + ';white-space:nowrap;min-width:70px;' + border + '">';
      html += '<span style="font-weight:500;font-size:11px;letter-spacing:var(--ls-tag);">' + item.label + '</span>';
      html += '<span style="font-size:9px;opacity:0.7;">' + item.sub + '</span>';
      html += '</a>';
    });
    html += '</nav>';

    var contextText = HIER_CONTEXT[path];
    if (contextText) {
      html += '<div style="margin:12px var(--page-padding);padding:10px 14px;border-left:2px solid var(--accent);background:var(--surface);font-size:var(--text-xs);color:var(--text-muted);line-height:var(--lh-body);">';
      html += '<span style="font-size:var(--text-2xs);font-weight:500;color:var(--accent);letter-spacing:0.04em;text-transform:uppercase;">Where this fits</span><br>';
      html += contextText;
      html += '</div>';
    }
    return html;
  }

  var navMount       = document.getElementById('amj-nav');
  var footerMount    = document.getElementById('amj-footer');
  var bottomNavMount = document.getElementById('amj-bottom-nav');
  var subscribeMount = document.getElementById('amj-subscribe');
  var hierNavMount   = document.getElementById('amj-hierarchy-nav');

  if (navMount)       navMount.innerHTML = buildNav();
  if (hierNavMount)   hierNavMount.innerHTML = buildHierarchyNav();
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

  // ── Auto-load countdown.js if not already included ──
  // Guard: skip if page already loaded it via explicit <script> tag
  if (!window.AMJ_EXPERIMENT) {
    var cdScript = document.createElement('script');
    cdScript.src = '/assets/js/countdown.js';
    cdScript.async = false;
    document.body.appendChild(cdScript);
  }

})();

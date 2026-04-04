/**
 * site_constants.js — Single source of truth for all factual content on averagejoematt.com
 *
 * RULE: If a value appears on more than one page, it lives here.
 * Pages reference these via data-const="key.path" attributes on elements,
 * or read window.AMJ directly in page-specific JS.
 *
 * Platform stats auto-hydrate from /api/platform_stats on page load.
 * The values below are fallbacks — the API response overrides them.
 *
 * After editing this file, run: deploy/sync_site_content.sh --check
 * to verify all data-const references resolve.
 *
 * v2.0.0 — 2026-03-30
 */
window.AMJ = {

  // ── Journey ────────────────────────────────────────────────
  journey: {
    start_weight:  307,
    goal_weight:   185,
    start_date:    '2026-04-01',
    experiment_start: '2026-04-01',  // Day 1 of the public experiment
    build_date:    '2026-02-22',     // Day platform build began
    phase:         'Launch',
    hero_tagline:  'Day 1. For real this time.',
    hero_short:    '307 → 185. 26 data sources. Every number public.',
    hero_copy:     'I built an AI health platform, got sick, fell off the wagon, and the system I built didn\'t catch me. So I\'m starting over — publicly. April 1, 2026 is Day 1. Every number, every failure, no filter.',
    cta_sub:       '307 lbs. A relapse. A relaunch. Day 1.',
  },

  // ── Platform (fallbacks — overridden by /api/platform_stats) ──
  platform: {
    data_sources:   26,
    mcp_tools:      121,
    lambdas:        62,
    monthly_cost:   '$19',
    review_grade:   'A',
    review_count:   19,
    test_count:     1075,
    cdk_stacks:     8,
    alarms:         66,
    active_secrets: 10,
    adrs:           45,
    site_pages:     72,
    board_technical: 12,
    board_product:  8,
  },

  // ── Bios (press kit / about page) ─────────────────────────
  bios: {
    fifty_word: 'Matthew built a personal health intelligence platform from scratch using AI as a development partner. 26 data sources, 121 AI tools, 62 AWS Lambda functions, running for $19/month. He publishes every number, every failure, every week.',
    hundred_word: 'Matthew is the creator of Life Platform — a personal health intelligence system built entirely with AI assistance. Using Claude as a development partner, Matthew built 26 data integrations, 121 intelligence tools, and a fully automated daily coaching brief that runs on AWS for $19/month. He documents every result publicly — wins, failures, and everything in between. His work is both a personal transformation project and a live proof-of-concept for what one person can build when AI removes the traditional barriers to software development.',
  },

  // ── OG / meta descriptions ─────────────────────────────────
  meta: {
    home:        'Day 1: April 1, 2026. 307 lbs. 26 data sources. An AI health platform. Every number public, every failure included.',
    live:        'Real-time metrics from 26 data sources. Weight, HRV, recovery, habits, and the full transformation timeline.',
    story:       '307 lbs. And a decision to stop optimizing in the dark.',
    about:       'IT leader by day. Solo engineer by night. Building the infrastructure to change everything.',
    platform:    '62 Lambda functions. 121 AI tools. 26 data sources. $19/month. A single-person health intelligence system on AWS serverless.',
    character:   '7-pillar scoring system: Sleep, Movement, Nutrition, Mind, Metabolic, Consistency, Relationships.',
    methodology: 'Pearson r, Benjamini-Hochberg FDR, 26 data sources. The statistical framework behind the experiment.',
  },

  // ── Reading paths (nav.js consumes these) ──────────────────
  reading_paths: {
    '/story/':             { href: '/live/',            title: 'See Today\'s Data →',      sub: 'What the sensors say right now' },
    '/about/':             { href: '/story/',           title: 'The Story →',              sub: 'Read the full transformation narrative' },
    '/live/':              { href: '/character/',       title: 'The Score →',              sub: 'How it all adds up' },
    '/character/':         { href: '/habits/',          title: 'The Habits →',             sub: 'The inputs that drive the score' },
    '/habits/':            { href: '/experiments/',     title: 'Experiments →',            sub: 'What\'s being actively tested' },
    '/accountability/':    { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the science works' },
    '/protocols/':         { href: '/live/',            title: 'The Results →',            sub: 'What these protocols produced' },
    '/experiments/':       { href: '/discoveries/',     title: 'Discoveries →',            sub: 'What the data proved' },
    '/discoveries/':       { href: '/intelligence/',    title: 'The Intelligence Layer →', sub: 'How the AI finds these patterns' },
    '/sleep/':             { href: '/glucose/',         title: 'Glucose Data →',           sub: '30-day CGM time-in-range' },
    '/glucose/':           { href: '/benchmarks/',      title: 'Benchmarks →',             sub: 'How Matthew compares to population norms' },
    '/benchmarks/':        { href: '/subscribe/',       title: 'Get Weekly Updates →',     sub: 'New data every week' },
    '/supplements/':       { href: '/protocols/',       title: 'All Protocols →',          sub: 'Sleep, training, nutrition, supplements' },
    '/platform/':          { href: '/cost/',            title: 'The Real Cost →',          sub: 'Running a full health OS for $19/month' },
    '/cost/':              { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the science works' },
    '/methodology/':       { href: '/intelligence/',    title: 'The Intelligence Layer →', sub: 'What the AI actually does' },
    '/intelligence/':      { href: '/discoveries/',     title: 'Discoveries →',            sub: 'What the data revealed' },
    '/board/':             { href: '/board/technical/', title: 'Technical Board →',        sub: '12 personas keeping the architecture honest' },
    '/board/technical/':   { href: '/board/product/',   title: 'Product Board →',          sub: '8 personas shaping what this site becomes' },
    '/board/product/':     { href: '/platform/',        title: 'How This Works →',         sub: 'The full platform architecture' },
    '/data/':              { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the data is processed' },
    '/tools/':             { href: '/ask/',             title: 'Ask the Data →',           sub: 'Query 26 sources of live data' },
    '/week/':              { href: '/subscribe/',       title: 'Get This Weekly →',        sub: 'Every week, in your inbox' },
    '/chronicle/':         { href: '/chronicle/archive/', title: 'All Entries →',          sub: 'The full chronicle archive' },
    '/chronicle/archive/': { href: '/subscribe/',       title: 'Get the Weekly Brief →',   sub: 'Delivered every week' },
    '/ask/':               { href: '/platform/',        title: 'How This Works →',         sub: 'The platform behind the AI' },
    '/explorer/':          { href: '/discoveries/',     title: 'Validated Discoveries →',  sub: 'Correlations that survived scrutiny' },
    '/weekly/':            { href: '/explorer/',        title: 'Explore the Data →',       sub: 'Pick any two metrics and discover correlations' },
    '/achievements/':      { href: '/character/',       title: 'The Character Sheet →',    sub: 'How it all adds up into one score' },
  },
};

// ── Auto-inject constants into data-const elements ───────────
(function() {
  'use strict';
  function resolve(obj, path) {
    return path.split('.').reduce(function(o, k) { return o && o[k]; }, obj);
  }
  function inject() {
    document.querySelectorAll('[data-const]').forEach(function(el) {
      var val = resolve(window.AMJ, el.getAttribute('data-const'));
      if (val !== undefined && val !== null) {
        el.textContent = val;
      }
    });
  }
  // Inject defaults immediately
  inject();

  // Then hydrate from API — overrides stale defaults
  fetch('/api/platform_stats')
    .then(function(r) { return r.json(); })
    .then(function(stats) {
      // Merge API stats into window.AMJ.platform
      Object.keys(stats).forEach(function(k) {
        if (stats[k] !== null && stats[k] !== undefined) {
          window.AMJ.platform[k] = stats[k];
        }
      });
      // Also update journey constants that come from the API
      if (stats.start_weight) window.AMJ.journey.start_weight = stats.start_weight;
      if (stats.goal_weight) window.AMJ.journey.goal_weight = stats.goal_weight;
      // Re-inject with fresh values
      inject();
    })
    .catch(function() { /* fallbacks are already injected */ });
})();

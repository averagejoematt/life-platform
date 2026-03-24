/**
 * site_constants.js — Single source of truth for all factual content on averagejoematt.com
 *
 * RULE: If a value appears on more than one page, it lives here.
 * Pages reference these via data-const="key.path" attributes on elements,
 * or read window.AMJ directly in page-specific JS.
 *
 * After editing this file, run: deploy/sync_site_content.sh --check
 * to verify all data-const references resolve.
 *
 * v1.0.0 — 2026-03-24
 */
window.AMJ = {

  // ── Journey ────────────────────────────────────────────────
  journey: {
    start_weight:  302,
    goal_weight:   185,
    start_date:    '2026-02-22',
    phase:         'Ignition',
    hero_tagline:  '302 → 185. 19 data sources. 95 AI tools. Every number public. Built by a non-engineer with Claude.',
    hero_short:    '302 → 185. 19 data sources. Every number public.',
    hero_copy:     'Most people optimize in the dark — gut feelings, Instagram advice, someone\'s podcast take. I connect 19 data sources to a custom AI and publish every number, every week, without filtering. 302 lbs to 185. Every failure included. This is what systematic self-improvement actually looks like.',
    cta_sub:       '302 lbs. A goal. Every failure included.',
  },

  // ── Platform ───────────────────────────────────────────────
  platform: {
    data_sources:   19,
    mcp_tools:      95,
    lambdas:        50,
    monthly_cost:   '~$13',
    review_grade:   'A-',
    review_count:   17,
    test_count:     83,
    cdk_stacks:     8,
    alarms:         49,
    active_secrets: 10,
  },

  // ── Bios (press kit / about page) ─────────────────────────
  bios: {
    fifty_word: 'Matthew Walker is a Senior IT Director who built a personal health intelligence platform from scratch using AI — no engineering degree required. 19 data sources, 95 AI tools, 50 AWS Lambda functions, running for under $15/month. He publishes every number, every failure, every week.',
    hundred_word: 'Matthew Walker is a Senior IT Director at a Seattle SaaS company and the creator of Life Platform — a personal health intelligence system built entirely with AI assistance. With no formal engineering background, Matthew used Claude as a development partner to build 19 data integrations, 95 intelligence tools, and a fully automated daily coaching brief that runs on AWS for under $15/month. He documents every result publicly — wins, failures, and everything in between. His work is both a personal transformation project and a live proof-of-concept for enterprise AI adoption by non-engineers.',
  },

  // ── OG / meta descriptions ─────────────────────────────────
  meta: {
    home:        '302 → 185. 19 data sources. 95 AI tools. Every number public. Built by a non-engineer with Claude.',
    live:        'Real-time metrics from 19 data sources. Weight, HRV, recovery, habits, and the full transformation timeline.',
    story:       '302 lbs. And a decision to stop optimizing in the dark.',
    about:       'IT leader by day. Solo engineer by night. Building the infrastructure to change everything.',
    platform:    '50 Lambda functions. 95 AI tools. 19 data sources. $13/month. A single-person health intelligence system on AWS serverless.',
    character:   '7-pillar scoring system: Sleep, Movement, Nutrition, Mind, Metabolic, Consistency, Relationships.',
    methodology: 'Pearson r, Benjamini-Hochberg FDR, 19 data sources. The statistical framework behind the experiment.',
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
    '/platform/':          { href: '/cost/',            title: 'The Real Cost →',          sub: 'Running a full health OS for ~$13/month' },
    '/cost/':              { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the science works' },
    '/methodology/':       { href: '/intelligence/',    title: 'The Intelligence Layer →', sub: 'What the AI actually does' },
    '/intelligence/':      { href: '/discoveries/',     title: 'Discoveries →',            sub: 'What the data revealed' },
    '/board/':             { href: '/board/technical/', title: 'Technical Board →',        sub: '12 personas keeping the architecture honest' },
    '/board/technical/':   { href: '/board/product/',   title: 'Product Board →',          sub: '8 personas shaping what this site becomes' },
    '/board/product/':     { href: '/platform/',        title: 'How This Works →',         sub: 'The full platform architecture' },
    '/data/':              { href: '/methodology/',     title: 'The Methodology →',        sub: 'How the data is processed' },
    '/tools/':             { href: '/ask/',             title: 'Ask the Data →',           sub: 'Query 19 sources of live data' },
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
  document.querySelectorAll('[data-const]').forEach(function(el) {
    var val = resolve(window.AMJ, el.getAttribute('data-const'));
    if (val !== undefined && val !== null) {
      el.textContent = val;
    }
  });
})();

/**
 * og-image Lambda (us-east-1)
 * 
 * GET /og — Returns a dynamically-generated SVG social preview image
 * with live stats baked in from generated/public_stats.json on S3.
 * 
 * CloudFront behavior: /og → this Lambda, Cache TTL 3600s (1hr)
 * OG image tag on site: <meta property="og:image" content="https://averagejoematt.com/og">
 * 
 * DEPLOY:
 *   1. Create Lambda: life-platform-og-image (us-east-1, Node 20, 256MB, 10s timeout)
 *   2. Add Function URL (AuthType NONE)
 *   3. Add S3:GetObject permission on matthew-life-platform/generated/public_stats.json
 *   4. Add CloudFront behavior: /og → this Lambda's Function URL
 *   5. Update OG meta tags on all pages to use /og instead of /assets/images/og-image.png
 * 
 * v1.0.0 — 2026-03-18 (WR-17)
 */

import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';

const s3 = new S3Client({ region: 'us-west-2' });
const BUCKET = 'matthew-life-platform';
// ADR-046: public_stats.json lives under generated/, not site/data/ (the old
// path returned NoSuchKey, so live stats were silently absent). Fixed 2026-06-08.
const KEY = 'generated/public_stats.json';

// Cache stats in warm container (5 min)
let _statsCache = null;
let _statsCacheExpiry = 0;

async function getStats() {
  if (_statsCache && Date.now() < _statsCacheExpiry) return _statsCache;
  try {
    const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: KEY }));
    const body = await resp.Body.transformToString('utf-8');
    _statsCache = JSON.parse(body);
    _statsCacheExpiry = Date.now() + 5 * 60 * 1000;
    return _statsCache;
  } catch (e) {
    console.error('[og-image] S3 fetch failed:', e.message);
    return null;
  }
}

function safeNum(val, decimals = 0) {
  if (val == null || isNaN(val)) return '—';
  return Number(val).toFixed(decimals);
}

// ── v5 "Measured Life" palette (mirrors site/assets/css/tokens.css). The OG card
//    renders server-side without the web fonts, so the type TRIAD is honoured by
//    ROLE via generic families: serif = human/headline (Fraunces), mono = data &
//    labels (IBM Plex Mono), sans = interface (Instrument Sans).
const C = {
  page: '#0E0C08', surface: '#16130E', raised: '#211C14',
  ink: '#ECE3D2', muted: '#A99F8C', faint: '#857B68', ember: '#DD7A37',
};
const SERIF = 'Georgia, \'Times New Roman\', serif';
const MONO = '\'IBM Plex Mono\', ui-monospace, monospace';

function progressBar(pct, width = 200, height = 8) {
  const fill = Math.max(0, Math.min(100, pct || 0));
  const fillWidth = Math.round(width * fill / 100);
  return `
    <rect x="0" y="0" width="${width}" height="${height}" rx="2" fill="${C.raised}"/>
    <rect x="0" y="0" width="${fillWidth}" height="${height}" rx="2" fill="${C.ember}"/>
  `;
}

// The platform's instrument mark — the same vocabulary as the coach sigils
// (concentric ring + radial measuring-ticks + an orbital node). Earned glow:
// ember, the "alive" accent. Ties the share card to the on-site identity.
function instrumentMark(cx, cy, r, color = C.ember) {
  let ticks = '';
  for (let i = 0; i < 12; i++) {
    const a = (Math.PI / 6) * i;
    const x1 = cx + (r - 7) * Math.cos(a), y1 = cy + (r - 7) * Math.sin(a);
    const x2 = cx + r * Math.cos(a), y2 = cy + r * Math.sin(a);
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${color}" stroke-width="2" opacity="0.7"/>`;
  }
  const nx = cx + (r - 14) * Math.cos(-0.9), ny = cy + (r - 14) * Math.sin(-0.9);
  return `<g>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="2"/>
    <circle cx="${cx}" cy="${cy}" r="${r - 14}" fill="none" stroke="${color}" stroke-width="2" opacity="0.85"/>
    ${ticks}
    <circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="4" fill="${color}"/>
    <circle cx="${cx}" cy="${cy}" r="3" fill="${color}"/>
  </g>`;
}

function buildSvg(stats) {
  const j = (stats && stats.journey) || {};
  const v = (stats && stats.vitals) || {};
  const p = (stats && stats.platform) || {};

  const weight = safeNum(j.current_weight_lbs, 1);
  const lost = safeNum(j.lost_lbs, 1);
  const progress = j.progress_pct != null ? Number(j.progress_pct).toFixed(1) : '—';
  const hrv = safeNum(v.hrv_ms, 0);
  const recovery = safeNum(v.recovery_pct, 0);
  const streak = safeNum(p.tier0_streak, 0);
  const daysIn = safeNum(p.days_in, 0);
  const progressNum = parseFloat(j.progress_pct) || 0;

  // Stat card — accent ember only on the truly-live signals (earned), faint otherwise.
  const card = (x, label, value, unit) => `
    <rect x="${x}" y="270" width="220" height="110" fill="${C.surface}" rx="6"/>
    <rect x="${x}" y="270" width="220" height="3" fill="${C.ember}" rx="2"/>
    <text x="${x + 20}" y="298" font-family="${MONO}" font-size="11" fill="${C.faint}" letter-spacing="2">${label}</text>
    <text x="${x + 20}" y="348" font-family="${MONO}" font-size="46" fill="${C.ink}">${value}</text>
    <text x="${x + 20}" y="372" font-family="${MONO}" font-size="11" fill="${C.faint}">${unit}</text>`;

  return `<svg width="1200" height="630" viewBox="0 0 1200 630" xmlns="http://www.w3.org/2000/svg">
  <rect width="1200" height="630" fill="${C.page}"/>

  <!-- warm ember bloom behind the headline — earned depth, never gloss -->
  <defs><radialGradient id="bloom" cx="22%" cy="20%" r="55%">
    <stop offset="0%" stop-color="${C.ember}" stop-opacity="0.10"/>
    <stop offset="100%" stop-color="${C.ember}" stop-opacity="0"/>
  </radialGradient></defs>
  <rect width="1200" height="630" fill="url(#bloom)"/>

  <!-- left ember accent bar (the one live accent) -->
  <rect x="0" y="0" width="4" height="630" fill="${C.ember}"/>

  <!-- top bar -->
  <rect x="0" y="0" width="1200" height="70" fill="${C.surface}"/>
  <rect x="38" y="29" width="12" height="12" rx="2" fill="${C.ember}"/>
  <text x="62" y="44" font-family="${MONO}" font-size="14" fill="${C.muted}" letter-spacing="1">averagejoematt</text>
  <text x="1160" y="44" font-family="${MONO}" font-size="12" fill="${C.faint}" text-anchor="end" letter-spacing="2">THE MEASURED LIFE</text>

  <!-- the platform instrument mark (top-right) -->
  ${instrumentMark(1090, 165, 46)}
  <text x="1090" y="240" font-family="${MONO}" font-size="11" fill="${C.faint}" text-anchor="middle" letter-spacing="2">N=1</text>

  <!-- headline (serif = the human voice) -->
  <text x="40" y="150" font-family="${SERIF}" font-size="80" font-weight="600" fill="${C.ink}" letter-spacing="-1">302 &#8594; ${weight}</text>
  <text x="40" y="192" font-family="${MONO}" font-size="16" fill="${C.muted}" letter-spacing="1">${lost} LBS LOST  ·  ${progress}% TO GOAL  ·  DAY ${daysIn}</text>

  <!-- progress -->
  <g transform="translate(40, 214)">${progressBar(progressNum, 700, 10)}</g>
  <text x="40" y="248" font-family="${MONO}" font-size="11" fill="${C.faint}">0</text>
  <text x="740" y="248" font-family="${MONO}" font-size="11" fill="${C.ember}" text-anchor="end">185 lbs</text>

  <!-- live vitals -->
  ${card(40, 'HRV', hrv, 'ms · 30d avg')}
  ${card(280, 'RECOVERY', recovery, '% · today')}
  ${card(520, 'STREAK', streak, 'days · T0 habits')}

  <!-- right rail: what it is -->
  <line x1="800" y1="270" x2="800" y2="540" stroke="${C.raised}" stroke-width="1"/>
  <text x="840" y="300" font-family="${MONO}" font-size="11" fill="${C.faint}" letter-spacing="2">THE WAGER</text>
  <text x="840" y="346" font-family="${SERIF}" font-size="30" font-weight="600" fill="${C.ink}">Numbers <tspan font-style="italic">and</tspan></text>
  <text x="840" y="384" font-family="${SERIF}" font-size="30" font-weight="600" fill="${C.ink}">meaning, kept</text>
  <text x="840" y="422" font-family="${SERIF}" font-size="30" font-weight="600" fill="${C.ember}">personal.</text>
  <text x="840" y="474" font-family="${MONO}" font-size="13" fill="${C.muted}">A board of AI experts reads</text>
  <text x="840" y="496" font-family="${MONO}" font-size="13" fill="${C.muted}">one real life. The anti-Blueprint.</text>

  <!-- bottom tagline -->
  <rect x="0" y="560" width="1200" height="70" fill="${C.surface}"/>
  <text x="40" y="595" font-family="${SERIF}" font-size="17" font-style="italic" fill="${C.ink}">Built by a non-engineer, with Claude.</text>
  <text x="40" y="617" font-family="${MONO}" font-size="12" fill="${C.faint}" letter-spacing="1">Every failure included · every number public</text>
</svg>`;
}

export const handler = async (event) => {
  // Support both API Gateway and Function URL events
  const method = (
    event?.requestContext?.http?.method ||
    event?.httpMethod ||
    'GET'
  ).toUpperCase();

  if (method === 'OPTIONS') {
    return {
      statusCode: 200,
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: '',
    };
  }

  const stats = await getStats();
  const svg = buildSvg(stats);

  return {
    statusCode: 200,
    headers: {
      'Content-Type': 'image/svg+xml',
      'Cache-Control': 'public, max-age=3600, s-maxage=3600',
      'Access-Control-Allow-Origin': '*',
    },
    body: svg,
  };
};

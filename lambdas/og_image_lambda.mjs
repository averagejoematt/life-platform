/**
 * og-image Lambda (us-east-1)
 * 
 * GET /og — Returns a dynamically-generated SVG social preview image
 * with live stats baked in from public_stats.json on S3.
 * 
 * CloudFront behavior: /og → this Lambda, Cache TTL 3600s (1hr)
 * OG image tag on site: <meta property="og:image" content="https://averagejoematt.com/og">
 * 
 * DEPLOY:
 *   1. Create Lambda: life-platform-og-image (us-east-1, Node 20, 256MB, 10s timeout)
 *   2. Add Function URL (AuthType NONE)
 *   3. Add S3:GetObject permission on matthew-life-platform/site/data/public_stats.json
 *   4. Add CloudFront behavior: /og → this Lambda's Function URL
 *   5. Update OG meta tags on all pages to use /og instead of /assets/images/og-image.png
 * 
 * v1.0.0 — 2026-03-18 (WR-17)
 */

import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';

const s3 = new S3Client({ region: 'us-west-2' });
const BUCKET = 'matthew-life-platform';
const KEY = 'site/data/public_stats.json';

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

function progressBar(pct, width = 200, height = 8) {
  const fill = Math.max(0, Math.min(100, pct || 0));
  const fillWidth = Math.round(width * fill / 100);
  return `
    <rect x="0" y="0" width="${width}" height="${height}" rx="2" fill="#1a2330"/>
    <rect x="0" y="0" width="${fillWidth}" height="${height}" rx="2" fill="#58a6ff"/>
  `;
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

  return `<svg width="1200" height="630" viewBox="0 0 1200 630" xmlns="http://www.w3.org/2000/svg">
  <!-- Background -->
  <rect width="1200" height="630" fill="#0d1117"/>

  <!-- Left accent bar -->
  <rect x="0" y="0" width="4" height="630" fill="#58a6ff"/>

  <!-- Grid lines (subtle) -->
  <line x1="0" y1="210" x2="1200" y2="210" stroke="#1a2330" stroke-width="1"/>
  <line x1="0" y1="420" x2="1200" y2="420" stroke="#1a2330" stroke-width="1"/>
  <line x1="400" y1="0" x2="400" y2="630" stroke="#1a2330" stroke-width="1"/>
  <line x1="800" y1="0" x2="800" y2="630" stroke="#1a2330" stroke-width="1"/>

  <!-- Top bar -->
  <rect x="0" y="0" width="1200" height="70" fill="#0a0e14"/>
  <text x="40" y="44" font-family="monospace" font-size="13" fill="#484f58" letter-spacing="2">AVERAGEJOEMATT.COM</text>
  <text x="1160" y="44" font-family="monospace" font-size="13" fill="#484f58" text-anchor="end" letter-spacing="2">// LIVE DATA</text>
  <rect x="1120" y="28" width="8" height="8" rx="4" fill="#3fb950">
    <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite"/>
  </rect>

  <!-- Main headline -->
  <text x="40" y="140" font-family="Arial Black, sans-serif" font-size="72" font-weight="900" fill="#e6edf3" letter-spacing="-2">
    302 → ${weight}
  </text>
  <text x="40" y="185" font-family="monospace" font-size="16" fill="#8b949e" letter-spacing="1">
    LBS LOST: ${lost}  ·  ${progress}% TO GOAL  ·  DAY ${daysIn}
  </text>

  <!-- Progress bar -->
  <g transform="translate(40, 205)">
    ${progressBar(progressNum, 520, 10)}
  </g>
  <text x="40" y="238" font-family="monospace" font-size="11" fill="#58a6ff">0</text>
  <text x="560" y="238" font-family="monospace" font-size="11" fill="#58a6ff" text-anchor="end">185 lbs</text>

  <!-- Stat cards -->
  <!-- HRV -->
  <rect x="40" y="270" width="220" height="110" fill="#0d1f2d" rx="4"/>
  <rect x="40" y="270" width="220" height="3" fill="#58a6ff" rx="2"/>
  <text x="60" y="298" font-family="monospace" font-size="10" fill="#484f58" letter-spacing="2">HRV</text>
  <text x="60" y="348" font-family="Arial Black, sans-serif" font-size="48" font-weight="900" fill="#58a6ff">${hrv}</text>
  <text x="60" y="372" font-family="monospace" font-size="11" fill="#484f58">ms · 30d avg</text>

  <!-- Recovery -->
  <rect x="280" y="270" width="220" height="110" fill="#0d1f2d" rx="4"/>
  <rect x="280" y="270" width="220" height="3" fill="#3fb950" rx="2"/>
  <text x="300" y="298" font-family="monospace" font-size="10" fill="#484f58" letter-spacing="2">RECOVERY</text>
  <text x="300" y="348" font-family="Arial Black, sans-serif" font-size="48" font-weight="900" fill="#3fb950">${recovery}</text>
  <text x="300" y="372" font-family="monospace" font-size="11" fill="#484f58">% · today</text>

  <!-- Streak -->
  <rect x="520" y="270" width="220" height="110" fill="#0d1f2d" rx="4"/>
  <rect x="520" y="270" width="220" height="3" fill="#f0883e" rx="2"/>
  <text x="540" y="298" font-family="monospace" font-size="10" fill="#484f58" letter-spacing="2">STREAK</text>
  <text x="540" y="348" font-family="Arial Black, sans-serif" font-size="48" font-weight="900" fill="#f0883e">${streak}</text>
  <text x="540" y="372" font-family="monospace" font-size="11" fill="#484f58">days · T0 habits</text>

  <!-- Right panel: Platform stats -->
  <rect x="800" y="70" width="400" height="560" fill="#0a0e14"/>
  <text x="860" y="130" font-family="monospace" font-size="11" fill="#484f58" letter-spacing="2">// THE PLATFORM</text>

  <text x="860" y="200" font-family="Arial Black, sans-serif" font-size="52" font-weight="900" fill="#e6edf3">95</text>
  <text x="860" y="228" font-family="monospace" font-size="12" fill="#8b949e">AI INTELLIGENCE TOOLS</text>

  <text x="860" y="300" font-family="Arial Black, sans-serif" font-size="52" font-weight="900" fill="#e6edf3">19</text>
  <text x="860" y="328" font-family="monospace" font-size="12" fill="#8b949e">LIVE DATA SOURCES</text>

  <text x="860" y="400" font-family="Arial Black, sans-serif" font-size="52" font-weight="900" fill="#e6edf3">A</text>
  <text x="860" y="428" font-family="monospace" font-size="12" fill="#8b949e">ARCHITECTURE GRADE (R16)</text>

  <text x="860" y="500" font-family="Arial Black, sans-serif" font-size="52" font-weight="900" fill="#e6edf3">$13</text>
  <text x="860" y="528" font-family="monospace" font-size="12" fill="#8b949e">/ MONTH ON AWS</text>

  <!-- Bottom tagline -->
  <rect x="0" y="560" width="800" height="70" fill="#0a0e14"/>
  <text x="40" y="602" font-family="monospace" font-size="14" fill="#58a6ff" letter-spacing="1">Built by a non-engineer with Claude.</text>
  <text x="40" y="622" font-family="monospace" font-size="12" fill="#484f58">Every failure included. Every number public.</text>
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

/**
 * DPR-1 Phase 2 — Remaining Sections Capture
 * 
 * Captures: The Practice (6), The Platform (7), The Chronicle (5), Utility (8)
 * Total: 26 additional pages
 *
 * Usage:
 *   cd captures
 *   node capture-phase2.mjs
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';

const BASE = 'https://averagejoematt.com';

const PAGES = [
  // THE PRACTICE
  { slug: 'stack',          path: '/stack/',          label: 'The Stack' },
  { slug: 'protocols',      path: '/protocols/',      label: 'Protocols' },
  { slug: 'supplements',    path: '/supplements/',    label: 'Supplements' },
  { slug: 'experiments',    path: '/experiments/',    label: 'Experiments' },
  { slug: 'challenges',     path: '/challenges/',     label: 'Challenges' },
  { slug: 'discoveries',    path: '/discoveries/',    label: 'Discoveries' },

  // THE PLATFORM
  { slug: 'platform',       path: '/platform/',       label: 'How It Works' },
  { slug: 'intelligence',   path: '/intelligence/',   label: 'The AI' },
  { slug: 'board',          path: '/board/',          label: 'AI Board' },
  { slug: 'methodology',    path: '/methodology/',    label: 'Methodology' },
  { slug: 'cost',           path: '/cost/',           label: 'Cost' },
  { slug: 'tools',          path: '/tools/',          label: 'Tools' },
  { slug: 'builders',       path: '/builders/',       label: 'For Builders' },

  // THE CHRONICLE
  { slug: 'chronicle',      path: '/chronicle/',      label: 'Chronicle' },
  { slug: 'weekly',         path: '/weekly/',         label: 'Weekly Snapshots' },
  { slug: 'recap',          path: '/recap/',          label: 'Weekly Recap' },
  { slug: 'ask',            path: '/ask/',            label: 'Ask the Data' },
  { slug: 'subscribe',      path: '/subscribe/',      label: 'Subscribe' },

  // UTILITY
  { slug: 'status',         path: '/status/',         label: 'Status' },
  { slug: 'privacy',        path: '/privacy/',        label: 'Privacy' },
  { slug: 'community',      path: '/community/',      label: 'Community' },
  { slug: 'start',          path: '/start/',          label: 'Start' },
  { slug: 'kitchen',        path: '/kitchen/',        label: 'Kitchen' },
  { slug: 'ledger',         path: '/ledger/',         label: 'Ledger' },
  { slug: 'elena',          path: '/elena/',          label: 'Elena' },
  { slug: '404',            path: '/404',             label: '404' },
];

const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const RENDER_SETTLE_MS = 4000;
const SLOW_PAGES = new Set(['chronicle', 'weekly', 'recap', 'protocols', 'supplements', 'intelligence', 'platform']);
const SLOW_EXTRA_MS = 3000;

async function autoScroll(page) {
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let totalHeight = 0;
      const distance = 400;
      const timer = setInterval(() => {
        const scrollHeight = document.body.scrollHeight;
        window.scrollBy(0, distance);
        totalHeight += distance;
        if (totalHeight >= scrollHeight) {
          clearInterval(timer);
          resolve();
        }
      }, 150);
    });
  });
}

async function capturePage(page, pageInfo, outDir) {
  const url = `${BASE}${pageInfo.path}`;
  console.log(`  → ${pageInfo.label} (${url})`);

  await page.setViewportSize(DESKTOP_VIEWPORT);

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) {
    try {
      await page.goto(url, { waitUntil: 'load', timeout: 20000 });
    } catch (e2) {
      console.log(`    ✗ Failed: ${e2.message}`);
      writeFileSync(join(outDir, `${pageInfo.slug}.txt`), `FAILED TO LOAD: ${e2.message}`);
      return;
    }
  }

  await page.waitForTimeout(RENDER_SETTLE_MS);
  if (SLOW_PAGES.has(pageInfo.slug)) await page.waitForTimeout(SLOW_EXTRA_MS);

  await autoScroll(page);
  await page.waitForTimeout(1500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);

  await page.screenshot({ path: join(outDir, `${pageInfo.slug}.png`), fullPage: true, type: 'png' });

  const visibleText = await page.evaluate(() => document.body.innerText);
  const textPath = join(outDir, `${pageInfo.slug}.txt`);
  writeFileSync(textPath, `PAGE: ${url}\nCAPTURED: ${new Date().toISOString()}\nVIEWPORT: ${DESKTOP_VIEWPORT.width}x${DESKTOP_VIEWPORT.height}\n${'='.repeat(80)}\n\n${visibleText}`);
  console.log(`    ✓ ${visibleText.length} chars`);
}

async function main() {
  const outDir = join(process.cwd(), 'desktop');
  mkdirSync(outDir, { recursive: true });

  console.log('🔍 DPR-1 Phase 2 — Remaining Sections');
  console.log(`   Pages: ${PAGES.length}\n`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    colorScheme: 'dark',
  });
  const page = await context.newPage();

  for (const pageInfo of PAGES) {
    await capturePage(page, pageInfo, outDir);
  }

  await browser.close();
  console.log(`\n✅ Done! ${PAGES.length} pages captured to desktop/`);
}

main().catch(err => { console.error('Fatal:', err); process.exit(1); });

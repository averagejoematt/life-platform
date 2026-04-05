/**
 * DPR-1 Page Capture Script
 * 
 * Captures full-page screenshots + rendered text for every page
 * in the Deep Page Review scope. Waits for API data to hydrate
 * before capturing so we see what a real visitor sees.
 *
 * Usage:
 *   cd captures
 *   npm install
 *   npx playwright install chromium
 *   node capture.mjs
 *
 * Output:
 *   captures/desktop/{page-name}.png     — full-page desktop screenshot
 *   captures/desktop/{page-name}.txt     — all visible text after hydration
 *   captures/mobile/{page-name}.png      — full-page mobile screenshot
 *   captures/mobile/{page-name}.txt      — mobile visible text
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';

const BASE = 'https://averagejoematt.com';

// All 13 pages for DPR-1 scope (Pulse + Data sections)
const PAGES = [
  // THE PULSE
  { slug: 'live',            path: '/live/',            label: 'The Pulse (Today)' },
  { slug: 'character',       path: '/character/',       label: 'The Score (Character)' },
  { slug: 'habits',          path: '/habits/',          label: 'Habits' },
  { slug: 'accountability',  path: '/accountability/',  label: 'Accountability' },
  // THE DATA (observatory pages)
  { slug: 'sleep',           path: '/sleep/',           label: 'Sleep Observatory' },
  { slug: 'glucose',         path: '/glucose/',         label: 'Glucose Observatory' },
  { slug: 'nutrition',       path: '/nutrition/',       label: 'Nutrition Observatory' },
  { slug: 'training',        path: '/training/',        label: 'Training Observatory' },
  { slug: 'physical',        path: '/physical/',        label: 'Physical Observatory' },
  { slug: 'mind',            path: '/mind/',            label: 'Inner Life (Mind)' },
  { slug: 'labs',            path: '/labs/',            label: 'Labs' },
  { slug: 'benchmarks',      path: '/benchmarks/',      label: 'Benchmarks' },
  { slug: 'explorer',        path: '/explorer/',        label: 'Data Explorer' },
];

const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const MOBILE_VIEWPORT  = { width: 390, height: 844 };  // iPhone 14

// How long to wait after network idle for JS to finish rendering
const RENDER_SETTLE_MS = 4000;

// Extra wait for pages known to have slow API calls
const SLOW_PAGES = new Set(['character', 'habits', 'nutrition', 'training', 'sleep', 'glucose', 'mind']);
const SLOW_EXTRA_MS = 3000;

async function capturePage(page, pageInfo, viewport, outDir) {
  const url = `${BASE}${pageInfo.path}`;
  console.log(`  → ${url} (${viewport.width}px)`);

  await page.setViewportSize(viewport);
  
  try {
    // Navigate and wait for network to settle
    await page.goto(url, { 
      waitUntil: 'networkidle',
      timeout: 30000 
    });
  } catch (e) {
    // networkidle can timeout on pages with polling — fall back to load
    console.log(`    ⚠ networkidle timeout, falling back to load event`);
    try {
      await page.goto(url, { waitUntil: 'load', timeout: 20000 });
    } catch (e2) {
      console.log(`    ✗ Failed to load: ${e2.message}`);
      writeFileSync(join(outDir, `${pageInfo.slug}.txt`), `FAILED TO LOAD: ${e2.message}`);
      return;
    }
  }

  // Wait for JS to hydrate — skeleton screens to clear, API data to render
  await page.waitForTimeout(RENDER_SETTLE_MS);
  
  if (SLOW_PAGES.has(pageInfo.slug)) {
    await page.waitForTimeout(SLOW_EXTRA_MS);
  }

  // Scroll to bottom to trigger any lazy-loaded content / reveal animations
  await autoScroll(page);
  await page.waitForTimeout(1500);

  // Scroll back to top for screenshot
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);

  // Full-page screenshot
  const screenshotPath = join(outDir, `${pageInfo.slug}.png`);
  await page.screenshot({ 
    path: screenshotPath, 
    fullPage: true,
    type: 'png'
  });
  console.log(`    ✓ Screenshot: ${screenshotPath}`);

  // Extract all visible text (what a human reads)
  const visibleText = await page.evaluate(() => {
    // Get innerText which respects visibility and CSS display
    return document.body.innerText;
  });

  const textPath = join(outDir, `${pageInfo.slug}.txt`);
  writeFileSync(textPath, `PAGE: ${url}\nCAPTURED: ${new Date().toISOString()}\nVIEWPORT: ${viewport.width}x${viewport.height}\n${'='.repeat(80)}\n\n${visibleText}`);
  console.log(`    ✓ Text: ${textPath} (${visibleText.length} chars)`);
}

// Scroll page to trigger lazy content
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

async function main() {
  // Create output directories
  const desktopDir = join(process.cwd(), 'desktop');
  const mobileDir  = join(process.cwd(), 'mobile');
  mkdirSync(desktopDir, { recursive: true });
  mkdirSync(mobileDir, { recursive: true });

  console.log('🔍 DPR-1 Page Capture');
  console.log(`   Base URL: ${BASE}`);
  console.log(`   Pages: ${PAGES.length}`);
  console.log(`   Output: desktop/ and mobile/\n`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    // Emulate a real user agent
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    // Dark mode (matches the site's default)
    colorScheme: 'dark',
  });
  const page = await context.newPage();

  // Desktop captures
  console.log('━━━ DESKTOP (1440px) ━━━');
  for (const pageInfo of PAGES) {
    await capturePage(page, pageInfo, DESKTOP_VIEWPORT, desktopDir);
  }

  // Mobile captures
  console.log('\n━━━ MOBILE (390px) ━━━');
  for (const pageInfo of PAGES) {
    await capturePage(page, pageInfo, MOBILE_VIEWPORT, mobileDir);
  }

  await browser.close();

  console.log('\n✅ Done! Captures saved to:');
  console.log(`   Desktop: ${desktopDir}/`);
  console.log(`   Mobile:  ${mobileDir}/`);
  console.log('\nNext: Share the .txt files with Claude for the DPR-1 review.');
  console.log('Screenshots can be uploaded for visual review of specific pages.');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});

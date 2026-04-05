# Cross-Board Offsite — Technical Brief & Design Spec

**Date:** March 28, 2026 | **Version:** v4.3.1 | **Target:** April 1–14 execution window
**Author:** Product Board + Technical Board + Personal Board (unified offsite output)
**Audience:** Claude Code — execute items in order, one per session unless noted

---

## How to Use This Document

Each item below is a self-contained work order. Read the item, execute it, update CHANGELOG.md, and commit. Items are ordered by priority. Items #1 and #9 can be done in the same session. Item #2 is a standalone infrastructure session. Items #5 and #6 can be combined. Item #7 is a standalone migration. Item #8 is a standalone design session.

**Before starting any item:** Read `handovers/HANDOVER_LATEST.md` for current state.
**After completing any item:** Follow the standard session-end ritual (sync_doc_metadata, handover, changelog, commit).

---

## Item #1 — Sleep & Glucose Observatory Visual Overhaul

### Context

The Training, Nutrition, and Inner Life (Mind) observatory pages use a mature editorial design pattern. Sleep and Glucose pages use an older pattern. Both need to be brought to parity.

### Reference Implementation

**Use `site/training/index.html` as the canonical reference.** The Training page (crimson theme) is the most complete implementation of the editorial observatory pattern. The Nutrition page (amber theme) is also a valid reference.

### Design Pattern — What Makes the New Observatory Pages Different

The editorial observatory pattern has these components in order:

1. **Two-column editorial hero** — Left column: observatory title in display font, one-line thesis (italic serif), and a provocation or key stat. Right column: animated SVG gauge ring(s) showing the headline metric with a numeric readout. Full-width bottom border.

2. **Staggered pull-quotes with evidence badges** — Alternating left-offset and right-offset block quotes in serif font. Each has:
   - A watermark character (large, faint, top-right)
   - The quote text (serif, ~20px, line-height 1.6)
   - Attribution line with board member name + emoji
   - Evidence badge: `N=1 · [SOURCE]-confirmed` in a small pill (monospace, uppercase, colored left-border)
   - Pull-quotes are separated by `border-bottom: 1px solid var(--border)`

3. **Monospace section headers with trailing em-dashes** — `font-family: var(--font-mono)`, `font-size: var(--text-2xs)`, uppercase, letter-spacing 0.15em. The `::after` pseudo-element adds `——` in faint text.

4. **Three-column editorial data spread** — A grid of three stat cards, each with: monospace label (faint, uppercase), large numeric value, and a trend indicator or secondary line. Cards separated by vertical borders.

5. **Left-accent bordered rule cards** — Content cards with a 3px colored left border, containing structured data (e.g., protocol summaries, experiment results, board commentary). Background is `var(--surface)`.

6. **Board commentary section** — One or more board member quotes in the pull-quote style, specific to the observatory domain.

### Sleep Observatory Specifics

**Theme color:** `--s-blue: #60a5fa` (blue) — already defined in the existing page
**Board member:** Dr. Lisa Park 😴
**Hero gauge metric:** Sleep Efficiency % (or Sleep Score)
**Evidence badge source:** `Whoop-verified` or `Eight Sleep-confirmed`
**Data spread metrics:** Average sleep hours, REM %, Deep %, Sleep Efficiency
**Pull-quote topics:** Architecture vs. duration, circadian consistency, bed temperature optimization
**API endpoint:** Uses existing `/api/vitals` for sleep data and can use `public_stats.json` for pre-computed values

**Key content sections to build:**
- Hero with sleep efficiency gauge ring
- "The Architecture Thesis" pull-quote (Lisa Park on architecture > duration)
- Sleep staging breakdown (3-column: REM%, Deep%, Light%)
- Eight Sleep × Whoop cross-reference section (data spread)
- Circadian consistency section (weekday vs weekend variance)
- Board commentary (Lisa Park + Huberman/Nakamura on protocols)
- Subscribe CTA (see Item #6)

### Glucose Observatory Specifics

**Theme color:** `--g-teal: #2dd4bf` (teal) — already defined in the existing page
**Board member:** Dr. Victor Reyes 📊 (fictional replacement for Attia)
**Hero gauge metric:** Time in Range % (70-140 mg/dL)
**Evidence badge source:** `CGM-confirmed`
**Data spread metrics:** Average glucose, Time in Range %, Coefficient of Variation, Fasting glucose
**Pull-quote topics:** Metabolic flexibility, meal response patterns, glucose variability
**API endpoint:** `/api/vitals` and `public_stats.json`

**Key content sections to build:**
- Hero with time-in-range gauge ring
- "The Metabolic Thesis" pull-quote (Reyes on glucose variability as leading indicator)
- Core metrics (3-column: Avg glucose, TIR%, CV%)
- Meal response patterns section (if data available from CGM tools)
- Board commentary (Reyes + Rhonda Patrick on genomic context)
- Subscribe CTA

### Implementation Steps

```
1. Copy site/training/index.html → working copy
2. Strip training-specific content, keep editorial structure
3. For Sleep:
   a. Replace CSS custom properties (--t-* → --s-*)
   b. Replace crimson color values with blue (#60a5fa family)
   c. Update hero content: title, thesis, gauge metric
   d. Write 2-3 pull-quotes using Lisa Park voice (see board config)
   e. Build 3-column data spread with sleep metrics
   f. Add board commentary section
   g. Ensure components.js placeholders present (nav, footer, subscribe, bottom-nav)
   h. Save to site/sleep/index.html (overwrite existing)
4. Repeat for Glucose with teal theme and Victor Reyes voice
5. Deploy: bash deploy/deploy_site.sh
6. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/sleep/*" "/glucose/*"
```

### CSS Pattern Reference

The observatory-specific CSS should be self-contained in a `<style>` block in the page `<head>`. Key patterns to replicate from training:

- `.t-section-header` → `.s-section-header` (sleep) / `.g-section-header` (glucose)
- `.t-pullquote`, `.t-pullquote--left`, `.t-pullquote--right`
- `.t-pullquote__watermark`, `.t-pullquote__text`, `.t-pullquote__attr`
- `.t-pullquote__badge` (the evidence badge pill)
- `.t-hero` (two-column hero grid)
- `.t-data-spread` (three-column metric grid)
- `.t-rule-card` (left-accent bordered cards)

All of these are prefixed per-observatory (`.t-` for training, `.s-` for sleep, `.g-` for glucose). The structural CSS is identical; only color values change.

### Acceptance Criteria

- [ ] Sleep page matches Training page editorial structure (hero, pull-quotes, data spread, rule cards)
- [ ] Gauge ring animates on load with correct metric
- [ ] Evidence badges use correct source labels
- [ ] Pull-quotes use Lisa Park / Kai Nakamura voice from board config
- [ ] Subscribe CTA present (see Item #6)
- [ ] Responsive: graceful collapse on mobile (single column)
- [ ] Dark mode works (uses CSS custom properties)
- [ ] Same checks for Glucose page with teal theme and appropriate board voices

---

## Item #2 — CDK Adoption for CLI-Created Lambdas (R18-F02)

### Context

During the v3.7.82 → v4.3.0 pre-launch sprint, at least 6 Lambdas were created via AWS CLI outside CDK management. They don't get IAM role management, EventBridge rules, alarm creation, or layer attachment through the pipeline. Past incidents (Mar 12 Todoist, Mar 11 Brittany email) were caused by this exact pattern.

### Current CDK Stacks

Located in `cdk/stacks/`:

| Stack | Purpose | File |
|-------|---------|------|
| `core_stack.py` | DynamoDB, S3, base IAM | `core_stack.py` |
| `ingestion_stack.py` | Data source Lambdas (Whoop, Strava, etc.) | `ingestion_stack.py` |
| `compute_stack.py` | Daily compute Lambdas | `compute_stack.py` |
| `email_stack.py` | Digest/brief/notification Lambdas | `email_stack.py` |
| `operational_stack.py` | Ops Lambdas (freshness, canary, etc.) | `operational_stack.py` |
| `mcp_stack.py` | MCP server Lambda | `mcp_stack.py` |
| `web_stack.py` | Site-api, CloudFront | `web_stack.py` |
| `monitoring_stack.py` | Alarms, dashboards | `monitoring_stack.py` |

### Lambdas to Adopt

Run this audit first to identify all CLI-created Lambdas:

```bash
# List all Lambdas not in CDK stacks
aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text --no-cli-pager
# Cross-reference against cdk/stacks/*.py to find unmanaged ones
```

**Known CLI-created Lambdas (from R18 findings):**

| Lambda | Created | Correct Stack | Needs |
|--------|---------|---------------|-------|
| `og-image-generator` | Pre-launch sprint | `operational_stack.py` | EventBridge cron, layer, alarm |
| `food-delivery-ingestion` | Pre-launch sprint | `ingestion_stack.py` | S3 trigger, layer, alarm |
| `challenge-generator` | Pre-launch sprint | `compute_stack.py` | EventBridge cron, layer, alarm |
| `email-subscriber` | Pre-launch sprint | `web_stack.py` | Function URL, layer, alarm |

There may be additional ones — the audit step will reveal them.

### Implementation Steps

```
1. Run audit:
   aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text --no-cli-pager
   Compare against all Lambda names in cdk/stacks/*.py

2. For each unmanaged Lambda:
   a. Read its current config:
      aws lambda get-function-configuration --function-name NAME --region us-west-2 --no-cli-pager
   b. Note: runtime, handler, memory, timeout, env vars, layers, IAM role, triggers
   c. Add to appropriate CDK stack using the existing lambda_helpers.py patterns
   d. Create import map entry (see existing *-import-map.json files in cdk/)

3. Import existing resources into CDK (don't recreate):
   # For each Lambda:
   # Add to stack code with exact current configuration
   # Then import:
   npx cdk import STACK_NAME --region us-west-2

4. Verify: npx cdk diff --region us-west-2
   Should show zero unmanaged Lambdas

5. Update lambda_map.json with any missing entries (R18-F03)
   - Verify every .py file in lambdas/ has a corresponding lambda_map entry
   - Add CI check if not already present

6. Update ARCHITECTURE.md and INFRASTRUCTURE.md with correct Lambda count
```

### Critical Rules

- **Never recreate** a Lambda that has existing EventBridge rules, DynamoDB triggers, or S3 triggers — use `cdk import`
- **Match exact configuration** — don't change runtime, memory, timeout, or env vars during adoption
- **Shared layer:** Check current version of `life-platform-shared-utils` and attach to all adopted Lambdas
- **Test after import:** Invoke each adopted Lambda with a test event to confirm it still works

### Acceptance Criteria

- [ ] `npx cdk diff` shows zero drift for all adopted Lambdas
- [ ] `lambda_map.json` has entries for all Lambdas in `lambdas/` directory
- [ ] CI pipeline (`ci-cd.yml`) will detect changes to adopted Lambda source files
- [ ] ARCHITECTURE.md and INFRASTRUCTURE.md updated with accurate Lambda count
- [ ] All adopted Lambdas have CloudWatch error alarms (can combine with Item #9)

---

## Item #5 — HP-13: Share Cards + Dynamic OG Images

### Context

The `og_image_lambda.py` already exists and generates 6 data-driven OG images daily (home, sleep, glucose, training, character, nutrition). The gap is:

1. Not all shareable pages have dedicated OG images (chronicle, weekly snapshots, experiments, discoveries, labs, mind)
2. The `<meta property="og:image">` tags on some pages point to generic images or are missing
3. No per-chronicle-installment OG images

### Existing Infrastructure

- **Lambda:** `og_image_lambda.py` in `lambdas/`
- **Fonts:** `lambdas/fonts/` (bebas-neue-400.ttf, space-mono-400.ttf, space-mono-700.ttf)
- **Output:** `s3://matthew-life-platform/site/assets/images/og-*.png`
- **Trigger:** EventBridge daily at 11:30 AM PT (19:30 UTC)
- **Data source:** `public_stats.json` from S3
- **Current images generated:** og-home.png, og-sleep.png, og-glucose.png, og-training.png, og-character.png, og-nutrition.png

### New OG Images to Add

| Image | Data Source | Key Content |
|-------|-----------|-------------|
| `og-mind.png` | public_stats.json | Mind pillar score, journal streak, social connection metric |
| `og-labs.png` | public_stats.json | Biomarker count, last draw date, key metric |
| `og-chronicle.png` | Generic for /chronicle/ index | "The Measured Life" + latest installment title |
| `og-weekly.png` | public_stats.json | Latest week number, weight, character level |
| `og-experiments.png` | public_stats.json | Active experiments count, completed count |
| `og-builders.png` | Static | Lambda count, tool count, data source count, cost |

### Implementation Steps

```
1. Open lambdas/og_image_lambda.py
2. Add new image generation functions following the existing pattern:
   - Each function reads from public_stats.json
   - Uses the same design tokens (BG, TEXT, MUTED, GREEN, etc.)
   - Generates 1200x630 PNG
   - Uploads to s3://matthew-life-platform/site/assets/images/
3. Update the Lambda handler to call all new generators
4. Update meta tags on all pages that need them:
   - site/mind/index.html → og-mind.png
   - site/labs/index.html → og-labs.png
   - site/chronicle/index.html → og-chronicle.png
   - site/weekly/index.html → og-weekly.png
   - site/experiments/index.html → og-experiments.png
   - site/builders/index.html → og-builders.png (when built)
5. Deploy Lambda: bash deploy/deploy_lambda.sh og-image-generator
6. Invoke once to generate initial images:
   aws lambda invoke --function-name og-image-generator --payload '{}' --region us-west-2 /dev/null --no-cli-pager
7. Deploy site with updated meta tags: bash deploy/deploy_site.sh
8. Invalidate CloudFront: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/images/og-*"
```

### OG Image Design Spec

All OG images follow this layout (matching existing pattern in og_image_lambda.py):

```
┌──────────────────────────────────────────────┐
│ [3px green accent bar at top]                │
│                                              │
│  OBSERVATORY NAME          (Bebas Neue, 48px)│
│  ─────────────────                           │
│  Key Metric: VALUE         (Space Mono, 36px)│
│  Secondary: value          (Space Mono, 18px)│
│  Third: value              (Space Mono, 18px)│
│                                              │
│  averagejoematt.com        (faint, bottom-left)
│ [green accent bar at bottom]                 │
└──────────────────────────────────────────────┘
```

- Background: `#080c0a`
- Accent: `#22c55e`
- Text: `#e8f0e8`
- Muted: `#8aaa90`

### Acceptance Criteria

- [ ] All observatory pages have dedicated, data-driven OG images
- [ ] Chronicle index page has OG image
- [ ] Weekly snapshot page has OG image
- [ ] All `<meta property="og:image">` tags point to correct images
- [ ] Twitter card meta tags present (`twitter:card`, `twitter:image`)
- [ ] Images generate successfully on Lambda invocation
- [ ] Images are 1200×630px PNG

---

## Item #6 — Subscribe CTA Consistency + Email Funnel Optimization

### Context

The `components.js` system already injects a subscribe CTA via the `<div id="amj-subscribe"></div>` placeholder. The issue is that not all pages include this placeholder, and the CTA copy is generic across all pages.

### Current State

- `components.js` handles nav, footer, subscribe CTA, and bottom-nav injection
- Subscribe endpoint: `/api/subscribe` (handled by `email-subscriber` Lambda)
- SES in production mode
- Confirmation flow exists

### Audit Task

First, audit which pages have the subscribe placeholder and which don't:

```bash
# On Matthew's machine, from project root:
grep -rL 'amj-subscribe' site/*/index.html | sort
# This lists pages MISSING the subscribe CTA
```

### Subscribe CTA Component Spec

The CTA should be contextual per observatory/section. Update `components.js` to detect the current page path and render section-specific copy:

```javascript
// In components.js, update the subscribe CTA function:
var subscribeCopy = {
  '/sleep/':       { hook: 'Get sleep intelligence weekly', sub: 'Real architecture data from Whoop × Eight Sleep. No sleep tips — sleep science.' },
  '/glucose/':     { hook: 'Get metabolic insights weekly', sub: 'CGM data, meal responses, and glucose patterns. What your metabolism is actually doing.' },
  '/nutrition/':   { hook: 'Get nutrition data weekly', sub: 'Macros, protein distribution, and adherence rates. The real food log.' },
  '/training/':    { hook: 'Get training intelligence weekly', sub: 'CTL, Zone 2, centenarian benchmarks. What training for longevity looks like.' },
  '/mind/':        { hook: 'Get inner life insights weekly', sub: 'Journal patterns, mood trajectories, and what the data says about the mind.' },
  '/chronicle/':   { hook: 'Follow the story weekly', sub: 'Elena Voss\'s embedded journalism on one person\'s health transformation.' },
  '/experiments/': { hook: 'Get experiment updates', sub: 'N=1 results as they happen. What worked, what didn\'t, and what\'s next.' },
  'default':       { hook: 'Follow the experiment', sub: 'Weekly data from 25 sources. Real numbers, no highlight reel.' }
};
```

### Implementation Steps

```
1. Audit all pages for amj-subscribe placeholder (see bash command above)
2. Add <div id="amj-subscribe"></div> to every page missing it
   - Place it BEFORE the footer placeholder
   - Place it AFTER the main content area
3. Update components.js with contextual subscribe copy (see spec above)
4. Add mid-article CTA for Chronicle pages:
   - In chronicle post template, add a subtle inline CTA after ~60% of content
   - Style: left-border accent, italic text, email input inline
5. Verify subscribe flow end-to-end: submit email → SES confirmation → confirmed state
6. Deploy: bash deploy/deploy_site.sh
7. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
```

### Subscribe CTA Visual Spec

The CTA block should match the observatory design language:

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  FOLLOW THE EXPERIMENT ——                    (mono, faint)  │
│                                                             │
│  [Contextual hook line]                      (display, 24px)│
│  [Contextual sub line]                       (body, muted)  │
│                                                             │
│  ┌──────────────────────────────┐ ┌──────────┐             │
│  │  your@email.com              │ │ SUBSCRIBE│              │
│  └──────────────────────────────┘ └──────────┘             │
│                                                             │
│  No spam. Unsubscribe anytime.               (2xs, faint)  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- Uses the monospace section header pattern (`.x-section-header::after { content: '——' }`)
- Input field: `background: var(--surface)`, `border: 1px solid var(--border)`
- Button: `background: var(--accent)` (#22c55e), dark text
- Section separated by `border-top` and `border-bottom`

### Acceptance Criteria

- [ ] Every page on the site has the subscribe CTA
- [ ] CTA copy is contextual per observatory/section
- [ ] Chronicle pages have mid-article inline CTA
- [ ] Subscribe form submits successfully
- [ ] Email confirmation flow works end-to-end
- [ ] CTA is responsive (stacks on mobile)

---

## Item #7 — Cross-Region Migration: site-api → us-west-2

### Context

The site-api Lambda (`life-platform-site-api`) currently runs in **us-east-1** while DynamoDB is in **us-west-2**. Every API call makes cross-region reads, adding ~60-80ms latency. With 8+ API endpoints added during the pre-launch sprint, this latency multiplies. The platform now has enough API surface area that this matters.

### Current State

- **Lambda:** `life-platform-site-api` in us-east-1
- **Function URL:** `https://lxhjl2qvq2ystwp47464uhs2ti0hpdcq.lambda-url.us-east-1.on.aws/`
- **DynamoDB:** `life-platform` table in us-west-2
- **CloudFront:** Distribution `E3S424OXQZ8NBE` points to the us-east-1 Function URL as origin
- **CDK:** `web_stack.py` manages the site-api Lambda

### Migration Plan

This is a blue-green migration — create the new Lambda in us-west-2, verify it works, then switch CloudFront origin.

```
1. AUDIT current Lambda configuration:
   aws lambda get-function-configuration \
     --function-name life-platform-site-api \
     --region us-east-1 --no-cli-pager
   # Note: runtime, handler, memory, timeout, env vars, layers, IAM role

2. CREATE new Lambda in us-west-2 with identical configuration:
   # Option A: Update CDK web_stack.py to target us-west-2, deploy
   # Option B: Manual creation + CDK import later
   # Recommend Option A — this is the whole point of Item #2

3. DEPLOY code to new Lambda:
   bash deploy/deploy_lambda.sh life-platform-site-api
   # Verify deploy_lambda.sh targets the correct region

4. CREATE Function URL for the new Lambda:
   aws lambda create-function-url-config \
     --function-name life-platform-site-api \
     --auth-type NONE \
     --region us-west-2 --no-cli-pager

5. TEST the new endpoint directly:
   curl -s "NEW_FUNCTION_URL/api/status/summary"
   curl -s "NEW_FUNCTION_URL/api/vitals"
   curl -s "NEW_FUNCTION_URL/api/journey"
   curl -s "NEW_FUNCTION_URL/api/character"
   # Verify all endpoints return valid data
   # Verify latency is lower (no cross-region DDB reads)

6. UPDATE CloudFront origin to point to new Function URL:
   # Get current distribution config:
   aws cloudfront get-distribution-config \
     --id E3S424OXQZ8NBE --no-cli-pager > /tmp/cf-config.json
   # Update the Origin DomainName from us-east-1 URL to us-west-2 URL
   # Update distribution:
   aws cloudfront update-distribution \
     --id E3S424OXQZ8NBE \
     --distribution-config FILE_WITH_UPDATED_ORIGIN \
     --if-match ETAG_FROM_GET --no-cli-pager

7. VERIFY via CloudFront:
   curl -s "https://averagejoematt.com/api/status/summary"
   # Confirm response comes from us-west-2 Lambda

8. CLEANUP: Delete or disable the us-east-1 Lambda after 24h burn-in

9. UPDATE docs:
   - ARCHITECTURE.md: site-api region → us-west-2
   - INFRASTRUCTURE.md: update Function URL
   - Memory: update AMJ SiteApi FunctionUrl
```

### Risk Mitigation

- **Rollback plan:** If the new Lambda fails, switch CloudFront origin back to us-east-1 Function URL. The old Lambda stays warm for 24h.
- **WAF:** The WAF is on CloudFront (us-east-1 scope for CloudFront), so it stays in place regardless of Lambda region.
- **CORS:** The site-api handles CORS via `CORS_HEADERS` dict + OPTIONS handler. Region change doesn't affect this.
- **Reserved concurrency:** Set on the new Lambda to match the old one (20).

### Acceptance Criteria

- [ ] `life-platform-site-api` running in us-west-2
- [ ] Function URL created and accessible
- [ ] All API endpoints return valid data via new Function URL
- [ ] CloudFront origin updated to us-west-2 Function URL
- [ ] P50 latency on `/api/ask` measurably lower
- [ ] Old us-east-1 Lambda disabled or deleted after 24h
- [ ] Docs updated with new region and Function URL

---

## Item #8 — Home Page Elevated to Observatory Design Standard

### Context

The home page (`site/index.html`) is the most-visited page but doesn't match the editorial design standard set by the newer observatory pages. It currently uses a functional but less distinctive layout (grid-based about section, source pills, sparklines). The goal is to apply the observatory editorial pattern so the home page feels like the same publication.

### Current Home Page Structure

```
1. Nav
2. About section (2-column grid: left=text, right=source pills)
3. Vital signs (4-quadrant grid: Body/Recovery/Behavior/Mind)
4. Day 1 vs Today comparison (4 dimensions)
5. Daily brief excerpt
6. Discoveries section
7. Transformation comparison card
8. What's new pulse section
9. Footer
```

### Target Home Page Structure (Observatory Pattern)

```
1. Nav
2. EDITORIAL HERO (2-column)
   Left: "The Measured Life" (display font), thesis line (italic serif),
         Day count + weight + character level as live stats
   Right: Animated SVG gauge ring — overall Character Level or composite score
3. PULL-QUOTE #1 — The Chair's latest verdict (staggered left)
4. MONOSPACE SECTION HEADER — "The experiment ——"
5. 3-COLUMN DATA SPREAD — Weight trajectory, Sleep avg, Habit score
6. PULL-QUOTE #2 — Elena Voss narrative excerpt (staggered right)
7. MONOSPACE SECTION HEADER — "Today's brief ——"
8. Daily brief excerpt (left-accent rule card)
9. MONOSPACE SECTION HEADER — "The evidence ——"
10. Observatory entry cards (5 cards: Sleep, Glucose, Nutrition, Training, Mind)
    Each card: colored left accent, observatory name, headline metric, → link
11. PULL-QUOTE #3 — Dr. Paul Conti or Coach Maya on the human dimension
12. Subscribe CTA (contextual, per Item #6)
13. Footer
```

### Design Decisions

- **Hero gauge:** Show overall Character Level (1-100) as the gauge ring. This is the single number that synthesizes all 7 pillars.
- **Color:** The home page uses the platform's primary accent green (`#22c55e`). No observatory-specific color — this is the hub.
- **Pull-quotes:** Use The Chair, Elena Voss, and one domain expert. These should feel like editorial selections, not a data dump.
- **Observatory entry cards:** These replace the current "vital signs" quadrant. Each card is a doorway to a deep-dive page. Use the observatory's theme color for the left accent border.
- **Data spread:** Keep it to 3 metrics. Less is more on the home page. Weight (the transformation anchor), Sleep (the universal entry point), Habits (the behavioral engine).

### Implementation Steps

```
1. Back up current home page:
   cp site/index.html site/index.html.bak

2. Restructure using the Training observatory page as structural reference
   - Keep the same CSS custom property pattern
   - Use --accent (#22c55e) as the home page theme color
   - Prefix CSS classes with .h- (for home)

3. Build the editorial hero:
   - Left column: "The Measured Life" in display font
   - Italic serif thesis: "One person. 25 data sources. An AI that reads everything."
   - Live stats: Day X · WEIGHT lbs · Level XX (fetched from /api/vitals and /api/character)
   - Right column: SVG gauge ring for Character Level

4. Build pull-quotes:
   - Quote #1: The Chair's verdict (write a representative quote about the experiment's purpose)
   - Quote #2: Elena Voss on the narrative (why this story matters)
   - Quote #3: Paul Conti on the inner dimension (what the data can't capture)

5. Build 3-column data spread:
   - Weight: current weight, change from start, trend arrow
   - Sleep: avg hours, avg efficiency, trend
   - Habits: T0 adherence %, composite score, trend

6. Build observatory entry cards (5 cards in a grid):
   - Each card: observatory name, theme color left border, headline metric, link
   - Sleep (blue), Glucose (teal), Nutrition (amber), Training (crimson), Mind (violet)

7. Keep existing API fetch logic for live data (vitals, journey, character endpoints)
   Update the DOM rendering to target new HTML structure

8. Add subscribe CTA placeholder: <div id="amj-subscribe"></div>

9. Ensure all components.js placeholders present

10. Deploy: bash deploy/deploy_site.sh
11. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/" "/index.html"
```

### Responsive Behavior

- Hero: 2-column → stacked (title above gauge) at `max-width: 900px`
- Data spread: 3-column → stacked at `max-width: 768px`
- Observatory cards: 5-column → 2-column + 1 at `max-width: 900px`, stacked at `max-width: 600px`
- Pull-quotes: reduce offset to 0 on mobile

### Acceptance Criteria

- [ ] Home page uses editorial observatory pattern (hero, pull-quotes, data spread, section headers)
- [ ] Gauge ring shows Character Level and animates on load
- [ ] Live data populates from existing API endpoints
- [ ] Observatory entry cards link to all 5 observatory pages with correct theme colors
- [ ] Pull-quotes from 3 different board members with evidence badges
- [ ] Subscribe CTA present
- [ ] Fully responsive (test at 1440px, 1024px, 768px, 375px)
- [ ] Dark mode works
- [ ] Page load time < 2s (no new API calls — reuse existing endpoints)

---

## Item #9 — Monitoring + Alarms for New Resources (R18-F04)

### Context

This is the simplest item — two deploy scripts already exist and just need to be run. They were created during the R18 remediation session but haven't been executed yet.

### Scripts to Run

**Script 1: CloudWatch Alarms for New Lambdas**
- File: `deploy/setup_r18_alarms.sh`
- Creates error alarms for: `og-image-generator`, `food-delivery-ingestion`, `challenge-generator`, `email-subscriber`
- SNS target: `arn:aws:sns:us-west-2:205930651321:life-platform-alerts`
- Idempotent: skips if alarm already exists

**Script 2: WAF Endpoint-Specific Rate Rules**
- File: `deploy/setup_waf_endpoint_rules.sh`
- Adds rate limits for: `/api/ask` (100/5min per IP), `/api/board_ask` (100/5min per IP)
- Region: us-east-1 (CloudFront scope)
- Idempotent: skips if AskRateLimit rule already exists

### Implementation Steps

```
1. Run alarm script:
   bash deploy/setup_r18_alarms.sh

2. Verify alarms exist:
   aws cloudwatch describe-alarms --alarm-name-prefix "og-image" --region us-west-2 --query 'MetricAlarms[].AlarmName' --output text --no-cli-pager
   aws cloudwatch describe-alarms --alarm-name-prefix "food-delivery" --region us-west-2 --query 'MetricAlarms[].AlarmName' --output text --no-cli-pager
   aws cloudwatch describe-alarms --alarm-name-prefix "challenge-generator" --region us-west-2 --query 'MetricAlarms[].AlarmName' --output text --no-cli-pager
   aws cloudwatch describe-alarms --alarm-name-prefix "email-subscriber" --region us-west-2 --query 'MetricAlarms[].AlarmName' --output text --no-cli-pager

3. Run WAF rules script:
   bash deploy/setup_waf_endpoint_rules.sh

4. Verify WAF rules:
   aws wafv2 get-web-acl --name life-platform-amj-waf --scope CLOUDFRONT --region us-east-1 --query 'WebACL.Rules[].Name' --output text --no-cli-pager
   # Should include: AskRateLimit, BoardAskRateLimit

5. Also check the freshness checker covers food delivery:
   # The freshness_checker_lambda.py should have food_delivery in its sources
   # Verify in the Lambda code or env vars
```

### Acceptance Criteria

- [ ] 4 new CloudWatch alarms exist and are in OK state
- [ ] AskRateLimit WAF rule active (100/5min on /api/ask*)
- [ ] BoardAskRateLimit WAF rule active (100/5min on /api/board_ask*)
- [ ] Freshness checker includes food delivery data source

---

## Execution Order Recommendation

| Session | Items | Effort | Notes |
|---------|-------|--------|-------|
| **Session 1** | #9 (Alarms) | 15 min | Quick wins — just run two scripts |
| **Session 2** | #1 (Sleep observatory) | 4-6h | Use Training page as template |
| **Session 3** | #1 (Glucose observatory) | 4-6h | Same pattern, teal theme |
| **Session 4** | #5 + #6 (OG images + Subscribe CTAs) | 4-6h | Combine — both touch all pages |
| **Session 5** | #8 (Home page redesign) | 6-8h | Largest design effort |
| **Session 6** | #7 (Cross-region migration) | 2-3h | Infrastructure only |
| **Session 7** | #2 (CDK adoption) | 4-6h | Most complex — do last when stable |

**Total estimated effort:** 25-40 hours across 7 sessions

---

## Reference Files

| File | Purpose |
|------|---------|
| `site/training/index.html` | Canonical editorial observatory pattern |
| `site/nutrition/index.html` | Secondary editorial reference (amber theme) |
| `site/mind/index.html` | Editorial reference (violet theme) |
| `site/sleep/index.html` | Current sleep page (to be overhauled) |
| `site/glucose/index.html` | Current glucose page (to be overhauled) |
| `site/index.html` | Current home page (to be overhauled) |
| `site/assets/js/components.js` | Shared nav/footer/subscribe injection |
| `site/assets/css/tokens.css` | Design system tokens |
| `site/assets/css/base.css` | Base styles |
| `lambdas/og_image_lambda.py` | Existing OG image generator |
| `lambdas/site_api_lambda.py` | Site API (cross-region migration target) |
| `deploy/setup_r18_alarms.sh` | CloudWatch alarm script |
| `deploy/setup_waf_endpoint_rules.sh` | WAF endpoint rules script |
| `deploy/deploy_site.sh` | Canonical site deploy script |
| `deploy/deploy_lambda.sh` | Lambda deploy script |
| `cdk/stacks/*.py` | CDK stack definitions |
| `ci/lambda_map.json` | Lambda CI/CD mapping |
| `config/board_of_directors.json` | Board personas (S3) |

---

## Notes for Claude Code

- **S3 sync safety:** NEVER use `--delete` flag. Use `deploy/deploy_site.sh` which handles this correctly.
- **MCP deploy rule:** NEVER register a tool in TOOLS dict without the implementing function. Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.
- **Large file transfers:** Write to `/mnt/user-data/outputs/` → `present_files` for download. Direct `Filesystem:write_file` risks truncation on large files.
- **Deploy commands:** Write as clean single-line commands (no inline `#` comments — zsh parse errors).
- **CloudFront invalidation after every site deploy:** `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"`
- **Wait 10s between sequential Lambda deploys.**

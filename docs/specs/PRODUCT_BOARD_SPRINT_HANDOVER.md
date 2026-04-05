# Product Board Sprint Handover — Claude Code Implementation Brief

**Date:** 2026-04-05
**Platform Version:** v5.1.1 (A- at R20)
**Source:** Product Board session (8 personas) + Technical Board review + Personal Board review
**Author:** Claude (claude.ai planning session with Matthew)

> **Purpose:** This document gives Claude Code everything needed to implement the Product Board's prioritized sprint without needing to ask Matthew questions. Each item has: context, what to do, where to do it, acceptance criteria, board review notes, and gotchas.

---

## Table of Contents

1. [PB-01 — Discoveries Verification & Annotation Activation](#pb-01)
2. [PB-02 — get_nutrition Bug Closure Verification](#pb-02)
3. [PB-03 — OG Share Card End-to-End Verification](#pb-03)
4. [PB-04 — Sleep Observatory V2 Visual Overhaul](#pb-04)
5. [PB-05 — Glucose Observatory V2 Visual Overhaul](#pb-05)
6. [PB-06 — Weekly Subscriber Email ("The Weekly Signal")](#pb-06)
7. [PB-07 — Protocol Adherence Design on Sleep Page](#pb-07)
8. [PB-08 — Intelligence Page Rebuild (INT-01)](#pb-08)
9. [Board Reviews](#board-reviews)

---

## Implementation Priority & Sequencing

| Order | ID | Item | Effort | Dependency |
|-------|----|------|--------|------------|
| 1 | PB-01 | Discoveries verification + annotation activation | 30 min | None |
| 2 | PB-02 | get_nutrition bug closure verification | 15 min | None |
| 3 | PB-03 | OG share card end-to-end verification | 30 min | None |
| 4 | PB-04 | Sleep Observatory V2 visual overhaul | 3-4 hrs | None |
| 5 | PB-05 | Glucose Observatory V2 visual overhaul | 3-4 hrs | None |
| 6 | PB-06 | Weekly subscriber email automation | 3-4 hrs | None |
| 7 | PB-07 | Protocol adherence card on sleep page | 1-2 hrs | PB-04 |
| 8 | PB-08 | Intelligence page rebuild (INT-01) | Full session | After SIMP-1 Phase 2 (~Apr 13) |

**Session strategy:** PB-01 through PB-03 are verification tasks — do them first as a warm-up sweep. PB-04 and PB-05 are HTML/CSS work that can be done in the same session. PB-06 is a new Lambda. PB-07 rides on top of PB-04. PB-08 is its own dedicated session after SIMP-1 Phase 2 lands.

---

<a name="pb-01"></a>
## 1. PB-01 — Discoveries Verification & Annotation Activation

### Context

DISC-7 seeding was marked DONE in CHANGELOG v4.7.4. Four Day 1 events were seeded to DynamoDB. The `annotate_discovery` and `get_discovery_annotations` MCP tools exist in `mcp/tools_social.py`. The Discoveries page frontend (`site/discoveries/index.html`) has the full annotation UI.

**However**, the handover v5.1.1 still carries "DISC-7 annotation testing/seeding" as a carry-forward item. The Product Board (unanimous) says an empty or broken Discoveries page is the single biggest credibility gap on the site.

### What to Do

**Task A: Verify the Discoveries page renders seeded events**

```bash
# Hit the API and confirm timeline events exist
curl -s https://averagejoematt.com/api/journey_timeline | python3 -m json.tool | head -40
```

If the response contains the 4 Day 1 seed events from `seeds/seed_discoveries.py` (milestone, 2 experiments, 1 discovery), the page should render them. Open `https://averagejoematt.com/discoveries/` and visually verify:
- Timeline shows events in reverse chronological order
- Each event displays the annotation flow (Finding → Action → Outcome)
- Executive summary stats update (total discoveries count)
- Filter bar works

**Task B: Verify MCP annotation tools work end-to-end**

```bash
python3 -m pytest tests/test_mcp_registry.py -v -k "annotate_discovery or get_discovery_annotations"
```

If tests pass, also manually test via the MCP server (if local MCP bridge is available):
1. Call `get_discovery_annotations` — should return the 4 seeded annotations
2. Call `annotate_discovery` with a test annotation on one of the existing events — confirm it updates in DynamoDB

**Task C: If timeline is empty despite seeding**

Check DynamoDB directly:
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk": {"S": "USER#matthew#SOURCE#journey_timeline"}}' \
  --region us-west-2 \
  --max-items 5
```

If no items exist, re-run the seed script:
```bash
python3 seeds/seed_discoveries.py
```

Then trace the API endpoint in `lambdas/site_api_lambda.py` — search for `journey_timeline` to find the route handler. Confirm the query PK/SK matches what the seed script wrote.

**Task D: Remove DISC-7 from carry-forward if verified**

Update these files:
- `handovers/HANDOVER_LATEST.md` — remove from Known Issues / Carry Forward
- `docs/PROJECT_PLAN.md` — mark as ✅ DONE if still listed

### Files to Inspect
- `seeds/seed_discoveries.py` — verify seed items and DynamoDB key structure
- `lambdas/site_api_lambda.py` — search for `journey_timeline` route handler
- `mcp/tools_social.py` — `tool_annotate_discovery`, `tool_get_discovery_annotations`
- `site/discoveries/index.html` — frontend (should NOT need changes)

### Acceptance Criteria
- [ ] `/api/journey_timeline` returns 4+ events with annotations
- [ ] Discoveries page renders timeline with annotation flow visible
- [ ] MCP annotation tools pass registry tests
- [ ] DISC-7 removed from carry-forward lists

---

<a name="pb-02"></a>
## 2. PB-02 — get_nutrition Bug Closure Verification

### Context

CHANGELOG v4.7.4 says: "8 test cases written (`tests/test_get_nutrition_args.py`), all pass, no bug reproducible." The carry-forward was closed. This is a 15-minute verification to confirm the tests still pass and the item can be permanently closed.

### What to Do

```bash
python3 -m pytest tests/test_get_nutrition_args.py -v
```

If all 8 tests pass → confirm closed, no further action needed.

If any test fails → read the traceback, fix the issue, add a CHANGELOG entry.

### Acceptance Criteria
- [ ] All 8 test cases pass
- [ ] No `get_nutrition` references remain in any carry-forward list

---

<a name="pb-03"></a>
## 3. PB-03 — OG Share Card End-to-End Verification

### Context

HP-13 (Share Card) was marked DONE in CHANGELOG v4.7.4. The OG image Lambda (`lambdas/og_image_lambda.py`) generates 12 page-specific 1200x630 PNGs daily. OG meta tags are wired on major pages. A share button was added to the homepage.

The Product Board (Sofia + Jordan) says this is a distribution prerequisite: when someone pastes averagejoematt.com into Slack, Twitter, or LinkedIn, the dynamic card MUST render correctly.

### What to Do

**Task A: Verify OG images exist and are current**

```bash
# Check the homepage OG image
curl -sI https://averagejoematt.com/assets/images/og-home.png | head -20

# Check it's not stale (should have been regenerated today by og-image-generator Lambda)
curl -s https://averagejoematt.com/assets/images/og-home.png -o /tmp/og-home.png
file /tmp/og-home.png
# Should be a PNG, 1200x630

# Check other key pages
for page in sleep glucose training character nutrition mind; do
  echo "--- og-$page.png ---"
  curl -sI "https://averagejoematt.com/assets/images/og-$page.png" | grep -E "HTTP|Content-Type|Content-Length|Last-Modified"
done
```

**Task B: Verify OG meta tags on homepage**

```bash
curl -s https://averagejoematt.com/ | grep -E 'og:image|twitter:image'
```

Expected: `og:image` should point to `og-home.png` (NOT the old `og-image.png`). `twitter:card` should be `summary_large_image`.

Also check `og:image:width` (1200) and `og:image:height` (630) are present.

**Task C: Test with social media debuggers**

Provide Matthew with these links to manually test:
- Twitter Card Validator: https://cards-dev.twitter.com/validator
- LinkedIn Post Inspector: https://www.linkedin.com/post-inspector/
- Facebook Sharing Debugger: https://developers.facebook.com/tools/debug/

**Task D: Verify share button on homepage**

Check `site/index.html` for the share button — confirm it uses Web Share API (mobile) with clipboard fallback (desktop).

**Task E: Fix any issues found**

Common issues:
- OG image URL uses `site/share_card.png` (old spec) instead of `assets/images/og-home.png` (actual) — update meta tag
- `og:image:width` / `og:image:height` missing — add them
- CloudFront caching stale image — invalidate: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/images/og-*.png"`

### Acceptance Criteria
- [ ] `og:image` on homepage points to a valid, current 1200x630 PNG
- [ ] `twitter:card` is `summary_large_image`
- [ ] `og:image:width` and `og:image:height` present
- [ ] Share button works on homepage
- [ ] Matthew has social media debugger links for manual verification

---

<a name="pb-04"></a>
## 4. PB-04 — Sleep Observatory V2 Visual Overhaul

### Context

The Sleep page (`site/sleep/index.html`) was last visually updated in v3.9.25 but still doesn't fully match the editorial design pattern established by Inner Life (`site/mind/index.html`) and Nutrition (`site/nutrition/index.html`). The Product Board (Mara + Tyrell, unanimous) says this is a brand consistency issue — Sleep and Glucose are the two highest-traffic observatory pages.

**The target pattern** (from Inner Life/Nutrition/Training/Labs pages):
- 2-column editorial hero with animated SVG gauge ring
- Monospace section headers with trailing em-dash lines (`.s-section-header::after`)
- Left-accent bordered narrative cards
- Elena Voss pull-quote block
- AI expert analysis card (via `renderAIAnalysisCard()` in `components.js`)
- Observatory freshness indicator (`#obs-freshness`)
- "This Week" summary card
- Reading path navigation links
- Consistent spacing using design tokens from `tokens.css`

### What to Do

**Step 1: Audit the gap**

Compare `site/sleep/index.html` against `site/mind/index.html` (the gold standard). Document which elements are present/missing/misaligned:

| Element | Mind (target) | Sleep (current) | Gap |
|---------|---------------|-----------------|-----|
| 2-col editorial hero | ✅ | ? | Check |
| SVG gauge ring | ✅ | ? | Check |
| Monospace section headers | ✅ | Has `.s-section-header` | Verify CSS matches |
| Narrative body in serif | ✅ `.mind-page` serif | ? | Check |
| Elena pull-quote | ✅ | ? | Check |
| AI expert card | ✅ (via components.js) | ? | Check |
| Freshness indicator | ✅ | ? | Check |
| "This Week" card | ✅ | ? | Check |
| Reading path nav | ✅ | ? | Check |
| Chart.js charts | ✅ | ? | Check |

**Step 2: Align the layout**

The sleep page already has some editorial elements (it was partially redesigned in v3.9.25). The work is CSS/HTML restructuring, NOT backend. Key changes:

1. **Hero section**: Should be 2-column — left column with title, subtitle (Matthew's real voice from v4.7.2 content review), and key stats; right column with animated SVG gauge ring showing sleep score or efficiency.

2. **Section headers**: Ensure all section headers use the monospace pattern:
```html
<div class="s-section-header">SLEEP ARCHITECTURE</div>
```
With the CSS from the editorial pattern (trailing em-dashes, `var(--font-mono)`, `var(--text-2xs)`, `var(--text-faint)`).

3. **Narrative blocks**: Matthew's pull-quote about sleep (from v4.7.2) should be in a left-accent bordered card with serif font, matching Inner Life's intimate visual language.

4. **Data sections**: Sleep architecture (deep/REM/light percentages), bed temperature optimization, circadian consistency, social jet lag — each in its own section with the monospace header pattern.

5. **AI expert card**: Ensure `renderAIAnalysisCard()` is called with expert key `sleep` (check `components.js` EXPERTS config). If not present, add it.

6. **Observatory freshness**: Ensure `#obs-freshness` element and `initObsFreshness()` call are present.

**Step 3: Design reference files**

Read these before making changes:
- `site/mind/index.html` — PRIMARY design reference (the "intimate visual language" pattern)
- `site/nutrition/index.html` — Secondary reference (data-heavy editorial)
- `site/assets/css/tokens.css` — Design tokens (colors, spacing, fonts)
- `site/assets/css/base.css` — Shared base styles
- `site/assets/js/components.js` — `renderAIAnalysisCard()`, evidence badges, shared components

**Step 4: Preserve existing functionality**

The sleep page has working Chart.js charts, Eight Sleep × Whoop cross-reference data, and API-driven content. **Do NOT break the existing data pipeline.** The overhaul is visual/structural only.

Key API endpoints the page uses:
- `/api/vitals` — HRV, recovery, RHR
- `/api/sleep` or sleep-related fields in `/api/observatory_week?domain=sleep`
- AI expert analysis via `/api/ai_analysis?expert=sleep`

### Technical Board Review (Priya + Elena)

> **Priya**: "No backend changes means no risk to the data pipeline. Approve as CSS/HTML only. One caution: the sleep page inline `<style>` block is likely 200+ lines of custom CSS. Don't duplicate tokens — use `var()` references to `tokens.css` wherever possible."
>
> **Elena**: "Could another team own this? Yes — this is a pure frontend task. Suggest creating a shared `.observatory-editorial` CSS class in `base.css` rather than duplicating the pattern across 6 pages. If that's too much scope for this sprint, at least extract the common section-header, narrative-card, and pull-quote styles."

### Deploy
```bash
aws s3 cp site/sleep/index.html s3://matthew-life-platform/site/sleep/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/sleep/*"
```

### Acceptance Criteria
- [ ] Sleep page has 2-column editorial hero with SVG gauge ring
- [ ] All section headers use monospace pattern with em-dash trailing lines
- [ ] Matthew's pull-quote rendered in left-accent bordered serif card
- [ ] AI expert card present (sleep expert)
- [ ] Freshness indicator present
- [ ] Chart.js charts still render correctly
- [ ] Mobile responsive (test at 375px width)
- [ ] All data still loads from existing API endpoints
- [ ] No new API endpoints or Lambda changes required
- [ ] Design tokens from `tokens.css` used — no hardcoded colors/spacing

### Gotchas
- The sleep page has custom CSS variables (`--s-blue`, `--s-green`, etc.) that should be PRESERVED — they're the sleep page accent palette. The editorial restructuring should use these variables, not replace them.
- Elena's pull-quote text from v4.7.1 content review: "Sleep was never a problem for me... Whoop and Eight Sleep surfaced onset time and alcohol's red-shift impact." — this is the real narrative, don't replace with placeholder copy.
- If the page already has most editorial elements but they're slightly misaligned, this might be a lighter-touch job than a full rewrite. Start with the audit (Step 1) before deciding scope.

---

<a name="pb-05"></a>
## 5. PB-05 — Glucose Observatory V2 Visual Overhaul

### Context

Same story as Sleep. The Glucose page (`site/glucose/index.html`) needs alignment with the editorial design pattern. It was last restructured in v3.9.25 but drifted from the Inner Life gold standard.

### What to Do

**Identical process to PB-04** — audit the gap against `site/mind/index.html`, then align.

Glucose-specific elements to preserve:
- CGM data visualizations (glucose time-in-range, daily curve if available)
- Meal × glucose cross-reference cards
- The pull-quote from v4.7.2: Matthew replaced the "health anxiety narrative" with "CGM curiosity framing"
- Custom CSS variables for glucose page accent palette

Glucose-specific API endpoints:
- `/api/glucose` or glucose fields in `/api/observatory_week?domain=glucose`
- `/api/meal_glucose` — meal × CGM cross-reference
- AI expert analysis via `/api/ai_analysis?expert=glucose`

**Design note (Tyrell):** The glucose page should use the amber/gold accent palette (`--g-amber`, `--g-gold` or similar). CGM data is inherently visual — the daily glucose curve chart is the centerpiece. Don't bury it below the fold.

### Deploy
```bash
aws s3 cp site/glucose/index.html s3://matthew-life-platform/site/glucose/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/glucose/*"
```

### Acceptance Criteria
- [ ] Same editorial checklist as PB-04 (hero, section headers, pull-quote, AI card, freshness, mobile)
- [ ] CGM visualizations preserved and working
- [ ] Glucose-specific accent palette maintained
- [ ] "Glucose daily curve" section gracefully hidden when no intraday data (existing behavior — don't regress)

---

<a name="pb-06"></a>
## 6. PB-06 — Weekly Subscriber Email ("The Weekly Signal")

### Context

The Product Board (Sofia, Jordan, Ava) identified a critical gap: the subscriber content pipeline is incomplete.

**What exists today:**
- `chronicle_email_sender_lambda.py` — sends Elena's weekly Chronicle to subscribers every Wednesday at 8:10 AM PT ✅
- `subscriber_onboarding_lambda.py` — sends Day 2 bridge email to new subscribers ✅
- `weekly_digest_lambda.py` — sends a comprehensive weekly report to **Matthew only** (via `RECIPIENT` env var) every Sunday ✅
- Email subscriber infrastructure: SES in production mode, subscribe form working, DynamoDB subscriber records ✅

**What's missing:**
- A weekly summary email that goes to **subscribers** (not just Matthew). The weekly digest is too detailed/personal. Subscribers need a curated 5-section summary — "The Weekly Signal."

### What to Build

**New Lambda: `weekly-signal-lambda`**

This is a subscriber-facing weekly email. NOT a copy of Matthew's private weekly digest. It's a curated public summary designed for retention.

**Schedule:** EventBridge `cron(30 16 ? * SUN *)` — Sunday 9:30 AM PT (30 min after Matthew's private digest at 9:00 AM)

**Architecture decision (Tech Board — James/Marcus):**
> Separate Lambda from weekly_digest. Same pattern as chronicle_email_sender vs wednesday_chronicle. Independent DLQ, independent retry, independent alarm. Reads pre-computed data from DynamoDB and S3 — does NOT re-run AI calls.

**Template: 5-Section "Weekly Signal" Email**

```
Subject: "Week {week_number} — The Measured Life"

Section 1: THE NUMBERS
  - Weight this week vs last (delta + arrow)
  - Avg sleep score
  - Avg recovery
  - Habit streak (Tier 0 count)
  - Character level + XP

Section 2: CHRONICLE PREVIEW
  - Elena's latest headline (from chronicle posts.json)
  - First 2 sentences + "Read more →" link

Section 3: WHAT WORKED / WHAT DIDN'T
  - Top 1 "worked" insight from daily brief guidance_given
  - Top 1 "didn't" or challenge from the week

Section 4: THE BOARD SAYS
  - One rotating board member quote from weekly digest commentary
  - Rotates: week 1 = The Chair, week 2 = Dr. Chen, etc.

Section 5: OBSERVATORY SPOTLIGHT
  - One rotating observatory page highlight
  - Rotates: Sleep → Glucose → Nutrition → Training → Inner Life
  - 1-2 sentences + link to page
```

**Data sources (all pre-computed, no AI calls needed):**

| Section | Data Source | How to Read |
|---------|------------|-------------|
| Numbers | `public_stats.json` in S3 (`generated/public_stats.json` or `site/public_stats.json`) | `s3.get_object()` |
| Chronicle | `generated/journal/posts.json` in S3 | `s3.get_object()`, take latest post |
| Worked/Didn't | DynamoDB `SOURCE#insights` or `SOURCE#computed_insights` | Query last 7 days, filter by type |
| Board quote | DynamoDB `SOURCE#insights` (weekly digest type) | Read `insight_type: "coaching"` from last weekly |
| Observatory | Hardcoded rotation array based on `week_number % 5` | Rotation logic in code |

**Subscriber query pattern:**

```python
# Get all confirmed subscribers
resp = table.query(
    KeyConditionExpression=Key("PK").eq(f"USER#{USER_ID}#SOURCE#subscribers"),
    FilterExpression=Attr("status").eq("confirmed")
)
subscribers = resp.get("Items", [])
```

This is the same pattern used by `chronicle_email_sender_lambda.py` — reference that file for:
- Subscriber query
- SES send pattern (personalized unsubscribe links)
- Rate limiting (1/sec for SES)
- Error handling per-subscriber (one failure doesn't block others)

**Email HTML template:**

Follow the same email design language as the chronicle emails and subscriber onboarding. Reference `chronicle_email_sender_lambda.py` for the HTML template pattern. Key design rules:
- Dark background (`#080c0a`), light text
- Monospace section headers
- Platform accent green (`#4ade80` or `#3db88a`)
- CAN-SPAM compliant: unsubscribe link, physical address (use the SES default)
- Mobile-first (single column, 600px max width)

### Files to Create
- `lambdas/weekly_signal_lambda.py` — NEW Lambda

### Files to Modify
- `cdk/stacks/email_stack.py` (or wherever email Lambdas are defined) — add weekly-signal Lambda with:
  - EventBridge schedule: `cron(30 16 ? * SUN *)`
  - IAM: DynamoDB read, S3 read (`generated/*`, `site/public_stats.json`), SES send, Secrets read
  - Environment vars: TABLE_NAME, USER_ID, S3_BUCKET, EMAIL_SENDER, SITE_URL
  - DLQ: `life-platform-ingestion-dlq`
  - Alarm: error + duration
- `ci/lambda_map.json` — add entry for `weekly-signal`
- `docs/ARCHITECTURE.md` — add to Email Layer table

### Technical Board Review (Marcus + Jin)

> **Marcus**: "Follow the chronicle_email_sender pattern exactly. Same subscriber query, same SES rate limiting, same error handling. The only new thing is the email template and data aggregation. Keep it under 200 lines."
>
> **Jin**: "What breaks at 2 AM? If public_stats.json doesn't exist yet (first run), the Lambda should gracefully degrade — send a minimal email or skip. Same for empty chronicle posts. Never crash on missing data. Add a CloudWatch alarm for errors AND for zero-sends (if subscriber count > 0 but emails sent = 0, that's a silent failure)."

### Deploy
```bash
# Add to CDK and deploy the email stack
cd cdk && cdk deploy LifePlatformEmail --require-approval never

# Or if creating manually first:
# 1. Create Lambda
# 2. Add EventBridge rule
# 3. Add IAM role
# 4. Add alarm
# Then adopt into CDK later (but CDK-first is preferred)
```

Wait 10s between Lambda deploys if deploying multiple Lambdas.

### Acceptance Criteria
- [ ] Lambda fires every Sunday at 9:30 AM PT
- [ ] All confirmed subscribers receive the email
- [ ] Email contains all 5 sections with real data
- [ ] Unsubscribe link works per subscriber
- [ ] Graceful degradation: missing data → section skipped, not Lambda crash
- [ ] CloudWatch alarm configured
- [ ] `lambda_map.json` updated
- [ ] Rate limiting: 1 email/sec (SES)

### Gotchas
- `chronicle_email_sender_lambda.py` is your primary reference — read it before writing the new Lambda.
- SES is in production mode (not sandbox), so no recipient verification needed.
- The weekly digest (`weekly_digest_lambda.py`) sends to `RECIPIENT` (Matthew's email only). Do NOT modify it to also send to subscribers — that's too much data. The Weekly Signal is a curated subset.
- `public_stats.json` may be at either `site/public_stats.json` or `generated/public_stats.json` — check both paths (the bug bash moved generated files to the `generated/` prefix, but the stats-refresh Lambda may write to either). Use a try/except with both paths.
- Test with a single subscriber first before enabling the full send.

---

<a name="pb-07"></a>
## 7. PB-07 — Protocol Adherence Design on Sleep Page

### Context

The Personal Board (Dr. Lena Johansson, longevity science advisor) and Product Board (Dr. Lena Johansson, science credibility) both flagged this: the platform has sleep protocols defined in DynamoDB and sleep data flowing from Whoop/Eight Sleep, but the Sleep page doesn't show whether protocols are being followed or working.

### Personal Board Review (Dr. Lisa Park + Dr. James Okafor)

> **Dr. Lisa Park (Sleep & Circadian Specialist):** "The sleep onset protocol is the most testable. Matthew's target is onset before 11pm. You have Whoop sleep_start data. Show: target onset, actual onset (7-day rolling), adherence rate (days met / total days), and recovery delta (recovery score on adherent days vs non-adherent days). That's the closed loop."
>
> **Dr. James Okafor (Longevity):** "Keep it simple. One protocol card, not a full section. The data volume isn't there yet for multivariate analysis. Just: protocol name, target, adherence %, and an early correlation signal (even if N<30 — flag it with the Henning Brandt low-confidence label)."

### What to Build

**A "Protocol Adherence" card on the Sleep page** — NOT a full section, just a single card in the existing data area.

**Design:**

```
┌─────────────────────────────────────────────────┐
│  PROTOCOL ADHERENCE ——                          │
│                                                 │
│  Sleep Onset < 11:00 PM                         │
│  ┌──────────────────────────────┐               │
│  │ ████████████░░░░  18/30 days │  60%          │
│  └──────────────────────────────┘               │
│                                                 │
│  When met: Avg recovery 52%                     │
│  When missed: Avg recovery 41%                  │
│  Delta: +11% recovery ⚠️ N<30, low confidence   │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Data source:** The site-api already has sleep data from Whoop. The sleep onset time comes from Whoop's `sleep_start` field (converted to PT in v4.8.3).

**Implementation options (Claude Code decides):**

**Option A — Client-side calculation:** The sleep page already fetches sleep data via API. Add a JavaScript function that:
1. Reads the last 30 days of sleep data (sleep_start times)
2. Counts days where sleep_start was before 23:00 PT
3. Calculates average recovery on adherent vs non-adherent days
4. Renders the card

**Option B — New API field:** Add `protocol_adherence` to the existing sleep-related API response in `site_api_lambda.py`. This is cleaner but requires a Lambda deploy.

**Recommended: Option A** — pure frontend, no deploy risk, can iterate quickly. The protocol target (23:00) can be read from `site_constants.js` or hardcoded initially.

### Technical Board Review (Henning Brandt)

> **Dr. Henning Brandt (Statistician):** "N<30 = low confidence. This MUST be labeled. Use the evidence badge system from the Signal Doctrine: 'Preliminary signal — N<30, correlational only.' Do NOT say 'sleep onset before 11pm improves recovery by 11%.' Say 'On days with onset before 11pm, recovery averaged 11 percentage points higher (N=18, preliminary).' If N<10, don't show the delta at all — just show adherence rate."

### Files to Modify
- `site/sleep/index.html` — add protocol adherence card (HTML + JS + CSS)

### Acceptance Criteria
- [ ] Protocol adherence card visible on sleep page
- [ ] Shows adherence rate as progress bar + percentage
- [ ] Shows recovery delta on adherent vs non-adherent days (if N≥10)
- [ ] Henning Brandt confidence label present when N<30
- [ ] Mobile responsive
- [ ] Falls back gracefully if insufficient data

### Gotchas
- Sleep onset times from Whoop are in UTC — MUST convert to PT before comparing to the 11pm target. The sleep page already handles this (v4.8.3 PT conversion).
- Protocol data may also exist in DynamoDB under `SOURCE#protocols`. Check if there's a "sleep onset" protocol record that stores the target time — use it instead of hardcoding if available.
- This card should be positioned AFTER the main sleep metrics but BEFORE the AI expert card.

---

<a name="pb-08"></a>
## 8. PB-08 — Intelligence Page Rebuild (INT-01)

### Context

The Intelligence page (`site/intelligence/index.html`) exists but is largely static. The Product Board (Raj Mehta) says: "A live, API-driven Intelligence page is your most differentiated asset — nobody else shows their AI reasoning layer publicly."

**Current state:** The page has a static layout with stat strip (4 metrics), feature cards for each IC feature, and a sample Daily Brief section. From v4.7.2 content review: "subtitle simplified, hardcoded sample Daily Brief replaced with API placeholder."

**Target state:** Live tabbed panels pulling real data from existing API endpoints. No new Lambdas needed — all data already exists.

### ⚠️ SCHEDULING NOTE

**Do NOT start this until after SIMP-1 Phase 2 (~April 13).** SIMP-1 will consolidate MCP tools from 115 to ≤80 and will touch the MCP server. The Intelligence page displays tool counts and IC feature information that will change. Starting INT-01 before SIMP-1 would create merge conflicts and stale content.

### What to Build

**Tabbed panel architecture** with 5 live tabs:

**Tab 1: Daily Brief (sample)**
- Fetch latest daily brief excerpt from `public_stats.json` or DynamoDB
- Show: today's brief summary, board commentary highlight, top insight
- This is the "hero" tab — it demonstrates what the AI actually produces

**Tab 2: Correlations**
- Fetch from `/api/correlations`
- Show: top 5 significant correlation pairs with confidence badges
- Interactive: click a pair to see the scatter plot or detail

**Tab 3: Hypotheses**
- Fetch from existing MCP tool `get_hypotheses` (or add a `/api/hypotheses` public route)
- Show: active hypotheses with status (pending/confirmed/refuted), domain tags, confidence
- This is the unique differentiator — show the platform generating and testing hypotheses

**Tab 4: Experiments**
- Already exists at `/api/experiments`
- Show: active N=1 experiments with status, days in, early signals
- Link to the full experiments page

**Tab 5: Character Engine**
- Fetch from `/api/character`
- Show: current level, pillar breakdown, XP, tier
- Brief explanation of how the engine works

**Each tab should:**
- Load data on tab activation (lazy load, not all at once)
- Show loading skeleton while fetching
- Handle errors gracefully (show "Data unavailable" not a crash)
- Use the editorial design pattern (monospace headers, cards, evidence badges)

### New API Endpoints Needed

The site-api may need 1-2 new public routes:

1. **`/api/hypotheses`** — public version of `get_hypotheses` MCP tool. Return active hypotheses (domain, status, confidence, date). Filter out any with `public: false` if applicable. TTL: 1 hour.

2. **`/api/intelligence_summary`** — aggregate endpoint returning counts and highlights:
```json
{
  "ic_features_live": 16,
  "ic_features_total": 31,
  "correlations_computed_weekly": 23,
  "hypotheses_active": 4,
  "experiments_active": 3,
  "insights_persisted_30d": 42,
  "last_hypothesis_date": "2026-04-01",
  "last_correlation_run": "2026-04-01"
}
```

### Technical Board Review (Anika + Henning)

> **Dr. Anika Patel (AI/LLM Systems):** "The Intelligence page is the AI trustworthiness showcase. Every number must be real, every hypothesis must have provenance, every correlation must show N and p-value. Do NOT display AI-generated text without labeling it as AI-generated. The evidence badge system from the Signal Doctrine should be used throughout."
>
> **Dr. Henning Brandt:** "Correlation display rules: (1) Only show pairs with p<0.05 after Benjamini-Hochberg correction. (2) Always show N. (3) Never use causal language. (4) Include the disclaimer: 'Correlational only. N=1 observational data. Not generalizable.' These rules are non-negotiable."

### Files to Create
- None — all work is in existing files

### Files to Modify
- `site/intelligence/index.html` — full page rebuild (HTML + JS + CSS)
- `lambdas/site_api_lambda.py` — add `/api/hypotheses` and `/api/intelligence_summary` routes
- `cdk/stacks/role_policies.py` — may need to add DynamoDB read permissions for hypotheses partition (check if site-api role already has it)

### Deploy
```bash
# Deploy site-api with new routes
bash deploy/deploy_lambda.sh life-platform-site-api

# Deploy page
aws s3 cp site/intelligence/index.html s3://matthew-life-platform/site/intelligence/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/intelligence/*" "/api/hypotheses*" "/api/intelligence_summary*"
```

### Acceptance Criteria
- [ ] 5 tabbed panels all loading live data
- [ ] Correlations show N, p-value, confidence badges
- [ ] Hypotheses show status, domain, confidence, date
- [ ] Evidence badges from Signal Doctrine used throughout
- [ ] Henning Brandt disclaimer present
- [ ] AI-generated content labeled as such
- [ ] Mobile responsive (tabs → accordion on mobile)
- [ ] Lazy loading per tab (no all-at-once fetch)
- [ ] Stat strip numbers pulled from API (not hardcoded)
- [ ] Post-SIMP-1 tool counts reflected accurately

### Gotchas
- **Wait for SIMP-1 Phase 2.** Tool count, feature count, and MCP architecture will change.
- site-api Lambda is in **us-west-2**. Deploy with `deploy_lambda.sh`.
- The hypotheses DynamoDB partition is `SOURCE#hypotheses`. Check if the site-api IAM role has read access to this partition — it might only have access to specific partitions. If not, update `role_policies.py` in the CDK operational stack.
- The existing Intelligence page is ~400+ lines. Consider building the new version alongside (e.g., `intelligence/index_v2.html`) and swapping once verified.

---

<a name="board-reviews"></a>
## Board Reviews

### Technical Board Summary

| Item | Reviewer(s) | Verdict | Key Concern |
|------|------------|---------|-------------|
| PB-01 (Discoveries) | — | Approve | Verification only, no risk |
| PB-02 (Nutrition bug) | — | Approve | Test-only, no risk |
| PB-03 (OG card) | — | Approve | Verification only |
| PB-04 (Sleep V2) | Priya, Elena | Approve (CSS/HTML only) | Don't duplicate tokens; consider shared `.observatory-editorial` class |
| PB-05 (Glucose V2) | Priya, Elena | Approve (CSS/HTML only) | Same as PB-04 |
| PB-06 (Weekly Signal) | Marcus, Jin | Approve (new Lambda) | Follow chronicle_email_sender pattern; graceful degradation on missing data; alarm for zero-sends |
| PB-07 (Protocol adherence) | Henning | Approve (frontend only) | N<30 confidence label MANDATORY; correlational language only |
| PB-08 (Intelligence rebuild) | Anika, Henning | Approve (after SIMP-1) | Evidence badges required; causal language prohibited; new API routes need IAM check |

### Personal Board Summary

| Item | Reviewer(s) | Input |
|------|------------|-------|
| PB-07 (Protocol adherence) | Dr. Lisa Park, Dr. James Okafor | Sleep onset protocol is most testable. Show target, actual, adherence %, recovery delta. One card, not a section. Low data volume — keep it simple. |

### Product Board Consensus

**Throughline test (decision framework):** Does this help a visitor connect the story from any page to any other page?

- PB-01 (Discoveries): YES — timeline is the connective tissue
- PB-04/05 (Visual V2): YES — consistent brand = coherent story
- PB-06 (Weekly Signal): YES — retention loop keeps visitors returning
- PB-07 (Protocol adherence): YES — closes the "what I'm doing about it" loop
- PB-08 (Intelligence): YES — shows the AI layer that makes this more than a dashboard

**Jordan Kim's wildcard reminder:** Matthew writing the Builders page prose and submitting a "Show HN" post is the single highest-ROI growth move available. The page infrastructure is ready. This is writing work, not engineering — do it whenever inspiration strikes.

---

## Deploy Safety Reminders

- NEVER use `aws s3 sync --delete` against bucket root or `site/`.
- All Lambda deploys via `bash deploy/deploy_lambda.sh <lambda-name>`.
- MCP Lambda (`life-platform-mcp`): manual zip deploy only — `deploy_lambda.sh` will FATAL if passed this name.
- Wait 10s between sequential Lambda deploys.
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.
- CloudFront invalidation: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/path/*"`
- `site_writer.py` lives in the shared Lambda layer — changes require layer rebuild + reattach.
- CloudFront distribution: E3S424OXQZ8NBE (averagejoematt.com)
- S3 bucket: matthew-life-platform
- DynamoDB table: life-platform (us-west-2)
- Site-api Lambda is in **us-west-2** (confirmed)

---

## Session-End Checklist

After completing this sprint:

1. Update `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` if counts changed
2. Run `python3 deploy/sync_doc_metadata.py --apply`
3. Write handover to `handovers/` and update `HANDOVER_LATEST.md`
4. Update `CHANGELOG.md` with version entry
5. Update docs per trigger matrix:
   - ARCHITECTURE.md — if PB-06 adds a new Lambda or PB-08 adds API routes
   - INFRASTRUCTURE.md — if PB-06 adds a new Lambda
   - RUNBOOK.md — if PB-06 adds operational procedures
6. `git add -A && git commit -m "feat: product board sprint — [items completed]" && git push`

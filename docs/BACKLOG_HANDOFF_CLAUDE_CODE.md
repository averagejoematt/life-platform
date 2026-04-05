# Backlog Handoff — Claude Code Implementation Brief

**Date**: 2026-03-31
**Platform version**: v4.5.0+
**Author**: Product Board (8 personas) + Matthew — compiled from offsite reviews, HOME_EVOLUTION_SPEC.md, and codebase audit

> **Purpose**: This document gives Claude Code everything it needs to implement backlog items without needing to ask Matthew questions. Each item has: what to do, where to do it, acceptance criteria, and gotchas.

---

## Table of Contents

1. [DISC-7 — Annotation Testing & Seeding](#disc-7)
2. [HP-12 — Elena Hero Line Backend Caller](#hp-12) ✅ DONE
3. [HP-13 — Share Card Lambda + Dynamic OG Image](#hp-13) ✅ DONE
4. [BL-01 — For Builders Page](#bl-01) ✅ DONE
5. [BL-02 — Bloodwork/Labs Page](#bl-02) ✅ DONE
6. [get_nutrition — Positional Args Bug](#get-nutrition-bug)

---

<a name="disc-7"></a>
## 1. DISC-7 — Annotation Testing & Seeding

### Status
- **Frontend**: DONE. `site/discoveries/index.html` has full DISC-7 UI — Finding → Action → Outcome annotation flow (CSS at line ~513, JS at line ~881). Card structure renders `e.annotation.annotation`, `e.annotation.action_taken`, `e.annotation.outcome`.
- **MCP tools**: DONE. `annotate_discovery` and `get_discovery_annotations` are registered in `mcp/registry.py` (lines 1613–1660). The implementing functions (`tool_annotate_discovery`, `tool_get_discovery_annotations`) are imported via wildcard from one of the `mcp/tools_*.py` modules.
- **API**: The `/api/journey_timeline` endpoint serves timeline events to the discoveries page.
- **What's missing**: The timeline launches **empty**. There is zero seed data in DynamoDB. The page shows a "Discoveries populate over time..." fallback message.

### What to Build

**Task A: Verify MCP annotation tools work end-to-end**

1. Find which `mcp/tools_*.py` file contains `tool_annotate_discovery` and `tool_get_discovery_annotations` (search all files in `mcp/` for these function names).
2. Run `python3 -m pytest tests/test_mcp_registry.py -v` — confirm both tools pass the registry validation (function exists, schema matches).
3. If the functions are stubs or missing, implement them:
   - `tool_annotate_discovery(args)`:
     - Reads `date`, `event_type`, `title`, `annotation`, `action_taken` (optional), `outcome` (optional) from args.
     - Writes to DynamoDB table `life-platform` with a key pattern consistent with `journey_timeline` events. The annotation should be stored as a nested `annotation` dict on the timeline event item, OR as a separate item linked by the event's composite key.
     - Check how `/api/journey_timeline` in `lambdas/site_api_lambda.py` reads timeline events to determine the correct key structure.
   - `tool_get_discovery_annotations(args)`:
     - Queries DynamoDB for all timeline events that have a non-null `annotation` field.
     - Returns list of `{date, event_type, title, annotation, action_taken, outcome}`.

**Task B: Seed initial timeline events + annotations**

Create a seed script at `seeds/seed_discoveries.py` that writes the following Day 1 baseline events to DynamoDB. These are the pre-launch seed events the Product Board specified (recommendation 15d):

```python
SEED_EVENTS = [
    {
        "date": "2026-04-01",
        "event_type": "milestone",
        "title": "Day 1 — Journey Begins",
        "body": "Platform goes live. Starting weight 302 lbs. 25 data sources connected. All observatories active.",
        "annotation": {
            "annotation": "Made the decision to track everything publicly. No hiding, no selective disclosure.",
            "action_taken": "Launched platform",
            "outcome": None  # TBD — this gets filled in later
        }
    },
    {
        "date": "2026-04-01",
        "event_type": "experiment",
        "title": "Hypothesis: Sleep onset before 11pm improves next-day recovery",
        "body": "Based on preliminary Whoop data showing correlation between sleep onset time and recovery score. Testing over 30 days with intentional 10:30pm target.",
        "annotation": {
            "annotation": "Set 10:15pm phone alarm as wind-down trigger. Moved phone charger to kitchen.",
            "action_taken": "Evening routine change",
            "outcome": None
        }
    },
    {
        "date": "2026-04-01",
        "event_type": "experiment",
        "title": "Hypothesis: Zone 2 cardio 150min/week stabilizes glucose variability",
        "body": "CGM data shows glucose coefficient of variation tracks inversely with aerobic volume. Testing Attia's 150min/week Zone 2 target.",
        "annotation": {
            "annotation": "Added 3x 50min rucking sessions to weekly schedule. Garmin HR zone targeting.",
            "action_taken": "Training protocol update",
            "outcome": None
        }
    },
    {
        "date": "2026-04-01",
        "event_type": "discovery",
        "title": "Baseline established: 14 biomarkers out of range",
        "body": "Function Health blood draw shows 14 of 107 biomarkers outside optimal range. Key flags: fasting insulin, hs-CRP, vitamin D, ApoB.",
        "annotation": {
            "annotation": "Scheduled follow-up labs for 90 days. Added vitamin D3+K2 5000IU and omega-3 protocol.",
            "action_taken": "Supplement protocol started",
            "outcome": None
        }
    },
]
```

The seed script must:
- Read the DynamoDB key structure from how `site_api_lambda.py` queries journey_timeline events (look for the GSI or query pattern).
- Write items using `boto3` with the correct PK/SK format for the `life-platform` table.
- Be idempotent (check if items exist before writing, or use `put_item` with condition expression).
- Print what it wrote so Matthew can verify.

**Task C: Verify the discoveries page renders the seeded events**

After seeding, hit `https://averagejoematt.com/discoveries/` and confirm:
- Timeline shows the 4 seeded events in reverse chronological order.
- Each event shows the annotation flow (Finding → Action → Outcome with the 3-step visual).
- The executive summary stats update (total discoveries count, behavioral change count).
- Filter bar works (filtering by event type).

### Files to Touch
- `mcp/tools_*.py` (whichever contains annotation functions) — verify/fix implementation
- `lambdas/site_api_lambda.py` — read to understand timeline event key structure (DO NOT MODIFY unless broken)
- `seeds/seed_discoveries.py` — NEW file
- `site/discoveries/index.html` — NO changes needed (frontend is done)

### Acceptance Criteria
- `pytest tests/test_mcp_registry.py -v` passes for both `annotate_discovery` and `get_discovery_annotations`.
- 4 seed events are in DynamoDB with annotations.
- Discoveries page renders events with annotation flow visible.
- `get_discovery_annotations` MCP tool returns the seeded annotations.

### Gotchas
- DynamoDB table is `life-platform` in `us-west-2`. Single-table design — check PK/SK format before writing.
- The discoveries page JS fetches from `/api/journey_timeline` — trace this endpoint in `site_api_lambda.py` to find the exact query pattern.
- NEVER use `--delete` when syncing to S3. Use `aws s3 cp` for single files.

---

<a name="hp-12"></a>
## 2. HP-12 — Elena Hero Line Backend Caller

### Status: ✅ ALREADY IMPLEMENTED — REMOVE FROM BACKLOG

**This item is done.** Audit confirms the full pipeline is wired:

1. **Generation** (daily_brief_lambda.py, lines 1608–1619): `_elena_hero_line` is extracted from the TL;DR guidance output, truncated to ≤200 chars with sentence-boundary logic.
2. **Passing** (daily_brief_lambda.py, line 1980): `elena_hero_line=_elena_hero_line` is passed to `write_public_stats()`.
3. **Writing** (site_writer.py, line 198): `write_public_stats()` accepts `elena_hero_line` parameter, writes it to the `public_stats.json` payload (line 275).
4. **Frontend** (site/index.html): HP-12 frontend was shipped in Sprint C — pull-quote block reads `elena_hero_line` from `public_stats.json` and renders it with Elena attribution. Hidden if null.

**Action for Claude Code**: No implementation needed. Remove HP-12 from all carry-forward lists in `PROJECT_PLAN.md`, `SPRINT_PLAN.md`, and handover files.

**Verification**: Run `curl -s https://averagejoematt.com/site/public_stats.json | python3 -m json.tool | grep elena` — if the daily brief has run at least once, this field should be present (may be null if TL;DR generation failed or hasn't run yet post-launch).

---

<a name="hp-13"></a>
## 3. HP-13 — Share Card Lambda + Dynamic OG Image

### Status: ✅ ALREADY IMPLEMENTED — REMOVE FROM BACKLOG

**This item is done.** Two implementations exist:
1. **Node.js SVG version** (`lambdas/og_image_lambda.mjs`) — deployed via CDK web stack, served through CloudFront OG image origin with 1hr cache.
2. **Python/Pillow PNG version** (`lambdas/og_image_lambda.py`) — 12 page-specific builders (home, sleep, glucose, training, character, nutrition, mind, labs, chronicle, weekly, experiments, builders). Runs daily at 11:30 AM PT via `og-image-generator` Lambda.
3. **Fonts** bundled in `lambdas/fonts/` (Bebas Neue, Space Mono).
4. **OG meta tags** wired on all major pages (glucose, labs, recap, supplements, tools, week).
5. **Pillow layer** (v1) published. CDK constants defined.

**Minor carry-forward:** `og-image-generator` Lambda was CLI-created, not yet CDK-managed (tracked as R18-F02).

### What to Build (COMPLETED — reference only)

**Architecture Decision: Static S3 file, regenerated daily by the Daily Brief pipeline.**

This avoids a new Lambda@Edge or function URL. The daily brief already runs at 10am PT and writes `public_stats.json` — it can also render the share card at the same time.

#### Step 1: SVG Template (`lambdas/share_card_template.svg`)

Create an SVG template (1200×630px — OG image standard) with placeholders:

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  averagejoematt.com                                 │
│  THE MEASURED LIFE                                  │
│                                                     │
│  Day {days_in}                                      │
│                                                     │
│  {lbs_lost} lbs lost  ·  {journey_pct}% to goal    │
│  Streak: {tier0_streak} days                        │
│  Level {character_level} — {tier_name}              │
│                                                     │
│  "{elena_hero_line}"                                │
│  — Elena Voss                                       │
│                                                     │
│  Updated {date}                                     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Design tokens: Dark background (`#080c0a`), accent green (`#4ade80`), amber for Elena quote (`#f59e0b`). Use the platform's font stack in `font-family` attributes (Georgia for Elena quote, system monospace for stats). Keep it clean — this should look like the platform's design language, not a generic social card.

#### Step 2: Share Card Generator (`lambdas/share_card_generator.py`)

New module (imported by daily_brief_lambda.py, NOT a standalone Lambda):

```python
def generate_share_card(public_stats: dict, output_bucket: str, output_key: str = "site/share_card.png"):
    """
    Reads the SVG template, substitutes values from public_stats,
    converts SVG → PNG via Pillow + cairosvg, uploads to S3.
    """
    # 1. Read SVG template from package or S3
    # 2. String-substitute all {placeholders} from public_stats dict
    # 3. Convert SVG → PNG:
    #    - Use cairosvg.svg2png() — cairosvg is pip-installable and Lambda-compatible
    #    - Output at 1200×630 px
    # 4. Upload PNG to S3:
    #    s3.put_object(Bucket=output_bucket, Key=output_key,
    #                  Body=png_bytes, ContentType="image/png",
    #                  CacheControl="max-age=3600")
    # 5. Return the CloudFront URL
```

**Dependencies to add to the Lambda layer or Lambda package**:
- `cairosvg` (pip install) — requires `cairo` system library. If Lambda doesn't have cairo, use alternative: `svglib` + `reportlab` (pure Python, no system deps), or pre-render with Pillow text drawing (no SVG needed, just draw directly).
- **Recommended fallback if cairosvg is problematic**: Skip SVG entirely. Use Pillow (`PIL`) to draw the card directly on a 1200×630 canvas with `ImageDraw.text()`. This is simpler and has zero system dependencies.

#### Step 3: Wire into Daily Brief

In `lambdas/daily_brief_lambda.py`, after the `write_public_stats()` call (~line 1980), add:

```python
# HP-13: Generate daily share card
try:
    from share_card_generator import generate_share_card
    _card_stats = {
        "days_in": _days_in,
        "lbs_lost": _lost,
        "journey_pct": _prog_pct,
        "tier0_streak": _tier0_streak,
        "character_level": (character_sheet or {}).get("level"),
        "tier_name": (character_sheet or {}).get("tier") or (character_sheet or {}).get("tier_name"),
        "elena_hero_line": _elena_hero_line,
        "date": today.strftime("%B %d, %Y"),
    }
    generate_share_card(_card_stats, S3_BUCKET)
    print("[INFO] HP-13: share_card.png written to S3")
except Exception as _sc_e:
    print(f"[WARN] HP-13: share card generation failed (non-fatal): {_sc_e}")
```

#### Step 4: Update OG Tags

In `site/index.html`, replace the static OG image:

```html
<!-- Before -->
<meta property="og:image" content="https://averagejoematt.com/assets/images/og-image.png">

<!-- After -->
<meta property="og:image" content="https://averagejoematt.com/site/share_card.png">
```

Also add `og:image:width` (1200) and `og:image:height` (630) if not already present.

#### Step 5: Share Button on Home Page

Add a "Share" button in the hero section of `site/index.html`:

```javascript
// Web Share API (mobile) with clipboard fallback (desktop)
function shareCard() {
  const url = 'https://averagejoematt.com';
  const text = 'The Measured Life — one person tracking everything, hiding nothing.';
  if (navigator.share) {
    navigator.share({ title: 'The Measured Life', text, url });
  } else {
    navigator.clipboard.writeText(url).then(() => {
      // Show "Copied!" toast
    });
  }
}
```

### Files to Create
- `lambdas/share_card_generator.py` — NEW
- `lambdas/share_card_template.svg` — NEW (or skip if using Pillow direct draw)

### Files to Modify
- `lambdas/daily_brief_lambda.py` — add share card generation call after write_public_stats
- `site/index.html` — update OG image URL + add share button

### Deploy Sequence
1. Add `cairosvg` or `Pillow` to the shared Lambda layer (if not already present — check `deploy/p3_build_shared_utils_layer.sh`). Pillow is likely already there.
2. Deploy daily_brief_lambda: `bash deploy/deploy_lambda.sh life-platform-daily-brief`
3. Sync site: `aws s3 cp site/index.html s3://matthew-life-platform/site/index.html --content-type "text/html"`
4. Invalidate CloudFront: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/site/index.html" "/site/share_card.png"`
5. Trigger a daily brief run to generate the first card, OR run `generate_share_card()` manually with test data.

### Acceptance Criteria
- `https://averagejoematt.com/site/share_card.png` returns a 1200×630 PNG with current stats.
- Sharing `https://averagejoematt.com` on Twitter/LinkedIn/Slack shows the dynamic card in the preview.
- Card updates daily when the daily brief runs.
- Share button works on mobile (native share sheet) and desktop (clipboard copy).
- Card is readable — text is legible, not cut off, contrast is good on dark background.

### Gotchas
- `share_card_generator.py` must live alongside `daily_brief_lambda.py` in the Lambda package (or in the shared layer). It's called by import, not as a standalone Lambda.
- `cairosvg` needs `libcairo2` — if the Lambda runtime doesn't have it, use Pillow direct draw instead. Test locally first.
- CloudFront will cache the PNG for up to 1 hour (`max-age=3600`). That's fine — the card updates daily.
- S3 key is `site/share_card.png` — this is a Lambda-generated file. Make sure deploy scripts exclude it from `--delete` syncs (they should already per the S3 sync safety rule).

---

<a name="bl-01"></a>
## 4. BL-01 — For Builders Page

### Status: ✅ ALREADY IMPLEMENTED — REMOVE FROM BACKLOG

**This item is done.** `site/builders/index.html` (704 lines) is live in production with 8 sections:
- Section 00 — Meta-Story ("Who Built This")
- Section 00b — The Partnership ("Claude wrote vs. Matt defined")
- Section 01 — Audience ("Who This Is For")
- Section 02 — Architecture Decisions (8 decision cards)
- Section 03 — The Stack (Python 3.12, CDK, DynamoDB, etc.)
- Section 04 — Lessons Learned (6 patterns with code examples)
- Section 07 — Start Building ("Your First Weekend" 3-step MVP)
- Section 08 — Why the Repo Is Private

Nav integrated via `site/assets/js/nav.js`. Dynamic stats via `data-const` attributes from `site_constants.js`. Confirmed live in handover v4.7.1.

**Original spec below retained for reference only.**
- A separate `FN-01_FIRST_PERSON_BUILD.md` spec was created for a related "First Person" blog page — that is a different page, not this one.
- No implementation exists. `/builders/` returns 404.

### What to Build

**Route**: `/builders/` (create `site/builders/index.html`)

**Design pattern**: Follow the established observatory editorial pattern — 2-column editorial hero, monospace section headers with trailing dash lines, left-accent bordered cards. But lighter on data visualization, heavier on prose. This is a narrative page, not a dashboard.

**Navigation**: Add "For Builders" to the nav. Check `site/assets/js/nav.js` and `site/assets/js/components.js` for the nav structure — it should go under "The Build" dropdown alongside Platform, AI, Tools, etc. Per Decision 34h, consider elevating to top-level nav as a peer to Story and Chronicle.

#### Sections

**Section 01 — The Setup (Hero)**
Narrative hook at top: "A non-engineer built this in 5 weeks. Here's the complete blueprint." (Decision 34f)

Content — first person from Matthew:
- Senior director at a SaaS company, not an engineer
- Built a production health platform with Claude as engineering partner
- Why: personal health transformation + proof-of-concept for enterprise AI adoption
- Tone: honest, specific, zero bullshit. NOT a humble-brag. This is a build log.

**Section 02 — Architecture at a Glance**
Simplified diagram — pull stats dynamically from `site_constants.js` (important per Decision 34b — do NOT hardcode Lambda count, MCP tool count, etc.):
- AWS services used: Lambda, DynamoDB (single-table), S3, CloudFront, SES, EventBridge
- Scale: {lambdas} Lambdas, {mcp_tools} MCP tools, {data_sources} data sources
- Cost: ~$X/month (pull from `COST_TRACKER.md` or `public_stats.json`)
- Architecture style: Compute→Store→Read, pre-compute pipelines, event-driven

**Section 03 — The AI Partnership**
How Claude Code sessions actually work:
- The Board of Directors pattern (Tech Board of 12, Product Board of 8, Health Board of 14)
- Session ritual: handover file → context load → work → handover file → commit
- MCP server as the bridge between conversation and infrastructure
- Prompt engineering patterns that work (be specific, give Claude the full codebase context)

**Section 04 — Patterns That Work**
Distilled from `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`:
- Compute→Store→Read (never query live APIs from the frontend)
- Pre-compute pipelines (daily brief → public_stats.json → static site)
- Shared Lambda layer (one utility layer across all Lambdas)
- ADR-driven decisions (Architecture Decision Records for every significant choice)
- Single-table DynamoDB design
- CI/CD with GitHub Actions (OIDC, manual approval gate)

**Section 05 — What Failed**
Honest list — this is what makes the page credible:
- Manual deploys before CI/CD (human error, forgotten steps)
- S3 `--delete` flag nuking Lambda-generated files (the public_stats.json incident)
- Stale data bugs from caching layers
- Secret management incidents
- MCP tool sprawl (peaked at 120+, now consolidated to ~80)
- Scope creep (observatory pages that took 3x estimated time)

**Section 06 — The Numbers**
Pull from docs and codebase:
- Time invested: X weeks (from git history first commit to today)
- AWS monthly cost (from COST_TRACKER.md)
- Lines of code (run `find . -name "*.py" -o -name "*.html" -o -name "*.js" -o -name "*.css" | xargs wc -l`)
- Git commits (from `git log --oneline | wc -l`)
- MCP tools built
- Data sources integrated
- Architecture reviews completed

**Section 07 — Start Building (CTA)**
NOT the health subscription CTA. Builder-specific:
- "If you're building something similar, I'd love to hear about it."
- Email link to Matthew
- Link to `/platform/` for the full technical deep dive
- Consider: "Get build updates" subscribe variant (but don't build segmented subscriptions yet — that's BL-05, gated on 200 subs)

#### Content Strategy
Claude Code should **scaffold the full page with real section structure and placeholder prose** — Matthew will write the final narrative copy himself. For Sections 02, 04, 05, and 06, Claude Code CAN pull real data from the codebase and docs to populate with accurate numbers and technical details.

For Sections 01, 03, and 07 — write placeholder paragraphs in Matthew's voice (first person, direct, honest) that he can edit. Mark these clearly with `<!-- MATTHEW: Replace with your voice -->` comments.

### Files to Create
- `site/builders/index.html` — NEW full page

### Files to Modify
- `site/assets/js/nav.js` or `site/assets/js/components.js` — add Builders to nav
- `site/assets/js/site_constants.js` — verify it has all stats referenced by the page (Lambda count, MCP tool count, data source count)

### Deploy
```bash
aws s3 cp site/builders/index.html s3://matthew-life-platform/site/builders/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/builders/*" "/assets/js/*"
```

### Acceptance Criteria
- `/builders/` loads with all 7 sections.
- Dynamic stats pull from `site_constants.js` (no hardcoded counts — Decision 34b is CRITICAL).
- Page matches the platform's design language (dark theme, monospace headers, editorial layout).
- Nav includes For Builders link.
- Breadcrumb: "The Build > For Builders" (Decision 34c).
- Reading path nav present (Decision 34d).
- Builder-specific CTA, NOT health subscription (Decision 34e).
- Mobile responsive — especially any multi-column sections (Decision 34g).
- `<!-- MATTHEW: Replace with your voice -->` comments on sections needing his prose.

### Gotchas
- Do NOT hardcode Lambda count, MCP tool count, or any platform stats as literals. Use `data-const` attributes or `site_constants.js` values. The offsite review flagged number inconsistency across pages as CRITICAL (Decision 34b).
- The builders page is for a TECHNICAL audience (developers, PMs, HN readers). Tone is different from the health pages — more matter-of-fact, more technical detail, fewer emotional hooks.
- Check `site/assets/css/tokens.css` and `site/assets/css/base.css` for the design system — don't invent new colors or spacing.

---

<a name="bl-02"></a>
## 5. BL-02 — Bloodwork/Labs Page

### Status: ✅ ALREADY IMPLEMENTED — REMOVE FROM BACKLOG

**This item is done.** Frontend and backend are both complete:
1. **Frontend** (`site/labs/index.html`) — hero stats, accordion biomarker categories (74 biomarkers, 18 categories), flagged values section, "What I'm Doing About It" action cards, AI expert analysis, staleness warning.
2. **API** (`/api/labs` in `site_api_lambda.py:6222`) — reads `dashboard/{user}/clinical.json` from S3, returns lab biomarkers with 1hr cache.
3. **Data pipeline** (`output_writers.py:write_clinical_json`) — generates `clinical.json` daily at 11 AM via daily brief Lambda.
4. **IAM fix** (v5.1.0) — added `dashboard/*` S3 read to site-api role (was causing 503).

**Original spec below retained for reference only.**
- Product Board spec in `docs/HOME_EVOLUTION_SPEC.md` (lines 313–330).

### What to Build

**Route**: `/labs/` (create `site/labs/index.html`)

**Design pattern**: Observatory editorial — same as Nutrition/Training/Inner Life pages. 2-column editorial hero with animated SVG gauge ring showing overall lab health score. Monospace section headers. Data spreads. Evidence badges.

#### Step 1: Public API Endpoint

Add a `/api/labs` route to `lambdas/site_api_lambda.py`:

```python
# Route: GET /api/labs
# Returns: Latest panel results + trends for public display
# Privacy: Only return biomarker names, values, ranges, and status — no PII
def handle_labs(params):
    # Query DynamoDB for LAB# items
    # Group by draw date
    # For each biomarker, include:
    #   - name, value, unit
    #   - reference_range (lab "normal")
    #   - optimal_range (longevity-optimal per Attia/Patrick)
    #   - status: "optimal" | "normal" | "out_of_range" | "critical"
    #   - trend: "improving" | "stable" | "declining" (if 2+ draws)
    # Return structured JSON
```

**Key**: Look at how `mcp/tools_labs.py` and `mcp/labs_helpers.py` query and format lab data. The public API should return a subset of what the MCP tools return — no raw clinical IDs, no provider metadata beyond the draw date.

#### Step 2: Page Sections

**Hero**: "Latest Bloodwork" — date of most recent draw, count of biomarkers tested, count in optimal range vs out of range. Animated gauge ring showing % in optimal range.

**Section 01 — Latest Panel**
Most recent blood draw results in a clean table/grid:
- Biomarker name
- Value + unit
- Status indicator (green/amber/red dot)
- Lab normal range vs longevity-optimal range (side by side — this is the unique value per Lena)
- Group by category: Metabolic, Lipids, Hormonal, Inflammation, Nutrients, Liver, Kidney, Thyroid, etc.

**Section 02 — Trends Over Time**
If 2+ draws exist, show trend arrows and mini sparklines per biomarker. Highlight biomarkers that improved or worsened between draws.

**Section 03 — Optimal vs Normal**
Educational callout: explain that "normal" lab ranges are based on population averages (which include unhealthy people), while "optimal" ranges target longevity. Source: Attia's "Outlive" framework, Patrick's research, Bryan Johnson's Blueprint reference ranges.

This section should have a design treatment — maybe a side-by-side visual showing how "normal" is a wide band and "optimal" is a narrow target within it.

**Section 04 — Protocol Links**
For each out-of-range biomarker, link to the supplement or protocol targeting it. The protocol data is in DynamoDB (protocols were migrated in a prior session). Cross-link using the biomarker name.

Example: "Vitamin D: 28 ng/mL (below optimal 40-60) → Protocol: D3+K2 5000IU daily"

**Section 05 — Methodology Note**
N=1 disclaimer. Lab values are individual, not medical advice. Henning Brandt standard applies: correlations are correlative, not causal. Link to full methodology page.

#### Step 3: Navigation

Add "Labs" or "Bloodwork" to the nav under the observatory section (alongside Sleep, Glucose, Nutrition, Training, Inner Life).

### Files to Create
- `site/labs/index.html` — NEW full page

### Files to Modify
- `lambdas/site_api_lambda.py` — add `/api/labs` route
- `site/assets/js/nav.js` or `site/assets/js/components.js` — add Labs to nav

### Reference Files (read these before building)
- `mcp/tools_labs.py` — see how lab data is queried and formatted
- `mcp/labs_helpers.py` — helper functions for lab data processing, optimal ranges, categorization
- `site/observatory/nutrition/index.html` — design pattern reference (editorial hero, gauge ring, sections)
- `site/observatory/training/index.html` — design pattern reference
- `site/observatory/innerlife/index.html` — design pattern reference (most recent, best example)

### Deploy
```bash
bash deploy/deploy_lambda.sh life-platform-site-api
aws s3 cp site/labs/index.html s3://matthew-life-platform/site/labs/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/labs/*" "/api/labs*"
```

### Acceptance Criteria
- `/labs/` loads with lab data from DynamoDB (107 biomarkers from 2 draws).
- Each biomarker shows value, status, normal range, and optimal range.
- Biomarkers grouped by category.
- Trends visible between Draw 1 (33 markers) and Draw 2 (74 markers) where both measured the same biomarker.
- Page matches observatory editorial design pattern.
- Mobile responsive.
- N=1 disclaimer present.
- Nav includes Labs link.

### Gotchas
- The lab data in DynamoDB was seeded from Function Health results. Check `mcp/labs_helpers.py` for the exact PK/SK format — it's likely `USER#matthew / LAB#YYYY-MM-DD#biomarker_name` or similar.
- Optimal ranges are likely defined in `labs_helpers.py` — don't reinvent them. Import or reference the same data.
- site-api Lambda is in **us-west-2**. Deploy with `deploy_lambda.sh`.
- Don't expose raw lab report PDFs or provider-specific identifiers on the public page.

---

<a name="get-nutrition-bug"></a>
## 6. get_nutrition — Positional Args Bug

### Status
- Carried forward across multiple sessions as a known bug.
- The `get_nutrition` tool is a dispatcher (line 628 of `mcp/tools_nutrition.py`) that routes to `tool_get_nutrition_summary`, `tool_get_macro_targets`, `tool_get_meal_timing`, or `tool_get_micronutrient_report` based on the `view` parameter.
- The handler in `mcp/handler.py` (line 88) passes `arguments` as a dict: `TOOLS[name]["fn"](arguments)`.
- All sub-functions accept `args` as a dict and use `args.get(...)`.
- **From code audit**: The dispatch chain looks correct. The bug may be intermittent, edge-case, or already fixed.

### What to Do

**Task A: Write a reproduction test**

Create `tests/test_get_nutrition_args.py`:

```python
"""
Reproduce the get_nutrition positional args bug.
Test that all view dispatches work with various argument combinations.
"""
import pytest
from mcp.tools_nutrition import tool_get_nutrition

def test_nutrition_no_args():
    """Default view with no arguments should not crash."""
    result = tool_get_nutrition({})
    assert "error" not in result or "Need" in result.get("error", "")  # data-dependent errors OK

def test_nutrition_summary_view():
    result = tool_get_nutrition({"view": "summary"})
    assert isinstance(result, dict)

def test_nutrition_macros_view():
    result = tool_get_nutrition({"view": "macros"})
    assert isinstance(result, dict)

def test_nutrition_meal_timing_view():
    result = tool_get_nutrition({"view": "meal_timing"})
    assert isinstance(result, dict)

def test_nutrition_micronutrients_view():
    result = tool_get_nutrition({"view": "micronutrients"})
    assert isinstance(result, dict)

def test_nutrition_with_dates():
    result = tool_get_nutrition({
        "view": "summary",
        "start_date": "2026-03-01",
        "end_date": "2026-03-31"
    })
    assert isinstance(result, dict)

def test_nutrition_macros_with_overrides():
    result = tool_get_nutrition({
        "view": "macros",
        "calorie_target": 2200,
        "protein_target": 200,
        "days": 14
    })
    assert isinstance(result, dict)

def test_nutrition_invalid_view():
    result = tool_get_nutrition({"view": "invalid"})
    assert "error" in result
    assert "valid_views" in result
```

**Task B: Run the tests**

```bash
python3 -m pytest tests/test_get_nutrition_args.py -v
```

If all tests pass → the bug is likely already fixed or was transient. Remove from backlog and note in CHANGELOG.

If a test fails with a positional argument error → the traceback will show exactly where the bug is. Fix it.

**Task C: Common positional arg bug patterns to check**

1. **Function signature mismatch**: A sub-function might have been refactored to take positional args instead of a dict. Check that ALL of these accept `(args)` as a single dict parameter:
   - `tool_get_nutrition_summary(args)` (line 398)
   - `tool_get_macro_targets(args)` (line 484)
   - `tool_get_meal_timing(args)` (line 163)
   - `tool_get_micronutrient_report(args)` (line 70)

2. **Import shadowing**: If any other module re-exports `tool_get_nutrition` with a different signature.

3. **MCP protocol level**: The handler extracts `arguments` from `params.get("arguments", {})` (handler.py line 65). If the MCP client sends arguments as a list instead of a dict, the `args.get(...)` calls would fail. Check if Claude Desktop or the MCP bridge ever sends positional args.

### Files to Create
- `tests/test_get_nutrition_args.py` — NEW

### Files to Inspect (read-only unless bug found)
- `mcp/tools_nutrition.py` — all function signatures
- `mcp/handler.py` — argument extraction (line 65)
- `mcp_bridge.py` — check how it passes arguments to the handler

### Acceptance Criteria
- All 8 test cases pass.
- If a bug is found and fixed: CHANGELOG entry + commit message explaining the root cause.
- If no bug found: note in CHANGELOG "get_nutrition positional args: tested, no reproduction — closing carry-forward."

---

## Implementation Priority Order

1. **HP-12** — Just remove from backlog (5 min)
2. **get_nutrition bug** — Write tests, run them, close or fix (30 min)
3. **DISC-7 seed** — Verify tools, write seed script, seed data (1-2 hours)
4. **BL-02 Labs page** — API endpoint + page build (half day)
5. **BL-01 Builders page** — Full page scaffold (half day)
6. **HP-13 Share card** — New module + daily brief integration (half day)

## Deploy Safety Reminders

- NEVER use `aws s3 sync --delete` against bucket root or `site/`.
- All Lambda deploys via `bash deploy/deploy_lambda.sh <lambda-name>`.
- MCP Lambda (`life-platform-mcp`): manual zip deploy only — `deploy_lambda.sh` will FATAL if passed this name.
- Wait 10s between sequential Lambda deploys.
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.
- CloudFront invalidation: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/path/*"`
- `site_writer.py` lives in the shared Lambda layer — changes require layer rebuild + reattach.

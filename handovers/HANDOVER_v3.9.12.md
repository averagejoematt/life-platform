# Handover — v3.9.12 (2026-03-25)

> Prior: handovers/HANDOVER_v3.9.11.md

## SESSION SUMMARY
Product Board convened twice: first to overhaul the Habits page ("The Operating System"), then the Supplements page ("The Pharmacy"). Both pages received complete rewrites driven by Product Board recommendations. Habits page restructured from 65-item flat list to a 3-zone behavioral architecture. Supplements page rebuilt with evidence-first visual hierarchy and a "no affiliate links" positioning.

## WHAT CHANGED

### site/habits/index.html (COMPLETE REWRITE — "The Operating System")

**Structural overhaul:**
- Renamed from "Habit Observatory" → "The Operating System"
- Three-zone architecture: Foundation (T0) → System (T1) → Horizon (T2)
- 21 supplement habits removed (live on /supplements/ page)
- 7 hygiene habits removed (maintenance, not transformation)
- Visible habit count: 65 → ~37 behavioral habits
- Purpose-grouped Tier 1 with collapsible accordions: Sleep Architecture, Training Engine, Fuel & Metabolic, Mind & Growth, Discipline Gates, Data Signals

**Visual identity:**
- SVG circular progress rings on every T0 habit card
- 30-day sparklines on T0 cards
- "The Why" quotes from habit registry `why_matthew` field
- Science rationale + evidence strength badges (strong/moderate/emerging)
- Tier-based color banners with glowing dots (green T0, amber vices, muted T1, faded T2)
- Faded/locked horizon cards with lock icons for T2
- Vice Discipline Gates elevated to own section
- Daily Pipeline visualization showing morning→evening stack flow

**Growth:**
- SEO meta tags: "habit system", "gamify health", "RPG habits"
- Reading path → Character page

**No new API endpoints** — uses existing /api/habits + /api/vice_streaks + /api/habit_streaks

### site/supplements/index.html (COMPLETE REWRITE — "The Pharmacy")

**Structural overhaul:**
- Renamed from "Supplement Protocol" → "The Pharmacy"
- Purpose-grouped layout: Longevity Foundation (6) → Muscle & Performance (5) → Metabolic & Body Comp (3) → Sleep Architecture (4) → Cognitive Support (3)
- All 21 supplements with full metadata from habit registry

**Visual identity:**
- Evidence confidence rings on every card (A/B/C rating, proportional fill, color-coded)
- Left border color codes evidence: green=strong, amber=moderate, gray=emerging
- "No affiliate links · No sponsorships · No brand promotions · Just the data" integrity banner
- Per-card badges: timing, board member (who recommended it), synergy group, genome SNP
- Expandable "Why I take it" (open by default) + collapsible "What the science says"
- "What I'm watching" footer on every card (expected impact + validation metric)

**Unique sections:**
- Genome-Informed section with 3 SNPs (VDR Bsm1, FADS2 rs1535, SLC39A4)
- "Supplements I'm Questioning" honest assessment section (7 items with candid reasons)

**No new API endpoints** — page renders from embedded registry data (client-side)

## DEPLOYED
```bash
# Habits page
aws s3 cp site/habits/index.html s3://matthew-life-platform/site/habits/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/habits/*"

# Supplements page
aws s3 cp site/supplements/index.html s3://matthew-life-platform/site/supplements/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/supplements/*"
```

## BUGS FIXED IN-SESSION
- Habits page: `reveal` class on dynamically-generated T0 cards caused them to be invisible (IntersectionObserver already fired before JS injected cards). Fixed by removing `reveal` from JS-generated elements.
- Supplements page: `create_file` tool wrote to Claude's container, not Matthew's Mac. Workaround: download from outputs attachment.
- Deploy script: `aws s3 sync --delete` flag is dangerous — can delete S3-only config files. Changed to targeted `aws s3 cp` for single-file deploys.

## LEARNINGS
- `create_file` writes to Claude's Linux container filesystem, NOT to Matthew's Mac. Use `Filesystem:write_file` for Mac writes or present_files for download.
- `sed -i ''` on macOS requires different escape patterns than Linux — escaped quotes in sed patterns don't match actual file content. Use simple unquoted patterns.
- `aws s3 sync --delete` should NOT be used for single-page deploys — risk of deleting S3-only files (config/, findings/, etc.). Use `aws s3 cp` for targeted file uploads.
- `reveal` class should only be on static HTML elements, never on dynamically JS-injected content.

## PENDING / CARRY FORWARD
- **Supplements page needs Matthew to download and deploy** — file was presented via outputs attachment, needs manual copy + s3 cp
- **CHANGELOG update**: Prepend v3.9.12 entry (content below)
- **sync_doc_metadata.py**: Run `--apply` after changelog update
- **WEBSITE_REDESIGN_SPEC.md**: Note habits + supplements overhauls
- **Git commit**: `git add -A && git commit -m "v3.9.12: Habits + Supplements page overhauls" && git push`
- **CHRON-3/4**: Chronicle generation fix + approval workflow
- **G-8**: Privacy page email confirmation
- **SIMP-1 Phase 2 + ADR-025 cleanup**: ~Apr 13
- **Withings OAuth**: No weight data since Mar 7

## PRODUCT BOARD RATIONALE (for future reference)

### Habits page:
- **Three-zone model**: Raj — "37 behaviors in 3 tiers is comprehensible. 65 checkboxes is overwhelming."
- **Remove supplements**: Mara — "21 supplements are noise on this page. They deserve their own page."
- **Purpose groups**: Tyrell — "Group by what the habit does for you, not by Habitify category."
- **Faded horizon**: Jordan — "Locked cards create aspiration. Visitors think 'what else is coming?'"
- **Pipeline viz**: Sofia — "Shows the daily routine flows — this is the operating manual."

### Supplements page:
- **No-affiliate banner**: Sofia — "This is your credibility weapon. The anti-influencer positioning."
- **Evidence rings**: Lena — "Creatine (30 years of RCTs) should feel different from Reishi (traditional use only)."
- **Board member badges**: Ava — "'Recommended by: Huberman' feels authoritative without being promotional."
- **Honest assessment**: Jordan — "The transparency section no one else would publish. That's shareability."
- **Group ordering**: Matthew — "Lead with longevity/muscle (strongest evidence), sleep/cognitive last."

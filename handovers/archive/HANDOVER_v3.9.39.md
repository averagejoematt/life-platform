# Handover v3.9.39 — Pre-Launch Sweep + Catalog Expansion

**Date**: 2026-03-27
**Session focus**: Action plan consolidation, nav fixes, mobile scroll fix, subscribe verification, baseline capture, challenge/experiment catalog expansion

---

## What Shipped

### Nav Rename (Product Board Consensus)
- "The Arena" → "Challenges" in all 3 nav locations (desktop, footer, science relationship map)
- "Active Tests" → "Experiments" in all nav locations
- File: `site/assets/js/components.js`

### Mobile Menu Scroll Fix
- **CSS** (`base.css`): Added `overflow-y: auto`, `-webkit-overflow-scrolling: touch`, `overscroll-behavior: contain` to `.nav-overlay`
- **JS** (`nav.js`): iOS scroll lock via `position: fixed` on body with scroll position save/restore
- Bug: hamburger menu overlay was static while page behind scrolled on mobile

### Subscribe Flow Verified
- Lambda invoked directly: confirmation email sent via SES ✅
- SES: production mode, domain verified, 50K/day quota
- email-subscriber Lambda: active, correctly configured

### Baseline Capture Script
- Created `deploy/capture_baseline.sh` — snapshots Character Sheet, daily data, habits, vice streaks → writes to `platform_memory` as `journey_milestone`
- **Already run once** (pre-April 1 test) — run again on actual April 1 morning for real Day 1 baseline

### Challenge Catalog Expansion: 34 → 66
- +5 sleep (Lights Out by 10, Noon Caffeine Cutoff, Cave Mode, The Ritual, First Light)
- +7 movement (Heat Therapy/sauna, Cold Steel, Couch to 5K, Zone 2 Machine, Limber Up, Post-Meal Walk, Grip of Steel)
- +5 nutrition (Sugar Free, Time-Restricted Eating, Prep Day, Water Works, Veggies First)
- +5 mind (Box Breathing, Structured Journal, 10 Minutes Still, Forest Bath, Worry Window)
- +5 social (Present Meals, Reach Back, Open Up, Find Your Tribe, Daily Thanks)
- +5 discipline (Clear Mind, Eyes Forward, Kitchen Only, Clockwork, Dopamine Reset)
- Files: `seeds/challenges_catalog.json` + S3 `config/challenges_catalog.json`

### Experiment Library Expansion: 58 → 71
- +2 movement (sauna protocol, cold plunge)
- +3 mental (Pennebaker expressive writing, Three Good Things, morning pages)
- +2 social (deep conversation weekly, stranger conversations)
- +2 supplements (creatine timing, magnesium for sleep)
- +2 nutrition (fiber-first meals, dairy elimination)
- +1 sleep (bulletproof sleep schedule)
- +1 discipline (dopamine reset weekend)
- Files: `config/experiment_library.json` + S3

### Action Plan Document
- Created `docs/ACTION_PLAN_APRIL_LAUNCH.md` — 23 items across 4 phases (pre-launch, week 1, weeks 2-4, strategic)
- Consolidates all carry-forwards, board recommendations, and undone items from last 10 sessions

### Phase B Visual Prompt Package
- Created comprehensive prompt file for Recraft/Midjourney (avatar, badges, heroes, portraits)
- Board-recommended generation order: avatar → heroes → badges → portraits

---

## Deploy Sequence (Already Run)

```bash
# Nav + scroll fix
aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js
aws s3 cp site/assets/css/base.css s3://matthew-life-platform/site/assets/css/base.css
aws s3 cp site/assets/js/nav.js s3://matthew-life-platform/site/assets/js/nav.js

# Catalog expansion
aws s3 cp seeds/challenges_catalog.json s3://matthew-life-platform/config/challenges_catalog.json
aws s3 cp config/experiment_library.json s3://matthew-life-platform/config/experiment_library.json

# CloudFront invalidation
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/js/*" "/assets/css/*"

# Git
git add -A && git commit -m "v3.9.39: ..." && git push  # ceb672f
```

---

## Warmup Script Flags

Two endpoints returned non-200:
- `/api/character_stats` → **503** — possible cold start timeout or data issue. Check CloudWatch before April 1.
- `/api/subscriber_count` → **405** — likely GET not mapped (POST only?). Not user-facing unless widget calls it.

---

## Current State

- **Platform version**: v3.9.39
- **66 challenges** in catalog (was 34)
- **71 experiments** in library (was 58)
- **105 MCP tools, 52 Lambdas, 19 data sources**
- Baseline captured in DynamoDB (`journey_milestone#2026-04-01`)

---

## Before April 1 (Matthew)

1. ⬜ **Test subscribe in browser** — go to averagejoematt.com/subscribe/, enter real email, verify full flow
2. ⬜ **Check `/api/character_stats` 503** — CloudWatch logs for site-api
3. ⬜ **March 31 11:55 PM**: `bash deploy/warmup_lambdas.sh`
4. ⬜ **April 1 morning**: `bash deploy/capture_baseline.sh` (real Day 1 data)

---

## On the Horizon (from ACTION_PLAN_APRIL_LAUNCH.md)

### Post-Launch Week 1
- Challenge catalog brainstorm with board (even more entries)
- Experiment library expansion (more social, supplement timing)
- `/live/` page sparklines + count-up animations
- HP-12: elena_hero_line in public_stats

### Post-Launch Weeks 2-4
- Sleep + Glucose observatory visual overhaul
- observatory.css consolidation
- HP-13: share card Lambda + dynamic OG image
- Phase B visual work (avatar, heroes, rich badges)
- Podcast scanner Lambda creation in AWS
- Challenge auto-completion trigger
- Phase E: more auto-metrics for challenge verification

### Strategic
- SIMP-1 Phase 2 + ADR-025 (~April 13)
- Interactive architecture SVG
- WR-18: Build Your Own guide (~June)
- BL-01: Builders page expansion
- BL-02: Bloodwork/Labs observatory

---

## Files Created/Modified This Session

### Created
- `deploy/capture_baseline.sh` — Day 1 baseline capture script
- `docs/ACTION_PLAN_APRIL_LAUNCH.md` — consolidated action plan (23 items, 4 phases)

### Modified
- `site/assets/js/components.js` — nav rename (Arena→Challenges, Active Tests→Experiments)
- `site/assets/css/base.css` — mobile overlay scroll fix
- `site/assets/js/nav.js` — iOS body scroll lock
- `seeds/challenges_catalog.json` — expanded 34→66
- `config/experiment_library.json` — expanded 58→71

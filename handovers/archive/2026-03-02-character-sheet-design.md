# Handover — 2026-03-02 — Character Sheet Design Complete (v2.58.0 Design)

## Session Summary
Designed and Board-reviewed the Character Sheet feature — a gamified life scoring system with persistent Character Level (1-100), 7 weighted pillars, XP accumulation, tier system, and cross-pillar effects. Full spec written, PROJECT_PLAN and CHANGELOG updated. No code deployed — design only.

## Version
v2.58.0 (design complete, build pending)

## What Was Created

### Feature Spec: `docs/archive/SPEC_CHARACTER_SHEET.md`
Comprehensive spec covering:
- **7 pillars** with Board-approved weights: Sleep (20%), Movement (18%), Nutrition (18%), Mind (15%), Metabolic Health (12%), Consistency (10%), Relationships (7%)
- **Each pillar** has 4-6 weighted components mapped to existing data sources
- **Scoring engine:** 21-day exponentially-weighted rolling average (lambda=0.85), percentile-based against own history
- **Anti-flip-flop rules:** Level UP requires 5 consecutive days above threshold. Level DOWN requires 7 consecutive days below threshold. Tier transitions: 7 up / 10 down. Target: ~2-4 level events/month, tier transitions every 2-3 months per pillar.
- **5 tiers:** Foundation (1-20), Momentum (21-40), Discipline (41-60), Mastery (61-80), Elite (81-100)
- **XP system:** +3/+2/+1/0/-1 XP based on raw_score bands
- **Cross-pillar effects:** Sleep Drag, Training Boost, Focus Buff, Synergy Bonus, Alignment Bonus, Vice Shield
- **Nutrition pillar** includes 40% body composition sub-score that tracks weight toward 185lb goal
- **Metabolic Health** includes lab biomarker decay (full value 30 days, linear decay to 50% over next 60 days)
- **Communication:** Daily Brief section, Weekly Digest summary, dashboard radar chart, buddy page, Chronicle narrative hooks
- **Milestones:** System-defined (level up/down, tier transitions) + future user-defined rewards

### Board Review — All 12 Members Provided Input
Key design decisions from Board review:
- **Maya Rodriguez:** Insisted on asymmetric leveling (stronger buffer against level-down) + rare level events (~2-4/month)
- **Lisa Park:** Required cross-pillar Sleep Drag debuff (Sleep <35 → Movement -8%, Mind -5%)
- **Okafor:** Required 14+ day rolling windows, no snapshot-based scoring
- **Attia:** Approved unequal pillar weights reflecting longevity science
- **Huberman:** Wants protocol recommendations tied to tier levels
- **Elena Voss:** Will use tier transitions as Chronicle narrative moments

### Technical Architecture
- **DynamoDB:** `USER#matthew#SOURCE#character_sheet` / `DATE#YYYY-MM-DD`
- **Computation:** Inside Daily Brief Lambda (already has all data)
- **New utility:** `character_engine.py` (bundled like board_loader.py)
- **New MCP module:** `mcp/tools_character.py` — 3 tools (get_character_sheet, get_pillar_detail, get_level_history)
- **Tool count:** 102 → 105
- **Cached tools:** 12 → 13
- **Cost:** $0 incremental

## Docs Updated
- **`docs/archive/SPEC_CHARACTER_SHEET.md`** — NEW — full feature spec
- **`docs/PROJECT_PLAN.md`** — Added #26 Character Sheet as Tier 1 top priority
- **`docs/CHANGELOG.md`** — v2.58.0 design entry

## Build Plan (4 Phases)

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | `character_engine.py` + DynamoDB writes + 3 MCP tools + retrocompute backfill | 6-8 hr |
| 2 | Daily Brief email integration + level-up events + Board commentary | 3-4 hr |
| 3 | Dashboard radar chart + buddy page + Chronicle hooks | 4-6 hr |
| 4 | User-defined rewards + protocol recommendations + Weekly Digest | 3-4 hr |

## What's Next
- **Phase 1 build session:** Start with `character_engine.py` — the scoring engine that computes all 7 pillars from existing data
- **Decision needed:** Backfill to 2023-07-23 (full day_grade range) or more recent date? Earlier dates have sparser data.
- **Decision needed:** Store pillar weights in `config/profile.json` (editable via MCP) or hardcode in engine?
- **v2.57.0 verification still pending:** Tomorrow's Daily Brief (10am PT) → check CloudWatch for `config-driven` log line

## Resolved Questions (this session)
1. **Baseline:** 2026-02-22 (journey start date from profile.json), Level 1 for all pillars. Weight: 302lb starting, 185lb goal. Retrocompute forward from Feb 22, day by day.
2. **Config:** `s3://matthew-life-platform/config/character_sheet.json` — all weights, thresholds, tiers, effects. Editable via MCP.
3. **Avatar:** Pixel-art RPG character based on Matthew's reference photo. 5 tier variants with progressive visual upgrades. 7 pillar badge overlays that appear at Discipline+ tier. Active effect indicators (Sleep Drag ZZZ, Synergy lightning, etc.). Pre-generated PNGs, CSS-composited on dashboard. Phase 3 deliverable.

## Remaining Open Questions
1. Notification channel — Daily Brief only vs additional push
2. Brittany email inclusion
3. Avatar generation method — AI image tools vs commissioned art
4. Sparse data handling — neutral score (40) vs last known value

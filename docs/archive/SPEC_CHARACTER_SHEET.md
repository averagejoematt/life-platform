# Feature Spec: Character Sheet — Gamified Life Score

**Version:** 0.1 (Design Review)
**Author:** Claude + Board of Directors
**Date:** 2026-03-02
**Target Version:** v2.58.0 (multi-session build)
**Status:** Design approved — ready to build

---

## 1. Concept

The Character Sheet is a persistent, gamified scoring system that distills Matthew's entire health platform into a single "Character Level" (1–100) composed of weighted pillar scores. Unlike the ephemeral day grade (resets daily), the Character Level represents a slow-moving, trajectory-based assessment of overall life optimization.

**Core metaphor:** You are the character. The pillars are your stats. The data is your XP. Level up by consistently living well — not by having one great day.

**Design goal:** The closer to 100, the more aligned your actual behavior is with the life the Board of Directors believes will make you happy, healthy, and fulfilled at 36, 46, 56, and 66.

---

## 2. Board of Directors Design Review

### 🎯 The Chair — APPROVED with emphasis

"This is the motivational layer we've been missing. The day grade tells Matthew how yesterday went. The Weekly Digest tells him how the week went. But neither answers: *am I actually becoming the person I want to be?* The Character Sheet answers that question with a single number. My one non-negotiable: the Consistency pillar must exist. Without it, Matthew will game the system with hero days."

### 🧠 Coach Maya Rodriguez — STRONG ADVOCATE

"This is behavioral design done right. Three things I insist on:

1. **Asymmetric movement.** Leveling up should require 5+ days of sustained performance above threshold. Leveling DOWN should require 7+ days of sustained decline. The asymmetry buffers against loss aversion — which is 2x stronger than the motivation from gains. If the score flip-flops, it becomes metric fatigue, not motivation.

2. **Level-up events must be rare and meaningful.** If someone levels up every other day, the dopamine hit disappears. The system should produce roughly 2-4 level-up events per MONTH across all pillars combined. That makes each one feel like an achievement. The tier boundaries (Foundation → Momentum → Discipline → Mastery → Elite) should trigger even more rarely — maybe once every 2-3 months per pillar.

3. **No punishment framing.** A level-down should never feel like failure. Frame it as 'your Sleep pillar needs attention — it's drifted from Discipline back to Momentum.' The Board should address it in Daily Brief as a coaching moment, not a red flag."

### 😴 Dr. Lisa Park — APPROVED with cross-pillar requirement

"Sleep must have outsized influence, and not just on its own pillar. Sustained poor sleep (pillar below 35) should apply a visible debuff to Movement and Mind. This models reality — you cannot out-train or out-habit bad sleep. The debuff should appear in the Daily Brief as a named effect: 'Sleep Drag: -8% to Movement, -5% to Mind.' This creates strategic thinking: 'I need to fix sleep before anything else can improve.'"

### 🏋️ Dr. Sarah Chen — APPROVED with zone weighting

"Movement can't just be 'did you exercise.' It needs to reflect training quality. I want Zone 2 adequacy and training load balance (TSB) to be weighted components. Someone who runs 60 miles a week but never does Zone 2 shouldn't score as high as someone with a polarized, periodized program. Volume matters less than structure."

### 🥗 Dr. Marcus Webb — APPROVED with composition integration

"Matthew's right that the 185lb goal should factor into Nutrition. I'd structure it as: 60% behavior (adherence, protein, consistency) + 40% outcome (body composition trajectory toward 185lb). This way, you get rewarded for doing the right things even before the scale moves — but the scale moving is the ultimate validation. As he approaches 185 and transitions to maintenance, the 40% shifts from 'progress toward goal' to 'maintenance stability.'"

### 🩺 Dr. James Okafor — APPROVED with trajectory emphasis

"Every pillar score must use a minimum 14-day rolling window with exponential decay. Snapshots lie. What I want to see in the architecture: each daily computation produces a `raw_score` (today's inputs only) and a `level_score` (the smoothed, trajectory-weighted value that determines your actual level). The raw score feeds into the level score but never directly determines level changes. This prevents the flip-flopping Matthew is worried about."

### 📊 Dr. Peter Attia — APPROVED with unequal weighting

"These pillars do not contribute equally to healthspan. Sleep and Movement are the two strongest predictors of all-cause mortality. Metabolic Health captures the four horsemen risk profile. The weights should reflect the science. I'd also add: grip strength as a sub-metric in Movement once that tracking is live — it's the strongest single predictor after VO2max."

### 🔬 Dr. Andrew Huberman — APPROVED, wants protocol connection

"Every level-up and level-down should come with a protocol recommendation. Dropped in Sleep? Here's the specific Huberman protocol: morning sunlight within 30 min of waking, NSDR at 2pm, no screens after 9pm. The Character Sheet shouldn't just score — it should prescribe. Each pillar's tier should unlock or recommend specific zero-cost protocols."

### 🧬 Dr. Rhonda Patrick — APPROVED, wants biomarker integration

"Metabolic Health should weight lab results heavily when available. A recent blood panel showing improving ApoB or fasting glucose should give a meaningful boost. Labs are ground truth — they're the deepest signal we have. But since labs are quarterly at best, the pillar needs to gracefully handle 90-day gaps between measurements."

### ✍️ Elena Voss — APPROVED with narrative framing

"'Level 47 Matthew' is a character I can write. Tier transitions become Chronicle moments. I can see the installment now: 'The week Matthew's Movement pillar crossed into Mastery.' This gives me narrative anchors beyond just what happened — it gives me what it MEANS in the longer arc."

---

## 3. Pillar Architecture (7 Pillars)

### 3.1 Sleep (Weight: 20%)
**Owner:** Dr. Lisa Park + Dr. Matthew Walker
**Data sources:** Whoop (SOT), Eight Sleep (environment)

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Sleep duration vs target | 25% | Whoop | `total_sleep_seconds` vs profile target (7.5h) |
| Sleep efficiency | 20% | Whoop | `sleep_performance` |
| Deep sleep % | 20% | Whoop | Deep sleep ratio (target ≥15%) |
| REM % | 15% | Whoop | REM ratio (target ≥20%) |
| Consistency (onset variance) | 20% | Whoop | Std dev of `sleep_start` over 14 days |

**Cross-pillar effect:** Sleep level <35 applies debuff: Movement -8%, Mind -5%. Named "Sleep Drag" in Daily Brief.

### 3.2 Movement (Weight: 18%)
**Owner:** Dr. Sarah Chen
**Data sources:** Strava, Whoop, Garmin, Apple Health

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Training frequency | 20% | Strava | Sessions/week vs target |
| Zone 2 adequacy | 25% | Strava/Garmin | Weekly Zone 2 minutes vs 150min target |
| Training load balance | 20% | Derived | TSB (fitness - fatigue) in healthy range |
| Progressive overload | 15% | Strava/Hevy | CTL trend (rising = good) |
| Movement diversity | 10% | Strava | Activity type variety (run, hike, strength, ruck) |
| Daily steps | 10% | Apple Health | Steps vs 8000 target |

### 3.3 Nutrition (Weight: 18%)
**Owner:** Dr. Marcus Webb + Dr. Layne Norton
**Data sources:** MacroFactor, Withings

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Calorie adherence | 20% | MacroFactor | Daily cals within ±10% of target |
| Protein total | 20% | MacroFactor | Daily protein vs 190g target |
| Protein distribution | 10% | MacroFactor | Meals with ≥30g protein (target: 4+) |
| Consistency (no blowouts) | 10% | MacroFactor | Days in range / total days (14d window) |
| Body composition progress | 40% | Withings | Smooth curve from current weight → 185lb goal |

**Phase transition:** When weight goal reached and profile shifts to maintenance, the 40% composition component shifts from "progress toward 185" to "stability within ±3lb of 185."

### 3.4 Metabolic Health (Weight: 12%)
**Owner:** Dr. Peter Attia + Dr. Rhonda Patrick
**Data sources:** Withings, Apple Health, Labs, DEXA, CGM

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Body fat trajectory | 25% | Withings/DEXA | Trending toward target (20-22% BF) |
| CGM glucose control | 25% | Apple Health CGM | Time in range (70-140), fasting glucose proxy |
| Lab biomarkers | 30% | Labs | Composite of key markers (ApoB, HbA1c, fasting glucose, lipids) — uses most recent, decays over 90 days |
| Blood pressure | 10% | Apple Health | Systolic/diastolic within normal range |
| Resting heart rate trend | 10% | Whoop | RHR trending down or stable at healthy level |

**Lab decay:** Lab scores hold full value for 30 days after draw, then decay linearly to 50% over the next 60 days. This incentivizes regular testing without penalizing normal testing cadence.

### 3.5 Mind (Weight: 15%)
**Owner:** Coach Maya Rodriguez + Dr. Andrew Huberman
**Data sources:** Habitify, Notion journal, State of Mind, Whoop stress, Todoist

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| T0 habit compliance | 30% | Habitify/habit_scores | Tier 0 (non-negotiable) completion rate |
| T1 habit compliance | 15% | Habitify/habit_scores | Tier 1 completion rate |
| Journal consistency | 15% | Notion | Days with journal entry / total days |
| State of Mind valence | 15% | State of Mind | Average valence trend (improving = good) |
| Stress management | 15% | Whoop | Stress score trend, recovery from high-stress days |
| Vice control | 10% | habit_scores | Vice streak maintenance (alcohol, THC, etc.) |

### 3.6 Relationships (Weight: 7%)
**Owner:** Social connection scoring (journal-derived)
**Data sources:** Notion journal (enriched), State of Mind

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Social interaction frequency | 40% | Journal enrichment | `social_connection_score` from journal entries |
| Interaction quality | 30% | Journal enrichment | Depth/quality of social mentions |
| Buddy engagement | 15% | Derived | Tom buddy page data freshness |
| Social mood correlation | 15% | State of Mind + Journal | Valence on social vs non-social days |

### 3.7 Consistency (Weight: 10%) — Meta-pillar
**Owner:** The Chair
**Data sources:** All other 6 pillars

| Component | Weight | Source | Metric |
|-----------|--------|--------|--------|
| Cross-pillar variance | 40% | Derived | Low std dev across 6 pillar raw_scores = high consistency |
| Data completeness | 20% | All sources | % of expected data points actually captured |
| Streak maintenance | 20% | Derived | Consecutive days with all 6 pillars scoring above their 30th percentile |
| Weekend-weekday stability | 20% | Derived | Ratio of weekend avg to weekday avg across pillars |

---

## 4. Scoring Engine

### 4.1 Daily Computation

Each day, after Daily Brief data assembly:

```
For each pillar:
  1. Compute raw_score (0-100) from today's component metrics
  2. Compute level_score = exponentially-weighted 21-day rolling average of raw_scores
     - Lambda = 0.85 (recent days weighted ~6x more than 21 days ago)
  3. Compute xp_delta from raw_score:
     - raw_score >= 80: +3 XP
     - raw_score >= 60: +2 XP
     - raw_score >= 40: +1 XP
     - raw_score >= 20: +0 XP
     - raw_score < 20:  -1 XP
  4. Apply cross-pillar buffs/debuffs to level_score
  5. Determine if level changed (see 4.2)

Overall Character Level = weighted average of 7 pillar level_scores
```

### 4.2 Level Change Rules (Anti-Flip-Flop)

**Level UP:** Requires `level_score` to be above the next level threshold for **5 consecutive days**. Only then does the level increment. This means a single great day does nothing — you need sustained improvement.

**Level DOWN:** Requires `level_score` to be below the current level threshold for **7 consecutive days**. The asymmetry (5 up / 7 down) is deliberate — loss aversion buffering per Maya's principle.

**Tier transitions** (Foundation/Momentum/Discipline/Mastery/Elite) follow the same rules but with **7 up / 10 down** — making them even more stable and meaningful.

**Result:** Approximately 2-4 level events per month total. Tier transitions every 2-3 months per pillar. This is the "occasional oh sweet" cadence Matthew wants.

### 4.3 Level Thresholds

Levels 1-100 map linearly to level_score 0-100 (1:1). The tiers provide named groupings:

| Tier | Level Range | Meaning |
|------|-------------|---------|
| 🔨 Foundation | 1–20 | Building the base. Just getting started or recovering from a setback. |
| 🔥 Momentum | 21–40 | Habits forming. Consistency emerging. |
| ⚔️ Discipline | 41–60 | This is your lifestyle now. Showing up regularly. |
| 🏆 Mastery | 61–80 | Sustained excellence. Top quartile of your own history. |
| 👑 Elite | 81–100 | Peak performance. You are doing this thing exceptionally well. |

### 4.4 Cross-Pillar Effects

| Condition | Effect | Name |
|-----------|--------|------|
| Sleep level < 35 | Movement -8%, Mind -5% | 🛏️ Sleep Drag |
| Movement level > 70 | Metabolic Health +5% | 💪 Training Boost |
| Mind level > 70 | Consistency +3% | 🧠 Focus Buff |
| Nutrition level > 70 AND Movement level > 70 | Metabolic Health +8% | ⚡ Synergy Bonus |
| All 7 pillars in Discipline+ (41+) | +2 to all pillar levels | 🌟 Alignment Bonus |
| Vice streak > 30 days (any vice) | Mind +3% | 🛡️ Vice Shield |

### 4.5 Baseline

**Baseline date: 2026-02-22** — Matthew's journey start date (from `profile.json`). Starting weight: 302 lbs. Goal: 185 lbs.

All pillars begin at **Level 1 (Foundation)** on Feb 22. The Character Sheet retrocomputes forward from that date, day by day, applying the scoring engine sequentially so levels build organically from the true starting point. This means the current Character Level reflects the *actual journey from day one* — not a snapshot of recent performance.

For pillars with sparse early data (State of Mind, CGM, Relationships), missing data contributes a neutral raw_score (40) rather than penalizing. As data coverage improves, the pillar naturally reflects reality.

**Weight/composition baseline:** The Nutrition pillar's 40% composition sub-score uses a smooth curve from 302lb (score=0) to 185lb (score=100). Current weight maps proportionally along this curve: `composition_score = ((302 - current_weight) / (302 - 185)) * 100`, capped at 0-100.

---

## 5. Milestones & Rewards

### 5.1 System-Defined Milestones

| Milestone | Trigger | Daily Brief Behavior |
|-----------|---------|---------------------|
| Pillar Level Up | Any pillar gains a level | 🎮 badge in Daily Brief header, Board member for that domain comments |
| Pillar Level Down | Any pillar drops a level | Coaching tone: "Your [pillar] needs attention" — no alarm, no shame |
| Tier Transition Up | Any pillar crosses tier boundary | 🏆 Celebration section in Daily Brief. Elena writes Chronicle moment. |
| Tier Transition Down | Any pillar drops a tier | 📋 "Recovery plan" — Board prescribes specific 7-day protocol |
| Character Level Up | Overall level increments | ⭐ Special header in Daily Brief |
| All-Pillar Discipline | All 7 pillars reach level 41+ | 🌟 Alignment achievement — rare, major celebration |
| All-Pillar Mastery | All 7 pillars reach level 61+ | 👑 "Project 40 Complete" — the endgame |

### 5.2 User-Defined Rewards (Future)

Matthew can define personal rewards for milestones via MCP tool:
- "When Sleep hits Mastery → buy the new pillow"
- "When Character Level hits 60 → dinner at Canlis"
- "When all pillars hit Discipline → weekend trip"

Stored in DynamoDB, surfaced in Daily Brief when triggered.

---

## 6. Communication Design

### 6.1 Daily Brief Integration

A new section after the day grade: **Character Sheet Status**

```
🎮 CHARACTER SHEET — Level 47 (Discipline)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

😴 Sleep        ████████░░ 62 Mastery      (+1 ↑ Level up!)
🏋️ Movement     ██████░░░░ 55 Discipline
🥗 Nutrition    ████████░░ 58 Discipline
📊 Metabolic    █████░░░░░ 44 Discipline
🧠 Mind         ███████░░░ 51 Discipline
💬 Relationships ████░░░░░░ 33 Momentum
🎯 Consistency  ██████░░░░ 49 Discipline

Active Effects: 🛏️ Sleep Drag (−8% Movement, −5% Mind)  ← only when applicable
Level Up! 😴 Sleep reached Level 62 (Mastery)
```

When NO level changes occurred: just show the compact table with no fanfare. The absence of events IS the design — it means things are stable, which is good.

### 6.2 Weekly Digest Integration

Character Sheet weekly summary:
- 7-day pillar movement (which pillars gained/lost levels)
- XP earned per pillar
- Closest pillar to next tier transition
- Board commentary on the strategic priority

### 6.3 Dashboard Integration

New tile on `dash.averagejoematt.com`:
- Radar chart (7 axes, one per pillar)
- Overall Character Level prominently displayed
- XP progress bars per pillar
- Recent milestone badges

### 6.4 Buddy Page Integration

Tom sees Matthew's Character Level and pillar breakdown — adds strategic context to the engagement-based beacon.

### 6.5 Chronicle Integration

Elena references the Character Sheet as narrative texture. Tier transitions become story moments. "The week Matthew's Movement pillar quietly crossed into Mastery" is a Chronicle-worthy event.

---

## 7. Technical Architecture

### 7.0 S3 Configuration

**Path:** `s3://matthew-life-platform/config/character_sheet.json`

Follows the same pattern as `profile.json` and `board_of_directors.json` — editable via MCP tool, loaded by Daily Brief Lambda at runtime.

```json
{
  "_meta": {
    "version": "1.0.0",
    "description": "Character Sheet configuration: pillar weights, components, thresholds, tier definitions, cross-pillar effects",
    "last_updated": "2026-03-02"
  },
  "baseline": {
    "start_date": "2026-02-22",
    "start_weight_lbs": 302,
    "goal_weight_lbs": 185
  },
  "pillars": {
    "sleep": {
      "weight": 0.20,
      "owner": "Dr. Lisa Park",
      "components": {
        "duration_vs_target": { "weight": 0.25, "target_hours": 7.5 },
        "efficiency": { "weight": 0.20 },
        "deep_sleep_pct": { "weight": 0.20, "target_pct": 0.15 },
        "rem_pct": { "weight": 0.15, "target_pct": 0.20 },
        "onset_consistency": { "weight": 0.20, "window_days": 14 }
      }
    }
    // ... (all 7 pillars follow same pattern)
  },
  "leveling": {
    "ema_lambda": 0.85,
    "ema_window_days": 21,
    "level_up_streak_days": 5,
    "level_down_streak_days": 7,
    "tier_up_streak_days": 7,
    "tier_down_streak_days": 10
  },
  "xp_bands": [
    { "min_raw_score": 80, "xp": 3 },
    { "min_raw_score": 60, "xp": 2 },
    { "min_raw_score": 40, "xp": 1 },
    { "min_raw_score": 20, "xp": 0 },
    { "min_raw_score": 0,  "xp": -1 }
  ],
  "tiers": [
    { "name": "Foundation", "emoji": "🔨", "min_level": 1,  "max_level": 20 },
    { "name": "Momentum",   "emoji": "🔥", "min_level": 21, "max_level": 40 },
    { "name": "Discipline", "emoji": "⚔️", "min_level": 41, "max_level": 60 },
    { "name": "Mastery",    "emoji": "🏆", "min_level": 61, "max_level": 80 },
    { "name": "Elite",      "emoji": "👑", "min_level": 81, "max_level": 100 }
  ],
  "cross_pillar_effects": [
    { "name": "Sleep Drag",     "emoji": "🛏️", "condition": "sleep < 35",   "targets": { "movement": -0.08, "mind": -0.05 } },
    { "name": "Training Boost", "emoji": "💪", "condition": "movement > 70", "targets": { "metabolic": 0.05 } },
    { "name": "Focus Buff",     "emoji": "🧠", "condition": "mind > 70",     "targets": { "consistency": 0.03 } },
    { "name": "Synergy Bonus",  "emoji": "⚡",  "condition": "nutrition > 70 AND movement > 70", "targets": { "metabolic": 0.08 } },
    { "name": "Alignment Bonus","emoji": "🌟", "condition": "all_pillars >= 41", "targets": { "_all": 2 } },
    { "name": "Vice Shield",    "emoji": "🛡️", "condition": "any_vice_streak > 30", "targets": { "mind": 0.03 } }
  ],
  "avatar": {
    "enabled": true,
    "style": "pixel_rpg",
    "s3_prefix": "dashboard/avatar/"
  }
}
```

Editable via existing MCP pattern — future `update_character_config` tool can modify weights, thresholds, and effects without redeploying any Lambda.

### 7.1 DynamoDB Schema

**New partition:** `USER#matthew#SOURCE#character_sheet`
**SK:** `DATE#YYYY-MM-DD`

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `character_level` | number | Overall weighted level (1-100) |
| `character_tier` | string | Foundation/Momentum/Discipline/Mastery/Elite |
| `character_xp` | number | Cumulative XP total |
| `pillar_sleep` | map | `{raw_score, level_score, level, tier, xp, xp_to_next, components: {...}, streak_above: N, streak_below: N}` |
| `pillar_movement` | map | Same structure |
| `pillar_nutrition` | map | Same structure |
| `pillar_metabolic` | map | Same structure |
| `pillar_mind` | map | Same structure |
| `pillar_relationships` | map | Same structure |
| `pillar_consistency` | map | Same structure |
| `active_effects` | list | Active buffs/debuffs: `[{name, source_pillar, target_pillar, modifier_pct}]` |
| `level_events` | list | Events today: `[{pillar, event_type, old_level, new_level, old_tier, new_tier}]` |
| `computed_at` | string | ISO timestamp |
| `engine_version` | string | Scoring engine version for retrocompute compatibility |

### 7.2 MCP Tools (3 new → 102 → 105 tools)

**Module:** `mcp/tools_character.py`

| Tool | Params | Description |
|------|--------|-------------|
| `get_character_sheet` | date (optional, default today) | Current state: overall level, all 7 pillars with levels/tiers/XP, active effects, recent events. 14-day sparkline per pillar. |
| `get_pillar_detail` | **pillar**, days (default 30) | Deep dive: component breakdown, daily raw_scores, level history, XP curve, contributing metrics, Board member assessment |
| `get_level_history` | days (default 90), pillar (optional) | Timeline of all level/tier change events. If pillar specified, that pillar only. Includes milestone achievements. |

### 7.3 Computation Location

**Option A (recommended): Daily Brief Lambda extension**
The Daily Brief already assembles all source data needed for every pillar. Add Character Sheet computation after day grade + habit scores, write to DynamoDB, include in email. This avoids a separate Lambda and duplicated data fetching.

**Estimated addition:** ~300-400 lines to daily_brief_lambda.py + a `character_engine.py` utility (similar pattern to board_loader.py — importable module bundled in the zip).

### 7.4 Backfill

A retrocompute script (`backfill/retrocompute_character_sheet.py`) will:
1. Read all existing source data, day_grades, and habit_scores
2. Compute character sheet for each historical date sequentially (levels depend on prior day's state)
3. Write to DynamoDB

This follows the same pattern as `retrocompute_day_grades.py`. Coverage will match day_grade coverage (~948 days from 2023-07-23).

### 7.5 Cache Warmer Addition

Add `get_character_sheet` (default/today) to the 12 cached tools → 13 cached tools. Cache key: `character_sheet_YYYY-MM-DD`.

### 7.6 Dashboard JSON Extension

Daily Brief's `write_dashboard_json()` adds character sheet data to `dashboard/data.json` for the radar chart tile.

### 7.7 Buddy JSON Extension

Daily Brief's `write_buddy_json()` adds character level + pillar summary to `buddy/data.json`.

---

## 8. Avatar System

### 8.1 Concept

A pixel-art RPG-style avatar based on Matthew's actual appearance that visually evolves as Character Level and pillar tiers change. The avatar makes the gamification tangible — you can *see* yourself leveling up.

### 8.2 Design: Pixel RPG Character

**Style:** 16-bit RPG character portrait (think Final Fantasy / Chrono Trigger character select screen). Based on a reference photo of Matthew, translated into pixel art. Approximately 128×128px base sprite, rendered at 2-4x for display (256×256 or 512×512).

**Why pixel art:** It's inherently "game" aesthetic, scales well, looks good at any size, renders cleanly in emails (static PNG), and the tier progression reads clearly through visual upgrades without needing photo-realistic quality.

### 8.3 Tier Progression (5 Visual States)

Each tier has a distinct visual treatment of the base avatar:

| Tier | Visual | Description |
|------|--------|-------------|
| 🔨 Foundation (1-20) | Basic outfit, muted palette | Simple clothes, no accessories. Starting the journey. Humble beginnings. |
| 🔥 Momentum (21-40) | Light gear, warmer colors | Basic equipment appears — running shoes, a training watch. Colors brighten. Determination visible. |
| ⚔️ Discipline (41-60) | Equipped, confident stance | Armor/gear fills out. Confident posture. Background starts glowing. This is the "you're actually doing this" state. |
| 🏆 Mastery (61-80) | Full gear, effects active | Full equipment loadout with visible auras. Pillar badges orbit the character. Commanding presence. |
| 👑 Elite (81-100) | Legendary, golden accents | Golden highlights, crown/halo effect, all pillar badges at full glow. The "final form." Rare and earned. |

### 8.4 Pillar Badges

Each pillar has a small icon that appears around the avatar when that pillar reaches Discipline (41+). The icon glows brighter at higher tiers:

| Pillar | Badge | Foundation | Discipline+ |
|--------|-------|------------|-------------|
| Sleep | 🌙 Moon | Hidden | Appears, dim → bright |
| Movement | ⚔️ Sword | Hidden | Appears, dim → bright |
| Nutrition | 🛡️ Shield | Hidden | Appears, dim → bright |
| Metabolic | ❤️ Heart | Hidden | Appears, dim → bright |
| Mind | 🧠 Brain | Hidden | Appears, dim → bright |
| Relationships | 🤝 Handshake | Hidden | Appears, dim → bright |
| Consistency | ⭐ Star | Hidden | Appears, dim → bright |

### 8.5 Active Effects Visualization

When cross-pillar effects are active, subtle visual indicators appear on the avatar:
- **Sleep Drag:** ZZZ cloud above character, slightly dimmed palette
- **Training Boost:** Small flexing aura / energy lines
- **Synergy Bonus:** Lightning sparks between pillar badges
- **Alignment Bonus:** Full golden ring connecting all badges

### 8.6 Technical Implementation

**Pre-generated static images** stored in S3:

```
s3://matthew-life-platform/dashboard/avatar/
  base/
    foundation.png        ← 128x128 base sprite per tier
    momentum.png
    discipline.png
    mastery.png
    elite.png
  badges/
    sleep_dim.png          ← individual badge overlays
    sleep_bright.png
    movement_dim.png
    ...
  effects/
    sleep_drag.png
    synergy_bonus.png
    alignment_bonus.png
    ...
  composite/              ← pre-composed common combinations (optional optimization)
```

**Generation approach:** Create the base 5 tier sprites from Matthew's reference photo (one-time creative effort). Badges and effects are small overlay PNGs composed via the dashboard HTML/CSS or a simple Lambda compositor.

**Display locations:**
- **Dashboard:** Hero position on `dash.averagejoematt.com`, updates daily when `data.json` refreshes
- **Daily Brief email:** Inline PNG of current avatar state in the Character Sheet section
- **Buddy page:** Tom sees Matthew's avatar with current tier visual
- **Chronicle:** Elena can reference avatar milestones ("the week the golden ring appeared")

**Avatar state in data.json:**
```json
{
  "avatar": {
    "overall_tier": "discipline",
    "pillar_badges": {
      "sleep": "bright",
      "movement": "dim",
      "nutrition": "bright",
      "metabolic": "hidden",
      "mind": "dim",
      "relationships": "hidden",
      "consistency": "dim"
    },
    "active_effects": ["training_boost"]
  }
}
```

The dashboard HTML reads this state and composites the appropriate images via CSS layering (absolutely positioned overlays on the base sprite). No server-side image generation needed for daily updates.

### 8.7 Build Phase

Avatar creation is a **Phase 3 deliverable** (Dashboard + Buddy + Chronicle). Steps:
1. Matthew provides a reference photo
2. Create 5 tier sprites (pixel art, one-time creative work)
3. Create badge and effect overlay PNGs
4. Add CSS compositing to dashboard HTML
5. Add avatar state to `data.json` output from Daily Brief
6. Add inline avatar PNG to Daily Brief email (uses highest-tier composite for email; dashboard shows full interactive version)

---

## 9. Build Phases

### Phase 1: Scoring Engine + DynamoDB (v2.58.0)
- `character_engine.py` — pillar computation, level rules, cross-pillar effects
- `config/character_sheet.json` — S3 config with all pillar weights, components, thresholds
- DynamoDB writes from Daily Brief Lambda
- Retrocompute backfill script (2026-02-22 → present, sequential day-by-day)
- 3 MCP tools (`tools_character.py`: get_character_sheet, get_pillar_detail, get_level_history)
- Estimated: 6-8 hours

### Phase 2: Daily Brief Integration (v2.59.0)
- Character Sheet section in Daily Brief email (compact pillar table + level bars)
- Level-up/level-down event handling with Board commentary
- Weekly Digest character sheet summary section
- Estimated: 3-4 hours

### Phase 3: Dashboard + Avatar + Buddy + Chronicle (v2.60.0)
- Radar chart tile on `dash.averagejoematt.com`
- **Avatar system:** Create 5 tier sprites from reference photo, badge overlays, effect overlays
- Avatar CSS compositing on dashboard
- Avatar state in `data.json` + inline PNG in Daily Brief email
- Buddy page character summary + avatar
- Chronicle integration (Elena narrative hooks for tier transitions + avatar milestones)
- Estimated: 6-8 hours

### Phase 4: Rewards & Polish (v2.61.0)
- User-defined reward milestones via MCP tool
- Protocol recommendations per pillar tier (Huberman)
- `update_character_config` MCP tool for weight/threshold tuning
- Monthly Digest character sheet retrospective section
- Estimated: 3-4 hours

**Total estimated effort:** 18-24 hours across 4-6 sessions

### Cost Impact
$0 incremental. DynamoDB writes are trivial (~1 item/day), computation happens within existing Daily Brief Lambda, MCP tools are lightweight queries. Avatar images are static PNGs in S3 (negligible storage).

---

## 10. Resolved Design Questions

| # | Question | Decision | Rationale |
|---|----------|----------|----------|
| 1 | Baseline date | **2026-02-22** (journey start) | Start at Level 1, build organically. Matches profile.json `journey_start_date`. |
| 2 | Starting weight | **302 lbs** (from profile.json) | Composition sub-score = 0% at 302, 100% at 185lb goal. |
| 3 | Configuration | **`config/character_sheet.json` in S3** | Editable via MCP, same pattern as board_of_directors.json and profile.json. |
| 4 | Avatar | **Pixel RPG style, 5 tier variants + badge overlays** | Pre-generated PNGs, CSS-composited on dashboard. Based on Matthew's reference photo. |

## 11. Open Questions for Build

1. **Notification channel:** Level-up events in Daily Brief only, or also push to a separate notification (SNS/email)?
2. **Brittany email:** Should the upcoming Brittany accountability email include Character Sheet data?
3. **Avatar artist:** Generate pixel art via AI image tools, or commission? AI is faster and free; commissioned art is higher quality.
4. **Sparse data handling:** For days where a source has no data (e.g., no Strava activity), should Movement raw_score use last known value, or score 0? Current design: neutral 40.

---

## 12. Success Criteria

The Character Sheet is working when:
- Matthew checks his level naturally (not obsessively) and feels a genuine sense of progress
- Level-up events feel earned and create a brief moment of satisfaction
- Level-down events feel like coaching moments, not punishment
- The score rarely flip-flops (target: <1 reversal per pillar per month)
- Tom can see Matthew's Character Level and it adds context to accountability
- Elena can reference character progression as narrative texture
- The Board uses pillar levels to calibrate their commentary ("as someone in Mastery-tier sleep...")


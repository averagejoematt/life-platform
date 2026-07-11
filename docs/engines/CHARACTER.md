# Character Engine — pillars, EMA levels, XP

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11 (post-#957, ENGINE_VERSION 1.4.0)
> Math audit + 420-day simulation verdicts: [CHARACTER_MATH_AUDIT_2026-07.md](CHARACTER_MATH_AUDIT_2026-07.md) (epic #956).
> **Sources of truth:** `lambdas/character_engine.py` (v1.3.0), `lambdas/compute/character_sheet_lambda.py`, `config/character_sheet.json` (deployed to `s3://…/config/matthew/character_sheet.json`)

## Purpose

Daily RPG-style character sheet: 7 weighted pillar scores → EMA-smoothed levels with
anti-flip-flop streak gates, XP with decay/debt, cross-pillar effects, and a deterministic
character mood. Runs in the `character-sheet` compute Lambda (daily, before 11 AM PT).

## The pillar model

Six primary pillars (`PILLAR_COMPUTERS`, `character_engine.py:1316-1323`): sleep, movement,
nutrition, metabolic, mind, relationships — plus the **consistency** meta-pillar computed from
the others. Config pillar weights (live `config/character_sheet.json`): sleep 0.20,
movement 0.18, nutrition 0.18, mind 0.15, metabolic 0.12, consistency 0.10, relationships 0.07.

Each pillar raw score is a weighted mean of components with a **confidence blend**
(`_weighted_pillar_score`, :802-857):

```
raw        = Σ(scoreᵢ·wᵢ)/Σwᵢ            over components with data
coverage   = Σwᵢ(with data) / Σwᵢ(all)
confidence = min(1, coverage / 0.80)
adjusted   = raw·confidence + 50·(1−confidence)     # blend toward neutral 50
```

**ADR-104 behavioral-absence semantics:** components flagged `behavioral: true` in config
(logging, journaling, training — things Matthew does or doesn't do) score **0 at full weight**
when absent, and are listed in `_absent_behaviors`. Only *measured* components (device readings)
drop out of the weight sum — a device gap is not a failure; an unlogged habit is. A pillar where
zero components had data returns the placeholder 50.0 with `_not_instrumented: true` (#747 —
callers must not present it as a reading).

**Categorical→numeric bridges** (read-time, in the gather layer):
- #902/#905: `enriched_mood` (native 1–5 from `journal_enrichment_lambda`) → `mood_avg` on the
  0–10 scale via `(m−1)/4×10` (`character_sheet_lambda._enriched_mood_to_10`, :158-180).
- #910/#911: categorical `enriched_social_quality` → `social_score` 0–10 by rank,
  `rank/3×10` (alone→0, surface→3.33, meaningful→6.67, deep→10;
  `character_engine._social_quality_to_10`, :667-696), averaged across the day's entries. The
  numeric `social_connection_score` fields remain the primary path (no producer writes them yet).

## EMA smoothing (`compute_ema_level_score`, :865-886)

Exponentially weighted mean over the last `ema_window_days` (21) raw scores, most-recent
heaviest, per-pillar decay `ema_lambda` (live: sleep 0.85, movement 0.90, nutrition 0.88,
metabolic 0.95, mind 0.85, relationships 0.93, consistency 0.93):

```
level_score = Σ(rawᵢ · λ^age) / Σ λ^age        (empty history → 50)
```

## Anti-flip-flop level rules (`evaluate_level_changes`, :1029-1189)

`target_level = round(level_score)`. Movement requires consecutive-day streaks, harder by tier
(live `tier_streak_overrides`: Foundation up 3/down 5 … Elite up 14/down 21; tier-boundary
crossings need longer streaks, e.g. Foundation 5/7 … Elite 21/30). Step size by gap
(`level_step_bands`: Δ>25 ⇒ 3, Δ>10 ⇒ 2, else 1).

Gates, in order:
1. **Coverage hold (ADR-104):** `data_coverage < level_change_min_coverage` (0.5) ⇒ no leveling
   signal — both streaks hold, no move in either direction.
2. **Up-day gate (ADR-104/#913/#954/#957):** climbing also requires `round(raw) ≥
   min(target_level, unadjusted EMA target)`, and since #957 the raw judged is the
   **UNBLENDED** raw (`weighted_sum/total_weight` before the confidence blend toward 50) —
   exactly 0 in total silence, so the blend floor (~15.6 for a dark behavioral pillar) can
   never re-open the up-gate at any horizon (pre-#957: after ~17 dark days the EMA converged
   down to the blend floor and the gate self-satisfied — a never-logging fresh character
   reached L16 in 60 days while mood read dormant). The target side stays the UNboosted EMA
   of raw scores (like-for-like): cross-pillar bonus modifiers raise the displayed
   level_score but can no longer raise the daily bar (#954 — boosts were freezing boosted
   pillars at L1 forever). (Scale fix #913: the old `raw ≥ current_level+1` let a crashed
   raw 9 beat a converging level 8.) A below-target day *holds* the up-streak, it doesn't
   reset it.
3. **XP buffer gate (down only, #954):** an explicit per-pillar `xp_buffer` state (fills with
   XP gained, capped at one level's worth; drains with XP lost; floors at 0 — monotone under
   decline) absorbs demotion pressure while `≥ xp_buffer_threshold` (20). Replaced the old
   `xp_total % 100`, which WRAPPED UPWARD as XP declined — losing XP across a 100-boundary
   re-armed near-maximum immunity. Legacy records seed the buffer once from the modulo
   remainder. ENGINE_VERSION 1.4.0.

## XP and debt (`_compute_xp`, :182-228)

Bands on raw score: ≥80 ⇒ +3, ≥60 ⇒ +2, ≥40 ⇒ +1, ≥20 ⇒ 0, else −1; minus `daily_xp_decay` (2,
scaled linearly over the first 14 grace days of a cycle). #913: the signed balance splits into
`xp_total` (positive part) and visible `xp_debt` (capped at `xp_debt_cap` = 100, one level's
worth) — good days pay debt before XP grows; sustained decay is no longer hidden by a 0-floor.

## Neglect atrophy + mood (#913)

- `neglect_decay_state` (:909-943): when `engagement_state.presence_class == "dark"` (and not a
  planned pause), after `n_grace_days` (3) the level score of pillars whose behavioral weight
  share ≥ 0.3 is multiplied by `0.98^(gap−3)`, floored at the day's own raw score and the config
  floor (0). Models detraining/evidence loss, never punishment (ADR-104). All four knobs live in
  `config/character_sheet.json` under `leveling.neglect_decay`
  (`n_grace_days` / `rate` / `floor` / `min_behavioral_share`).
- `compute_character_mood` (:950-1009), pure code (ADR-105), first match wins:
  dark ⇒ **dormant**; quiet or 7d-composite trend ≤ −5 ⇒ **fading**; present/light AND trend ≥ +3
  AND composite ≥ 55 ⇒ **thriving**; else **steady**. Trend = mean(last 3 d) − mean(prior 4 d).

## Cross-pillar effects + overall level

Config `cross_pillar_effects` conditions over pillar levels (e.g. `sleep < 30 AND …`) add
multiplicative modifiers: `adjusted = level_score × (1 + Σ mod)` (:1228-1260, [F-05]).
Overall: `character_level = floor(Σ(levelᵖ·wᵖ)/Σwᵖ)` [F-14]; tiers Foundation 1–20 /
Momentum 21–40 / Discipline 41–60 / Mastery 61–80 / Elite 81–100.

## Outputs / config surface

Record → `USER#matthew#SOURCE#character_sheet / DATE#<date>` (`store_character_sheet`,
:1548-1567; pre-genesis dates tagged `phase=pilot`), EXPERIMENT_SCOPED — wiped + rebuilt at
reset. Per-pillar output carries raw_score, level_score, level, tier, xp_total/xp_delta/xp_debt,
confidence, data_coverage, `not_instrumented`, `absent_behaviors`, `drivers` (ADR-104
provenance), `coverage_hold`, `neglect_decay`. Config: `config/character_sheet.json` in S3
(5-min warm cache); tunable via the `update_character_config` MCP tool. No env vars beyond the
standard table/bucket.

> **Verified against `lambdas/character_engine.py` + `config/character_sheet.json` @ git f2c9ed64 on 2026-07-11.**

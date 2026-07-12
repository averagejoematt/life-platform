# Character Engine — pillars, EMA levels, XP

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11 (post-#956 math v2, ENGINE_VERSION 1.5.0, ADR-134)
> Math audit + 420-day simulation verdicts: [CHARACTER_MATH_AUDIT_2026-07.md](CHARACTER_MATH_AUDIT_2026-07.md) (epic #956).
> **Sources of truth:** `lambdas/character_engine.py` (v1.5.0), `lambdas/compute/character_sheet_lambda.py`, `config/character_sheet.json` (v1.4.0, deployed to `s3://…/config/matthew/character_sheet.json`)

## Purpose

Daily RPG-style character sheet: 7 weighted pillar scores → EMA-smoothed levels with
anti-flip-flop streak gates, XP with decay/debt, cross-pillar effects, and a deterministic
character mood. Runs in the `character-sheet` compute Lambda (daily, before 11 AM PT).

## The pillar model

Six primary pillars (`PILLAR_COMPUTERS`, `character_engine.py:1539-1546`): sleep, movement,
nutrition, metabolic, mind, relationships — plus the **consistency** meta-pillar computed from
the others. Config pillar weights (live `config/character_sheet.json`): sleep 0.20,
movement 0.18, nutrition 0.18, mind 0.15, metabolic 0.12, consistency 0.10, relationships 0.07.

Each pillar raw score is a weighted mean of components with a **confidence blend**
(`_weighted_pillar_score`, :928-990):

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

**Behavioral modifiers are engine inputs (#961/ADR-134):** the caller passes
`data["raw_score_modifiers"] = {pillar: {"multiplier": m, "source": "…"}}` (e.g. the
food-delivery penalty/bonus, computed by the lambda against the date being scored) and the
engine scales the raw + unblended raw at step 1 — before the EMA, XP bands, up-gate, and
drivers — recording provenance as `raw_modifier` on the pillar record. The stored raw_score is
always the number the engine leveled on; nothing mutates it post-compute.

**Categorical→numeric bridges** (read-time, in the gather layer):
- #902/#905: `enriched_mood` (native 1–5 from `journal_enrichment_lambda`) → `mood_avg` on the
  0–10 scale via `(m−1)/4×10` (`character_sheet_lambda._enriched_mood_to_10`, :168-190).
- #910/#911: categorical `enriched_social_quality` → `social_score` 0–10 by rank,
  `rank/3×10` (alone→0, surface→3.33, meaningful→6.67, deep→10;
  `character_engine._social_quality_to_10`, :713-742), averaged across the day's entries. The
  numeric `social_connection_score` fields remain the primary path (no producer writes them yet).
- #962: `vice_streaks` is lifted from the day's habit_scores record (daily_metrics_compute has
  always written it) into the top-level key the mind pillar's vice_control component reads;
  `streak_all_above_30th` + `weekend_weekday_ratio` are derived by
  `character_engine.derive_consistency_inputs` (:804-878) from the same 21-day record window
  the EMA histories already fetch. `buddy_engagement` was removed (B-3 precedent — no producer
  ever wrote `buddy_freshness_days`); relationships weights renormalized (.45/.35/.20).

## EMA smoothing (`compute_ema_level_score`, :998-1019)

Exponentially weighted mean over the last `ema_window_days` (21) raw scores, most-recent
heaviest, per-pillar decay `ema_lambda` (live: sleep 0.85, movement 0.90, nutrition 0.88,
metabolic 0.95, mind 0.85, relationships 0.93, consistency 0.93):

```
level_score = Σ(rawᵢ · λ^age) / Σ λ^age        (empty history → 50)
```

## Anti-flip-flop level rules (`evaluate_level_changes`, :1162-1385)

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
3. **XP buffer gate (down only, #954/ADR-134):** an explicit per-pillar `xp_buffer` state
   (fills with XP gained, capped at `xp_buffer_cap` = 40; drains with XP lost; floors at 0 —
   monotone under decline) absorbs demotion pressure while `≥ xp_buffer_threshold` (20).
   Replaced the old `xp_total % 100`, which WRAPPED UPWARD as XP declined. The v2 cap bounds
   the engaged-decline shield to ~10–20 days (an uncapped buffer pinned at 100 under the v2
   XP economy and silently granted 40+ days of immunity). Legacy records seed the buffer once
   from the modulo remainder (capped).
4. **Dark persistence (#959/ADR-134):** during a confirmed dark stretch (`presence_class=dark`
   past grace, never a planned pause) atrophy-qualifying pillars bypass the XP buffer gate and
   their down-streak PERSISTS across drops instead of re-arming a fresh 7-day streak per
   single drop — anti-flip-flop machinery protects against noisy engaged data, never against
   provable absence. Sim: a 30-day silent month costs ~12 headline levels (was ~2, the cycle-4
   failure mode) and recovers ~28 days after resuming. Kill-switch:
   `leveling.neglect_decay.persistent_down_streak`.

## XP and debt (`_compute_xp`, :183-243; buffer `_roll_xp_buffer`, :245-273)

Bands on raw score: ≥80 ⇒ +3, ≥60 ⇒ +2, ≥40 ⇒ +1, ≥20 ⇒ 0, else −1; minus `daily_xp_decay`
(**1** since ADR-134 — the zero-point sits at "a decent day": raw 40–59 nets 0, 60+ grows,
sub-20 bleeds; scaled linearly over the first 14 grace days of a cycle). #913: the signed
balance splits into `xp_total` (positive part) and visible `xp_debt` (capped at `xp_debt_cap`
= 100, one level's worth) — good days pay debt before XP grows; sustained decay is no longer
hidden by a 0-floor, and under the v2 zero-point a dark-stretch debt is visibly repaid by
realistic living instead of ratcheting forever.

**#964 (ADR-134): XP mirrors the level gate** — a `coverage_hold` or `not_instrumented` day
carries no XP judgment in either direction (the #747 relationships placeholder used to feed
the bands as "a mediocre day" and bleed a permanent phantom −100 debt). **#961: challenge
bonus XP** enters as `data["challenge_bonus_xp"] = {pillar: xp}` and flows through the signed
balance (debt pays first, even on hold days); `xp_consumed_at` is stamped only after the
record stores successfully.

## Neglect atrophy + mood (#913)

- `neglect_decay_state` (:1042-1076): when `engagement_state.presence_class == "dark"` (and not a
  planned pause), after `n_grace_days` (3) the level score of pillars whose behavioral weight
  share ≥ 0.3 is multiplied by `0.98^(gap−3)`, floored at the day's own raw score and the config
  floor (0). Models detraining/evidence loss, never punishment (ADR-104). Knobs live in
  `config/character_sheet.json` under `leveling.neglect_decay`
  (`n_grace_days` / `rate` / `floor` / `min_behavioral_share` / `persistent_down_streak`).
- `compute_character_mood` (:1083-1142), pure code (ADR-105), first match wins:
  dark ⇒ **dormant**; quiet or 7d-composite trend ≤ −5 ⇒ **fading**; present/light AND trend ≥ +3
  AND composite ≥ 55 ⇒ **thriving**; else **steady**. Trend = mean(last 3 d) − mean(prior 4 d).

## Cross-pillar effects + overall level

Config `cross_pillar_effects` conditions evaluate EMA level_**scores** — deliberately, per
ADR-134/#963: effects model current-state physiology synergies (poor sleep drags today's
training capacity), not tier achievements; the config narrative is worded to match. The
`any_vice_streak` conditions are data-driven since #962 (`compute_cross_pillar_effects`,
:1427-1466, takes the day's vice_streaks — the Vice Shield can actually fire). Modifiers are
multiplicative: `adjusted = level_score × (1 + Σ mod)` [F-05].

Overall: `character_level = floor(Σ(levelᵖ·wᵖ)/Σwᵖ)` over **instrumented** pillars [F-14 +
#960/ADR-134]: a pillar that is `not_instrumented` today and still at level 1 (never earned a
level) is excluded and the weights renormalize — the frozen relationships pillar no longer
caps the reachable headline at 93 (Elite was mathematically unreachable; sim now reaches it at
~1 year of sustained raw ~90). Once a pillar levels it counts forever — going dark later drags
honestly. Excluded pillars ride the record as `headline_excluded_pillars`. Tiers Foundation
1–20 / Momentum 21–40 / Discipline 41–60 / Mastery 61–80 / Elite 81–100.

## Outputs / config surface

Record → `USER#matthew#SOURCE#character_sheet / DATE#<date>` (`store_character_sheet`,
:1865-1884; pre-genesis dates tagged `phase=pilot`), EXPERIMENT_SCOPED — wiped + rebuilt at
reset. Per-pillar output carries raw_score, level_score, level, tier, xp_total/xp_delta/xp_debt,
`raw_modifier`, `challenge_bonus_xp`, confidence, data_coverage, `not_instrumented`,
`absent_behaviors`, `drivers` (ADR-104 provenance), `coverage_hold`, `neglect_decay`. Config:
`config/character_sheet.json` in S3 (5-min warm cache); tunable via the
`update_character_config` MCP tool. No env vars beyond the standard table/bucket.

**Regression harness:** `python3 scripts/character_sim_year.py` (5 scenarios × 420 days
against the real engine) + `tests/test_character_math_v2.py` — rerun both after any retune.

> **Verified against `lambdas/character_engine.py` + `config/character_sheet.json` @ char-math-v2 (#956) on 2026-07-11.**

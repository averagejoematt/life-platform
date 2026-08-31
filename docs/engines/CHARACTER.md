# Character Engine — pillars, EMA levels, XP

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-31 (cycle-15 reset re-verify — the only `config/character_sheet.json` change is the baseline block: `start_date` 2026-08-17 → **2026-09-01**, `start_weight_lbs` 321.01 → **326.24** (the reset's `--override-weight-lbs`, the 2026-08-24 last-real reading; the standing supersede reflex replaces it when the genesis-morning Withings reading syncs — tracked on #3390), `start_weight_kg` 145.608 → **147.98**, `last_updated` bumped. No pillar weight, formula, threshold or leveling knob moved; config still v1.6.0, engine still v1.8.0; `character_sheet.json` line count 571 → 571 so no citation shifted, and `character_engine.py` took zero commits since the 08-26 verify. Prior verify 2026-08-26: #2811 closing-slice re-verify — this time the ENGINE moved, and the change is a day-FRAME one: `character_engine.py`'s two `compute_date = data.get("date", <utc today>)` **defaults** flipped to `pacific_today()`. Both are fallbacks — the scheduled `character_sheet_lambda` always passes an explicit date, so the daily cascade is unchanged; the defaults only bound an off-schedule or direct-call invoke, where a UTC "today" aged the lab-decay reference day and shifted `_day_number` off the Pacific genesis anchor after 17:00 PT. **Nothing this doc documents moved**: no pillar weight, formula, threshold, tier boundary, XP/decay knob or leveling rule; config still v1.6.0, engine still v1.8.0; the doc mentions neither `compute_date` nor a day frame. One non-behavioural fold rode along — a twice-duplicated function-local `import statistics` hoisted to module scope, paying for the added `pacific_time` import so `test_module_size_guard.py` stayed byte-identical (file **2117 → 2117** lines). **All 12 `character_engine.py` citations re-derived by AST and 11 of them genuinely drifted** — a net-zero file still moves its interior: everything above :192 gained the two module-level imports (+2) and everything below :989 lost the two hoisted locals (−1 net, −2 at :401 and −2 at :989 against +1/+1 above), so `_compute_xp` 192-251 → **194-253**, `_roll_xp_buffer` 276-302 → **278-304**, `_social_quality_to_10` 791-817 → **792-818**, `derive_consistency_inputs` 893-971 → **894-972**, then the sign flips below the second hoist: `_weighted_pillar_score` 1032-1100 → **1031-1099**, `compute_ema_level_score` 1108-1129 → **1107-1128**, `neglect_decay_state` 1152-1186 → **1151-1185**, `compute_character_mood` 1193-1252 → **1192-1251**, `evaluate_level_changes` 1272-1498 → **1271-1497**, `compute_cross_pillar_effects` 1559-1614 → **1558-1613**, `PILLAR_COMPUTERS` 1690-1697 → **1689-1696**. `store_character_sheet` **:2082-2104 is unchanged** (the two shifts cancel by then) and the lambda-side `_enriched_mood_to_10` **:233-254** is untouched — `character_sheet_lambda.py` took zero commits. Every corrected range was read back to confirm it lands on the named symbol. Prior verify 2026-08-25: #2811 PT-day fleet re-verify — `character_sheet_lambda.py`'s two day derivations (`days_old` staleness + `today`) flipped from the UTC clock to `pacific_now().date()`; `character_engine.py` and `config/character_sheet.json` took ZERO commits. **Day-FRAME change, not an engine change**: no pillar weight, formula, threshold or leveling knob moved; config still v1.6.0, engine still v1.8.0. The one lambda-side citation shifts +1 from the added import: `_enriched_mood_to_10` :232-253 → **:233-254** (re-derived by AST; every `character_engine.py` citation unchanged — file untouched). Prior verify 2026-08-17: cycle-14 reset re-verify — the only `config/character_sheet.json` change is the `_meta`+baseline block: `start_date` 2026-08-10 → **2026-08-17**, `start_weight_lbs` 321.6 → **321.01** (the reset's `--override-weight-lbs`; the standing supersede reflex replaces it when the genesis-morning Withings reading syncs — currently blocked by the 08-17 Whoop-only auth latch, Withings itself healthy), `start_weight_kg` 145.875 → **145.608**, `last_updated` bumped. No pillar weight, formula, threshold or leveling knob moved; config still v1.6.0, engine still v1.8.0. **All 13 line citations re-derived by AST**: #2747's return of `character_engine.py` to its 2117-line baseline landed after the 08-15 stamp's derivation, shifting most anchors −10 (`PILLAR_COMPUTERS` 1700-1707 → **1690-1697**, `evaluate_level_changes` 1282-1508 → **1272-1498**, `_compute_xp` 202-261 → **192-251**) while `derive_consistency_inputs`/`neglect_decay_state`/`compute_character_mood` sit at **893-971**/**1152-1186**/**1193-1252** and the lambda-side `_enriched_mood_to_10` at **232-253** (now :233-254, see the 08-25 note); every corrected range read back to confirm it lands on the named symbol. Prior verify 2026-08-15: #2638 re-verify — `character_engine.py` took mypy `return-value` annotation corrections ONLY. `load_character_config` is now typed `Optional[dict]`, which is what it has always returned: None when S3 is unreadable with no warm cache, a case `character_sheet_lambda` already handles with `if not config: raise RuntimeError(...)` and a test already pins. `store_character_sheet` is typed `-> dict` (it returns the tagged record; no caller reads it, and removing the return would have been a real change). **No pillar weight, formula, threshold or leveling knob moved**; config still v1.6.0, engine still v1.8.0. Every line citation in this doc WAS re-derived from the AST rather than assumed: a 2-line cache annotation and a 7-line docstring shifted all six (`PILLAR_COMPUTERS` 1690-1697 -> 1700-1707, `evaluate_level_changes` 1266-1494 -> 1282-1508, and four more). Prior verify 2026-08-09: cycle-13 reset re-verify — the only `config/character_sheet.json` change is the baseline block: `start_date` 2026-08-03 → **2026-08-10** (genesis moved to the Monday, #2465), `start_weight_kg` 145.877 → **145.875** (the carried 321.6 lbs baseline re-derived by the pipeline), `last_updated` bumped. No pillar weight, formula, threshold or leveling knob moved; config still v1.6.0, engine still v1.8.0, and the `PILLAR_COMPUTERS` citation `character_engine.py:1690-1697` is unchanged from the 08-08 verify. Prior verify 2026-08-08: #2235 re-verify — `character_sheet_lambda.get_food_delivery_modifier` now reads the food-delivery streak through the shared `common.digest_utils.get_food_delivery_streak_state` accessor instead of a direct `STREAK#current` `get_item`, so a source past its `stale_hours` threshold yields the neutral **1.0** modifier rather than a frozen streak from the last import. That is a real behaviour change at the modifier's *input*, and it is the honest one: the stored `streak_days` is written once at ingestion and never recomputed, so once the source goes stale it is a snapshot, not a counter. Re-verified rather than date-bumped: **nothing in the engine moved** — no pillar weight, formula, threshold or leveling knob, config still v1.6.0, engine still v1.8.0, and the "Behavioral modifiers are engine inputs" contract below is unchanged (the caller still passes `raw_score_modifiers`; the engine still scales raw + unblended raw at step 1). The `PILLAR_COMPUTERS` citation `character_engine.py:1690-1697` re-checked and still resolves. Prior verify 2026-08-03: cycle-12 reset re-verify — the only `config/character_sheet.json` change is the baseline block: `start_date` 2026-07-27 → **2026-08-03**, `start_weight_lbs` 321.09 → **321.6** (the real genesis-morning weigh-in), `last_updated` bumped. No pillar weight, formula, threshold or leveling knob moved; config still v1.6.0, engine still v1.8.0, `PILLAR_COMPUTERS` citation `character_engine.py:1690-1697` re-checked and still resolves. Prior verify 2026-07-30: #1898 plan-literal re-verify — `config/character_sheet.json` protein `target_grams` 190 → **170** (the sealed cycle-11 prereg's floor; the wiped pilot's 190 had survived the reset) and `character_engine.py`'s matching hardcoded fallback. `target_grams` is a SCORING target, so protein now grades against the pre-registered plan — a real behaviour change, not a label fix. **A citation genuinely drifted and is corrected here:** the +6 lines of comment above the fallback moved `PILLAR_COMPUTERS` from `character_engine.py:1684-1693` to **:1690-1697** (verified by reading both ranges — the old one now lands on a comment header). Config still v1.6.0, all seven pillar weights unchanged, engine still v1.8.0, `character_sheet.json` line count 571 → 571. Prior verify 2026-07-29: #1891 cast re-verify — the only `config/character_sheet.json` change is two `pillars.*.owner` DISPLAY strings (metabolic `Dr. Peter Attia` → `Dr. Amara Patel`, mind `Coach Maya Rodriguez` → `Dr. Nathan Reeves`); `owner` is read by no Lambda and by no claim in this doc. Re-verified rather than date-bumped: config still v1.6.0, all seven pillar weights unchanged (sleep 0.20 / movement 0.18 / nutrition 0.18 / mind 0.15 / metabolic 0.12 / consistency 0.10 / relationships 0.07), `leveling.neglect_decay` present, file line count 571 → 571 so no citation shifted, and `character_engine.py:1684-1693` re-checked and still resolves. Prior verify 2026-07-28: #1653 packaging re-verify — `character_engine.py` moved to `lambdas/health/` and `character_sheet_lambda.py` had its imports rewritten; both are pure relocation (no formula, threshold or leveling change). Line count unchanged in `character_engine.py`, so the `character_engine.py:1684-1693` citation was re-checked and still resolves. Prior verify 2026-07-27: Day-1 re-verify: the only `config/character_sheet.json` change since 07-26 is the baseline block — the real genesis weigh-in 321.09 lbs superseding the 317.61 override; pillar weights/ema_lambda/leveling knobs and every formula untouched. Prior: #1590 re-verify — line refs + version stamps re-derived against live source; formulas unchanged since #1403; 07-26: only #1656/#1709/#1713 mypy churn in `character_engine.py`)
> Math audit + 420-day simulation verdicts: [CHARACTER_MATH_AUDIT_2026-07.md](CHARACTER_MATH_AUDIT_2026-07.md) (epic #956).
> **Sources of truth:** `lambdas/health/character_engine.py` (v1.8.0 — v1.7.0 #1373 progression receipts, v1.6.1 #1125 level-up drivers, v1.6.0 #965 source wiring; #1412 personal-baselines targets and #1411 fitted-not-authored badges shipped without an engine version bump), `lambdas/compute/character_sheet_lambda.py`, `config/character_sheet.json` (v1.6.0, deployed to `s3://…/config/matthew/character_sheet.json`)

## Purpose

Daily RPG-style character sheet: 7 weighted pillar scores → EMA-smoothed levels with
anti-flip-flop streak gates, XP with decay/debt, cross-pillar effects, and a deterministic
character mood. Runs in the `character-sheet` compute Lambda (daily, before 11 AM PT).

## The pillar model

Six primary pillars (`PILLAR_COMPUTERS`, `character_engine.py:1689-1696`): sleep, movement,
nutrition, metabolic, mind, relationships — plus the **consistency** meta-pillar computed from
the others. Config pillar weights (live `config/character_sheet.json`): sleep 0.20,
movement 0.18, nutrition 0.18, mind 0.15, metabolic 0.12, consistency 0.10, relationships 0.07.

Each pillar raw score is a weighted mean of components with a **confidence blend**
(`_weighted_pillar_score`, :1031-1099):

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
  0–10 scale via `(m−1)/4×10` (`character_sheet_lambda._enriched_mood_to_10`, :233-254).
- #910/#911: categorical `enriched_social_quality` → `social_score` 0–10 by rank,
  `rank/3×10` (alone→0, surface→3.33, meaningful→6.67, deep→10;
  `character_engine._social_quality_to_10`, :792-818), averaged across the day's entries. The
  numeric `social_connection_score` fields remain the primary path (no producer writes them yet).
- #962: `vice_streaks` is lifted from the day's habit_scores record (daily_metrics_compute has
  always written it) into the top-level key the mind pillar's vice_control component reads;
  `streak_all_above_30th` + `weekend_weekday_ratio` are derived by
  `character_engine.derive_consistency_inputs` (:894-972) from the same 21-day record window
  the EMA histories already fetch. `buddy_engagement` was removed (B-3 precedent — no producer
  ever wrote `buddy_freshness_days`); relationships weights renormalized (.45/.35/.20).

**Source wiring (#965/ADR-134 amendment, v1.6.0):** three previously-blind sources feed one
component each — all **day-count** metrics so volume gaming buys nothing:
- **hevy → movement `strength_sessions`** (weight .20, behavioral): distinct workout days in the
  trailing 7 vs a 3-day target (`fetch_hevy_workout_days` handles the `DATE#…#WORKOUT#` sort-key
  end-bound trap). A lifting week no longer reads as movement absence.
- **reading → mind `reading_practice`** (weight .10, behavioral): distinct ADR-097 session days
  in the trailing 7 vs a 4-day target, via GSI2 `READING_SESSION` (reading is CROSS_PHASE — no
  phase filter).
- **flourishing → mind `values_alignment`** (weight .10, measured — #1403): distinct
  values-in-action the journal-enrichment pass evidenced today (`SOURCE#flourishing`
  row, `lambdas/health/flourishing.py`): none-on-a-journaled-day = 20 (a real low — the LLM
  read the prose and found none), 1 = 60, 2 = 80, 3+ = 100; no row = None
  (uninstrumented, ADR-104). Rebalance: t1_habit_compliance and journal_consistency
  each .15 → .10 (mind weights still sum 1.0). The row is also the PRIMARY
  Relationships social input (the #910 entry-scan is now the fallback). Both pillars
  surface `_flourishing_provenance` ("LLM-coded from journal text (model …)") in
  details whenever the row fed a score.
- **todoist → consistency `task_follow_through`** (weight .15, measured): `100 − 12.5 ×
  overdue_count` — follow-through as overdue pressure, the one todoist signal task-volume
  gaming can't inflate. Measured class: the record is an automatic daily pull, so absence is an
  ingestion gap, never a behavior verdict.

**#1412 (no version bump — read-half in `personal_baselines.py`, not the engine):** component
targets can arrive personalized via `personal_baselines.apply_character_targets` instead of the
hand-authored config target; `_weighted_pillar_score` surfaces each target's derivation
provenance into component details. Target values still live in CONFIG, so a baselines refresh
shows as labeled `config_drift`, never `engine_drift`, in progression-receipt replay.

## EMA smoothing (`compute_ema_level_score`, :1107-1128)

Exponentially weighted mean over the last `ema_window_days` (21) raw scores, most-recent
heaviest, per-pillar decay `ema_lambda` (live: sleep 0.85, movement 0.90, nutrition 0.88,
metabolic 0.95, mind 0.85, relationships 0.93, consistency 0.93):

```
level_score = Σ(rawᵢ · λ^age) / Σ λ^age        (empty history → 50)
```

## Anti-flip-flop level rules (`evaluate_level_changes`, :1271-1497)

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

## XP and debt (`_compute_xp`, :194-253; buffer `_roll_xp_buffer`, :278-304)

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

- `neglect_decay_state` (:1151-1185): when `engagement_state.presence_class == "dark"` (and not a
  planned pause), after `n_grace_days` (3) the level score of pillars whose behavioral weight
  share ≥ 0.3 is multiplied by `0.98^(gap−3)`, floored at the day's own raw score and the config
  floor (0). Models detraining/evidence loss, never punishment (ADR-104). Knobs live in
  `config/character_sheet.json` under `leveling.neglect_decay`
  (`n_grace_days` / `rate` / `floor` / `min_behavioral_share` / `persistent_down_streak`).
- `compute_character_mood` (:1192-1251), pure code (ADR-105), first match wins:
  dark ⇒ **dormant**; quiet or 7d-composite trend ≤ −5 ⇒ **fading**; present/light AND trend ≥ +3
  AND composite ≥ 55 ⇒ **thriving**; else **steady**. Trend = mean(last 3 d) − mean(prior 4 d).

## Cross-pillar effects + overall level

Config `cross_pillar_effects` conditions evaluate EMA level_**scores** — deliberately, per
ADR-134/#963: effects model current-state physiology synergies (poor sleep drags today's
training capacity), not tier achievements; the config narrative is worded to match. The
`any_vice_streak` conditions are data-driven since #962 (`compute_cross_pillar_effects`,
:1558-1613, takes the day's vice_streaks — the Vice Shield can actually fire). Modifiers are
multiplicative: `adjusted = level_score × (1 + Σ mod)` [F-05]. **#1411 (ADR-105):** every fired
effect carries a `fit_status` badge — config can only declare `authored-prior`; `fitted` is
earned from data by the quarterly `effect_fitter` re-fit (lagged pairs, block-bootstrap CI,
BH-FDR — piggybacked on the weekly hypothesis-engine cron, `refit_cross_pillar_effects` in
`hypothesis_engine_lambda.py`) and merged in at compute/serve time, never hand-written in config.

Overall: `character_level = floor(Σ(levelᵖ·wᵖ)/Σwᵖ)` over **instrumented** pillars [F-14 +
#960/ADR-134]: a pillar that is `not_instrumented` today and still at level 1 (never earned a
level) is excluded and the weights renormalize — the frozen relationships pillar no longer
caps the reachable headline at 93 (Elite was mathematically unreachable; sim now reaches it at
~1 year of sustained raw ~90). Once a pillar levels it counts forever — going dark later drags
honestly. Excluded pillars ride the record as `headline_excluded_pillars`. Tiers Foundation
1–20 / Momentum 21–40 / Discipline 41–60 / Mastery 61–80 / Elite 81–100.

## Outputs / config surface

Record → `USER#matthew#SOURCE#character_sheet / DATE#<date>` (`store_character_sheet`,
:2082-2104; pre-genesis dates tagged `phase=pilot`), EXPERIMENT_SCOPED — wiped + rebuilt at
reset. Per-pillar output carries raw_score, level_score, level, tier, xp_total/xp_delta/xp_debt,
`raw_modifier`, `challenge_bonus_xp`, confidence, data_coverage, `not_instrumented`,
`absent_behaviors`, `drivers` (ADR-104 provenance), `coverage_hold`, `neglect_decay`. Config:
`config/character_sheet.json` in S3 (5-min warm cache); tunable via the
`update_character_config` MCP tool. No env vars beyond the standard table/bucket.

**Regression harness:** `python3 scripts/character_sim_year.py` (5 scenarios × 420 days
against the real engine) + `tests/test_character_math_v2.py` — rerun both after any retune.

> **Verified against `lambdas/health/character_engine.py` (v1.8.0) + `config/character_sheet.json` (v1.6.0) @ git `fab48cbd` on 2026-07-20 (#1590).**

# Scoring Engine — the Day Grade

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-24 (#3135 DIL-024 re-verify — `daily_metrics_compute_lambda.py` changed, `scoring_engine.py` did NOT (git log confirms zero commits to it since 08-15). The one change is `get_source_fingerprints`'s hand-typed `sources` default collapsing to a derivation from the new `common.input_manifest.COMPUTE_INPUTS["daily-metrics-compute"]` registry (#2844 ledger paydown) — a late-arrival recompute-trigger function this doc does not cite or describe anywhere (no line span into `daily_metrics_compute_lambda.py` exists in this doc to re-derive). **Not material**: no weight, target, threshold, formula or grade band moved, and every `scoring_engine.py` line citation below is confirmed byte-identical since it was last re-derived at the 08-15 verify. Prior verify 2026-08-15: #2638 re-verify — `scoring_engine.py` took mypy `return-value` annotation corrections ONLY: `ScoreTuple` now declares `Optional[Numeric]` instead of `Optional[int]`, matching what every scorer has always returned (`clamp()` is `Numeric -> Numeric`), and `compute_day_grade`'s annotation was corrected from a 3-tuple to the 4-tuple it actually returns. **No weight, target, threshold, formula or grade band moved, and no returned VALUE changed** — verified by 889 passing behaviour tests across the scoring path. Every line citation in this doc WAS re-derived rather than assumed: a 6-line explanatory comment above `ScoreTuple` shifted all eleven of them, so each was recomputed from the AST (`score_sleep` 57-92 -> 63-98, `compute_day_grade` 462-482 -> 468-490, and nine more). Prior verify 2026-08-08: #2242 re-verify — `store_habit_scores` now persists the running Tier-0 perfect-day streak as `t0_perfect_streak` on the habit_scores record documented under Outputs below. It is a **transport** change, not a scoring one: the streak was already computed and already written to `computed_metrics`; it simply never reached the row the award readers query, so eleven streak awards were unearnable against a permanent 0. No weight, target, threshold or grade formula moved, and `scoring_engine.py` is untouched. Prior verify 2026-08-04: #2109 window re-verify — `daily_metrics_compute_lambda.fetch_range` now derives its ADR-058 phase scope per source from `phase_taxonomy` (trailing weight/HRV/load windows read across a reset; EXPERIMENT_SCOPED sources stay filtered). Storage-window change only: `scoring_engine.py` is untouched, its line count is unchanged, and both cited ranges (414-423, 462-482) still resolve. **No documented scoring formula moved.** Prior verify 2026-07-28: #1653 packaging re-verify — `scoring_engine.py` moved to `lambdas/health/` and `daily_metrics_compute_lambda.py` had its imports rewritten. Documented formulas are untouched; `scoring_engine.py` line count is unchanged and both cited ranges (414-423, 462-482) were re-checked byte-for-byte against the pre-move source. Prior verify 2026-07-27: post-#970 — scoring_engine deliberately KEPT its typed safe_float; formulas unchanged. 2026-07-13: docstring reword only, now that the shared layer is retired by #781 — no logic change. 2026-07-26 re-verify: only #1656 mypy type-annotation churn in `scoring_engine.py`/`daily_metrics_compute_lambda.py` since; documented formulas unchanged. 2026-07-27 re-verify: #1843 added the `diary_sessions` computed field to daily_metrics_compute — additive storage only; the documented scoring formulas are untouched)
> **Sources of truth:** `lambdas/health/scoring_engine.py`, `lambdas/compute/daily_metrics_compute_lambda.py`, profile record `USER#matthew / PROFILE#v1` (`day_grade_weights`)

## Purpose

Computes the daily letter grade (A+…F) shown in the daily brief and the cockpit. Pure functions
(no AWS calls) in `lambdas/health/scoring_engine.py`; invoked by `daily_brief_lambda.py` and
`daily_metrics_compute_lambda.py`, which persist the result.

## Inputs

One day's gathered data dict (per-source records: `sleep`, `whoop`, `macrofactor`, `strava`,
`apple`, `habitify` + `habitify_7d`, `journal_entries`) and the user profile (targets + weights).

## The math

Eight component scorers, each returning `(score 0–100 | None, details)` (`COMPONENT_SCORERS`,
`scoring_engine.py:422-431`). A component with no data returns `None` and drops out entirely.

**Day Grade** (`compute_day_grade`, `scoring_engine.py:468-490`): weighted mean over components
that have both a score and a positive weight; weights re-normalize over the active set.

```
total = clamp(round( Σ(scoreᵢ · wᵢ) / Σ wᵢ ))   over components with scoreᵢ ≠ None and wᵢ > 0
```

Weights come from `profile["day_grade_weights"]` — **no code defaults** (missing weight = 0 =
excluded). Live values (read from `PROFILE#v1`, 2026-07-10): sleep_quality 0.20, nutrition 0.20,
recovery 0.15, movement 0.15, habits_mvp 0.15, hydration 0.05, journal 0.05, glucose 0.05.

### Component formulas (values from code)

- **sleep_quality** (`score_sleep`, :63-98): Whoop `sleep_score`×0.40 + `sleep_efficiency_pct`×0.30
  + duration-vs-target×0.30, re-normalized over present parts.
  `dur_score = clamp(100 − |hrs − target|/2.0 × 100)`; target `sleep_target_hours_ideal` (default 7.5).
- **recovery** (`score_recovery`, :101-105): Whoop `recovery_score`, used directly (clamped).
- **nutrition** (`score_nutrition`, :108-168): calories 0.40 + protein 0.40 + macro split 0.20.
  - Calories: 100 inside ±`calorie_tolerance_pct` (default 10%) of `calorie_target` (default 1800);
    linear to 0 at `calorie_penalty_threshold_pct` (default 25%) off; **surplus asymmetry:** eating
    above target+tolerance subtracts a further 15 points ("surplus directly stalls weight loss").
  - Protein: 100 at ≥ `protein_target_g` (default 190); 80→100 linear between `protein_floor_g`
    (default 170) and target; below floor `max(0, 80·protein/floor)`.
  - Macros: `clamp(100 − (|fat−60|/60 + |carbs−125|/125) × 50)` (defaults fat 60 g, carbs 125 g;
    50× multiplier ⇒ 100% off on both = 0).
- **movement** (`score_movement`, :171-200): exercise 0.50 + steps 0.50.
  - Exercise (Strava): any activity ⇒ `min(100, 70 + moving_minutes × 0.5)` (base 70 for showing
    up; 60 min ⇒ 100); no activity ⇒ 0.
  - Steps (Apple): `min(100, steps/step_target × 100)`, `step_target` default 7000.
- **habits_mvp** (`score_habits_registry`, :203-300): tier-weighted over the profile
  `habit_registry`. Tier weights **T0 3.0×, T1 1.0×, T2 0.5×**; T0/T1 binary (100/0 per habit),
  T2 scored as rolling 7-day frequency vs `target_frequency`. Weekday-only habits skip weekends;
  `post_training` habits only count on Strava-activity days; per-habit `scoring_weight`
  down-weights emerging-evidence habits. Composite = Σ(tier_avg·tier_w)/Σ tier_w. Falls back to
  the legacy flat `mvp_habits` percentage when the registry is empty.
- **hydration** (`score_hydration`, :324-337): `min(100, water_ml/target × 100)`, target
  `water_target_ml` default 2957. Readings **< 500 ml are treated as no-data** (HAE sync
  artifacts deliver ~350 ml on truncated payloads).
- **journal** (`score_journal`, :340-362): morning AND evening template ⇒ 100; one of them ⇒ 60;
  entries without either template ⇒ 40; no entries ⇒ None.
- **glucose** (`score_glucose`, :365-415): TIR 0.50 + avg 0.30 + std-dev 0.20 (piecewise linear:
  TIR ≥95 ⇒ 100, 90–95 ⇒ 80–100, 70–90 ⇒ 0–80; avg <95 ⇒ 100, 95–100 ⇒ 80–100, 100–140 ⇒ 80–0;
  std <15 ⇒ 100, 15–20 ⇒ 80–100, 20–40 ⇒ 80–0).

### Letter grade (`letter_grade`, :434-455)

```
A+ ≥95 · A ≥90 · A− ≥85 · B+ ≥80 · B ≥75 · B− ≥70 · C+ ≥65 · C ≥60 · C− ≥55 · D ≥45 · F <45
```

## Outputs

- `USER#matthew#SOURCE#day_grade / DATE#<date>` — the grade series (RAW_TIMESERIES: kept across
  resets, genesis-clamped on read; ADR-077 dec C) — written by the daily brief's
  `store_day_grade` path.
- `USER#matthew#SOURCE#computed_metrics / DATE#<date>` — day grade + components + readiness etc.
  (`daily_metrics_compute_lambda.store_computed_metrics`), EXPERIMENT_SCOPED.
- `USER#matthew#SOURCE#habit_scores / DATE#<date>` — habit tier detail plus `t0_perfect_streak`,
  the running Tier-0 perfect-day streak the award ladder reads (#2242 — written even when 0, so a
  reset reads as a reset rather than as missing data), EXPERIMENT_SCOPED.

## Config surface

All targets/weights live on the profile record (`PROFILE#v1`): `day_grade_weights`,
`sleep_target_hours_ideal`, `calorie_target`, `calorie_tolerance_pct`,
`calorie_penalty_threshold_pct`, `protein_target_g`, `protein_floor_g`, `fat_target_g`,
`carb_target_g`, `step_target`, `water_target_ml`, `habit_registry`, `mvp_habits`. No env vars.

> **Verified against `lambdas/health/scoring_engine.py` (byte-identical since the 08-15 verify — confirmed via `git log --since=2026-08-15`) and `lambdas/compute/daily_metrics_compute_lambda.py` (changed by #3135, not material — see header) @ git `55f939c86` on 2026-08-24 (#3135).**

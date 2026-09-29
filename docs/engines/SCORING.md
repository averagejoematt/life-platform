# Scoring Engine — the Day Grade

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-09-29 (#4362 re-verify — both declared sources moved by #4399 (`0f24b3d6f`), read in full. **MATERIAL to this doc (habits_mvp):** `scoring_engine.habitify_reading` (new, :203-226) resolves a registry habit through its own key AND every name in its optional `habitify_names` list, and returns None when the day's record names it under none of them. `score_habits_registry` now treats that None as UNOBSERVED — the habit is skipped (not scored 0, and not counted in `tier0`/`tier1` `total`) and listed in a new `details["unobserved"]` — where before `.get(name, 0)` scored it a miss; the T2 7-day frequency count resolves renames the same way. A day where every applicable habit is unobserved now returns `(None, {})`, so habits_mvp drops out of the grade and the weights re-normalise. The `t0_perfect_streak` written to `habit_scores` now comes from `health.habit_streaks` (the daily brief's #2221 scan: absent = unknown, gaps ≤ 3 days skipped) via a thin `daily_metrics_compute_lambda.compute_habit_streaks` delegate — the in-module copy that read an absent habit, or a missing day, as a break is gone. The habits_mvp bullet and the Outputs bullet say this. **NOT material:** tier weights (3.0/1.0/0.5), the other seven scorers, `COMPONENT_SCORERS`, `letter_grade`, `compute_day_grade` and `store_computed_metrics` are byte-unchanged. Re-derived by AST on `origin/main` `ea9fec281` (every span after `score_movement` shifted **+34**, pre-#4399 spans re-checked against `0f24b3d6f^` first): `score_habits_registry` :203-300 → **:229-334**, `score_hydration` → **:358-371**, `score_journal` → **:374-396**, `score_glucose` → **:399-449**, `COMPONENT_SCORERS` → **:456-465**, `letter_grade` → **:468-489**, `compute_day_grade` → **:502-524**; `score_sleep`/`score_recovery`/`score_nutrition`/`score_movement` unchanged. Prior verify 2026-09-27: #4184 second re-verify — `daily_metrics_compute_lambda.assemble_data` no longer builds the weight-trajectory series itself: the `withings_28d` fetch + `weight_trend.weight_trajectory` call are replaced by one call to `weight_trend.fetch_experiment_trajectory(fetch_range, today, EXPERIMENT_START_DATE, goal, ref_dt=pacific_now())`, whose window (`experiment_rate_window`) is genesis-clamped AND ends TODAY rather than yesterday, the same window `site_api_journey.journey()` now reads, so `public_stats.json` and `/api/journey` state one rate. It adds one read (`apple_health`, last 7 days, for the current-weight tie-break) that feeds only `weight_traj`. **Not a scoring change**: `weight_traj` is still the journey/brief projection, not a day-grade input; `data`'s day-grade keys (journal, glucose, sleep, macrofactor, strava, apple, habitify) are built by untouched lines; `compute_day_grade(data, profile)` and `store_computed_metrics` are unchanged (re-read in the diff); `lambdas/health/scoring_engine.py` took ZERO commits since the 09-23 verify (git log confirms). This doc cites no line spans into `daily_metrics_compute_lambda.py`, only the function names `store_computed_metrics` and `compute_day_grade`, both re-checked by AST as present, so no span needed re-deriving. Prior verify 2026-09-26: #4184 re-verify — `daily_metrics_compute_lambda.py`'s `assemble_data` clamps the `withings_28d` fetch that feeds `weight_traj` (`weight_trend.weight_trajectory`) to `max(today - 28d, EXPERIMENT_START_DATE)`, mirroring `site_api_journey.journey()`'s `d120` clamp, so a flat 28-day window no longer reaches across the 2026-09-06 genesis into the prior cycle's weigh-ins. **Not a scoring change**: `weight_traj`/`weight_trajectory` is the journey/brief weight-trend projection, not a day-grade input — this doc's Inputs section (journal, glucose, sleep, macrofactor, strava, apple, habitify) never cites it, and `scoring_engine.py` took ZERO commits since the 09-23 verify (git log confirms), so no line citation below is re-derived. Prior verify 2026-09-23: #4129 end-bound re-verify — `daily_metrics_compute_lambda.fetch_range` now ends its window at `DATE#{end}~` instead of `DATE#{end}`, so a partition with suffixed sks (hevy `DATE#<d>#WORKOUT#<id>`, whoop workout sub-rows) returns the END day's sub-rows like every other day in the window. **Input-window correction, not a scoring change**: no weight, target, threshold, formula or grade band moved; `scoring_engine.py` took ZERO commits since the 09-02 verify (git log confirms) and every line citation below is into that untouched file. What the change moves: TSB/CTL/ATL now count yesterday's Hevy session on the run that follows it (it previously landed one day late); the whoop-fed HRV averages and sleep-debt sum are unchanged by construction — workout sub-rows carry no `hrv` and no `sleep_duration_hours`, and both reads already filter on those fields (re-checked). The other windows (strava, withings, habitify, macrofactor) have no suffixed rows, where the `~` admits nothing. Prior verify 2026-09-02: #3443 co-owned-write re-verify — `daily_metrics_compute_lambda.py` changed: `store_computed_metrics` + the sick-day rebuild now carry acwr-compute's merged `acwr_*`/load fields through their from-scratch re-puts (registry `compute/computed_metrics_contract.py`). **Write-contract change, not a scoring change**: no weight, target, threshold, formula or grade band moved; `scoring_engine.py` took ZERO commits (git log confirms) and every line citation below is into that untouched file, so none is re-derived. Prior verify 2026-08-25: #2811 PT-day fleet re-verify — `daily_metrics_compute_lambda.py`'s day derivations flipped UTC → Pacific (`pacific_today()`/`pacific_now()`) and `tag_record` was hoisted to module scope; `scoring_engine.py` took ZERO commits (git log confirms) and every line citation below is into that untouched file, so none is re-derived. **Day-FRAME change at the storage layer, not a scoring change**: no weight, target, threshold, formula or grade band moved — a 17:00-PT-to-midnight run now grades the Pacific day the site names rather than the rolled UTC day. Prior verify 2026-08-24: #3135 DIL-024 re-verify — `daily_metrics_compute_lambda.py` changed, `scoring_engine.py` did NOT (git log confirms zero commits to it since 08-15). The one change is `get_source_fingerprints`'s hand-typed `sources` default collapsing to a derivation from the new `common.input_manifest.COMPUTE_INPUTS["daily-metrics-compute"]` registry (#2844 ledger paydown) — a late-arrival recompute-trigger function this doc does not cite or describe anywhere (no line span into `daily_metrics_compute_lambda.py` exists in this doc to re-derive). **Not material**: no weight, target, threshold, formula or grade band moved, and every `scoring_engine.py` line citation below is confirmed byte-identical since it was last re-derived at the 08-15 verify. Prior verify 2026-08-15: #2638 re-verify — `scoring_engine.py` took mypy `return-value` annotation corrections ONLY: `ScoreTuple` now declares `Optional[Numeric]` instead of `Optional[int]`, matching what every scorer has always returned (`clamp()` is `Numeric -> Numeric`), and `compute_day_grade`'s annotation was corrected from a 3-tuple to the 4-tuple it actually returns. **No weight, target, threshold, formula or grade band moved, and no returned VALUE changed** — verified by 889 passing behaviour tests across the scoring path. Every line citation in this doc WAS re-derived rather than assumed: a 6-line explanatory comment above `ScoreTuple` shifted all eleven of them, so each was recomputed from the AST (`score_sleep` 57-92 -> 63-98, `compute_day_grade` 462-482 -> 468-490, and nine more). Prior verify 2026-08-08: #2242 re-verify — `store_habit_scores` now persists the running Tier-0 perfect-day streak as `t0_perfect_streak` on the habit_scores record documented under Outputs below. It is a **transport** change, not a scoring one: the streak was already computed and already written to `computed_metrics`; it simply never reached the row the award readers query, so eleven streak awards were unearnable against a permanent 0. No weight, target, threshold or grade formula moved, and `scoring_engine.py` is untouched. Prior verify 2026-08-04: #2109 window re-verify — `daily_metrics_compute_lambda.fetch_range` now derives its ADR-058 phase scope per source from `phase_taxonomy` (trailing weight/HRV/load windows read across a reset; EXPERIMENT_SCOPED sources stay filtered). Storage-window change only: `scoring_engine.py` is untouched, its line count is unchanged, and both cited ranges (414-423, 462-482) still resolve. **No documented scoring formula moved.** Prior verify 2026-07-28: #1653 packaging re-verify — `scoring_engine.py` moved to `lambdas/health/` and `daily_metrics_compute_lambda.py` had its imports rewritten. Documented formulas are untouched; `scoring_engine.py` line count is unchanged and both cited ranges (414-423, 462-482) were re-checked byte-for-byte against the pre-move source. Prior verify 2026-07-27: post-#970 — scoring_engine deliberately KEPT its typed safe_float; formulas unchanged. 2026-07-13: docstring reword only, now that the shared layer is retired by #781 — no logic change. 2026-07-26 re-verify: only #1656 mypy type-annotation churn in `scoring_engine.py`/`daily_metrics_compute_lambda.py` since; documented formulas unchanged. 2026-07-27 re-verify: #1843 added the `diary_sessions` computed field to daily_metrics_compute — additive storage only; the documented scoring formulas are untouched)
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
`scoring_engine.py:456-465`). A component with no data returns `None` and drops out entirely.

**Day Grade** (`compute_day_grade`, `scoring_engine.py:502-524`): weighted mean over components
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
- **habits_mvp** (`score_habits_registry`, :229-334): tier-weighted over the profile
  `habit_registry`. Tier weights **T0 3.0×, T1 1.0×, T2 0.5×**; T0/T1 binary (100/0 per habit),
  T2 scored as rolling 7-day frequency vs `target_frequency`. Weekday-only habits skip weekends;
  `post_training` habits only count on Strava-activity days; per-habit `scoring_weight`
  down-weights emerging-evidence habits. Composite = Σ(tier_avg·tier_w)/Σ tier_w. Falls back to
  the legacy flat `mvp_habits` percentage when the registry is empty.
  **A habit the day's Habitify record does not name is UNOBSERVED, never a miss** (#4362,
  `habitify_reading`, :203-226): each registry entry resolves through its own key and its
  `habitify_names` list (the names it has carried in Habitify, so a rename upstream still
  resolves); an unresolved habit is skipped — out of the tier average and the `tier0`/`tier1`
  totals — and named in `details["unobserved"]`. If every applicable habit is unobserved the
  component returns None and drops out of the grade.
- **hydration** (`score_hydration`, :358-371): `min(100, water_ml/target × 100)`, target
  `water_target_ml` default 2957. Readings **< 500 ml are treated as no-data** (HAE sync
  artifacts deliver ~350 ml on truncated payloads).
- **journal** (`score_journal`, :374-396): morning AND evening template ⇒ 100; one of them ⇒ 60;
  entries without either template ⇒ 40; no entries ⇒ None.
- **glucose** (`score_glucose`, :399-449): TIR 0.50 + avg 0.30 + std-dev 0.20 (piecewise linear:
  TIR ≥95 ⇒ 100, 90–95 ⇒ 80–100, 70–90 ⇒ 0–80; avg <95 ⇒ 100, 95–100 ⇒ 80–100, 100–140 ⇒ 80–0;
  std <15 ⇒ 100, 15–20 ⇒ 80–100, 20–40 ⇒ 80–0).

### Letter grade (`letter_grade`, :468-489)

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
  reset reads as a reset rather than as missing data), EXPERIMENT_SCOPED. Since #4362 the streak
  is `health.habit_streaks.compute_habit_streaks` — the same scan the daily brief runs — so an
  absent or renamed habit, or a missing Habitify day inside a ≤ 3-day gap, does not break it.

## Config surface

All targets/weights live on the profile record (`PROFILE#v1`): `day_grade_weights`,
`sleep_target_hours_ideal`, `calorie_target`, `calorie_tolerance_pct`,
`calorie_penalty_threshold_pct`, `protein_target_g`, `protein_floor_g`, `fat_target_g`,
`carb_target_g`, `step_target`, `water_target_ml`, `habit_registry`, `mvp_habits`. No env vars.

> **Verified against `lambdas/health/scoring_engine.py` (byte-identical since the 08-15 verify — confirmed via `git log --since=2026-08-15`) and `lambdas/compute/daily_metrics_compute_lambda.py` (changed by #3135, not material — see header) @ git `55f939c86` on 2026-08-24 (#3135).**

# Hypothesis Engine

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11 (post-#970: its query_range now the paginated digest_utils implementation — the silent 1MB truncation class is gone; formulas unchanged)
> **Sources of truth:** `lambdas/compute/hypothesis_engine_lambda.py` (v2, #530/ADR-105), `lambdas/stats_core.py`

## Purpose

Weekly (Sunday 11 AM PT) cross-domain hypothesis loop: an LLM proposes hypotheses **with a
frozen machine-checkable test spec** (the pre-registration); pure Python decides every verdict;
every resolution writes a calibration-ledger row. ADR-105 rule 3: deterministic before narrative
— no LLM ever sees the data at check time.

## Inputs

30 days of multi-source data (`whoop, garmin, macrofactor, apple_health, withings, strava,
notion, habitify, eightsleep`) flattened to day-rows by `build_data_narrative` (:363-449).
Checks see the full 30 days (`LOOKBACK_DAYS`); generation sees the last 14 (`GENERATION_DAYS`).
Generation requires ≥10 days with ≥5 non-null metrics (`MIN_DATA_DAYS`, `MIN_METRICS_PER_DAY`).

## The pre-registered test spec (#530)

At creation the LLM must emit a `test_spec`, validated deterministically and **frozen** —
hypotheses without a parseable spec are rejected (`validate_test_spec`, :551-598):

- `condition_metric`, `outcome_metric` — both from the fixed `SPEC_METRICS` vocabulary
  (:129-161, exactly what `build_data_narrative` emits — a spec can only reference values the
  check path can compute), and must differ.
- `condition_op` ∈ {`>=`, `<=`, `median_split`} (+ numeric `condition_threshold` for the first two)
- `direction` ∈ {higher, lower}; `min_effect ≥ 0` (outcome units); `lag_days` 0–3.

Other creation gates (`validate_hypothesis`, :463-515): required fields incl. confidence ∈
{low, medium, high}; ≥2 domains; a numeric threshold with units in `confirmation_criteria`;
`monitoring_window_days` 7–30; >50% word-overlap duplicate rejection. Caps: ≤5 new per run
(`MAX_NEW_HYPOTHESES`), ≤20 pending (`MAX_PENDING_HYPOTHESES`).

## The deterministic check (`evaluate_test_spec`, :601-704)

Pure Python, weekly, per pending/confirming hypothesis that is ≥7 days old
(`MIN_SAMPLE_DAYS_FOR_CHECK`):

1. Pair each day's condition value with the outcome value at `lag_days` offset.
2. Split into condition vs comparison arms (threshold, or median split with strictly-above).
3. Require ≥5 days per arm (`MIN_DAYS_PER_ARM`) and ≥10 pairs total; else inconclusive.
4. `effect = mean(condition) − mean(comparison)`; moving-block-bootstrap 95% CI
   (`stats_core.bootstrap_mean_diff_ci`) + Cohen's d.

```
supported     — CI excludes 0 in the predicted direction AND |effect| ≥ min_effect
contradicted  — CI excludes 0 in the OPPOSITE direction
inconclusive  — arms too thin or CI straddles 0
```

## Lifecycle (status machine, :1040-1116)

```
pending ── supported (window open) ──▶ confirming
pending/confirming ── supported AND days_old ≥ monitoring_window ──▶ confirmed   (resolution)
pending/confirming ── contradicted ──▶ refuted                                   (resolution)
pending/confirming ── window expired, no verdict ──▶ archived / expired_undecided (resolution)
anything non-terminal older than 30 days ──▶ archived (hard expiry, :518-542)
```

v1 legacy hypotheses (no `test_spec`) are never checked — they age out via hard expiry.
On resolution, Haiku **narrates** the already-decided verdict (one sentence, only numbers from
the deterministic evidence string; fail-soft to the deterministic sentence — `narrate_resolution`,
:790-825).

## Outputs

- `USER#matthew#SOURCE#hypotheses / HYPOTHESIS#<ISO-ts>` — the hypothesis + frozen spec +
  per-check stats (`effect_size`, `ci95_low/high`, `cohens_d`, arm counts, `deterministic_verdict`;
  :309-360). EXPERIMENT_SCOPED (wiped at reset).
- `USER#matthew#SOURCE#calibration / CALIB#<date>#<hypothesis_id>` — one row per resolution with
  stated confidence, outcome, effect + CI (`build_calibration_item`, :735-760). **CROSS_PHASE**:
  the long-run "do high-confidence bets confirm more often?" scoreboard survives resets.
- A compact monitoring block into `platform_memory` for the digest lambdas (IC-16).
- Consumers: MCP `get_hypotheses` / `update_hypothesis_outcome`, `/api/hypotheses`.

## Config surface

Env: `AI_MODEL`, `AI_MODEL_HAIKU` (default `claude-haiku-4-5-20251001`), `TABLE_NAME`, `USER_ID`,
`S3_BUCKET`. Thresholds are module constants (:101-165), not config files. Cost ≈ $0.05/week —
one generation call; the check path is free except resolution narration.

> **Verified against `lambdas/compute/hypothesis_engine_lambda.py` @ git 4d132ec7 on 2026-07-10.**

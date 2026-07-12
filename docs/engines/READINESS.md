# Readiness Score

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11 (post-#970 helper consolidation — formulas unchanged)
> **Sources of truth:** `lambdas/compute/daily_metrics_compute_lambda.py` (`compute_readiness`, :280-320), `mcp/tools_health.py` (`tool_get_readiness_score`), `lambdas/training_load.py`, `lambdas/personal_baselines.py` (`readiness_hrv_score`, :184-199)

## Purpose

One 0–100 "how hard can I go today" composite. Two implementations exist **by design**:
the pre-compute model (daily, stored) and the live MCP tool model; the MCP tool cross-checks
itself against the stored value as a drift detector.

## Model 1 — pre-computed (the stored score)

`daily_metrics_compute_lambda.compute_readiness(data, baselines)` — runs daily before 11 AM PT,
stored on `USER#matthew#SOURCE#computed_metrics / DATE#<date>` as `readiness_score`,
`readiness_colour`, plus the component `breakdown` (#492/M-4: the actual inputs are stored
beside the score).

Components (weight re-normalizes over whichever are present):

| component | weight | score formula |
|---|---|---|
| Whoop recovery (today, else yesterday) | 0.40 | `recovery_score` used directly |
| Whoop sleep score | 0.25 | `sleep_score` used directly |
| HRV trend (7d avg / 30d avg) | 0.20 | `personal_baselines.readiness_hrv_score(ratio)` — piecewise linear through personal percentile anchors {p10→0, p50→50, p90→100}, clamped; fallback anchors {0.75, 1.0, 1.25} reproduce the legacy `clamp((ratio − 0.75) × 200)` exactly (#543/ADR-105 rule 4) |
| TSB (training form) | 0.10 | `clamp(round(60 + tsb × 2))` — TSB 0 → 60, −30 → 0, +20 → 100 |

```
score = round( Σ(vᵢ·wᵢ) / Σwᵢ )
colour: green ≥ 80 · yellow ≥ 60 · red < 60
```

Sleep is 25% (not 30%) deliberately, to stay aligned with the MCP model so the cross-check is a
true drift detector (comment at :282-285).

**TSB input:** Banister model in `lambdas/training_load.py` — CTL (42-day fitness), ATL (7-day
fatigue), `TSB = CTL − ATL`, over a 60-day Strava+Hevy window; loads are TSS-like points
(100 ≈ 1 h at threshold), with a moving-time fallback for walks and a Hevy strength proxy
calibrated to the same scale (#490).

## Model 2 — live MCP tool (`get_readiness_score`)

`mcp/tools_health.py:13-390`. Same first four components with different sub-formulas, plus a
fifth:

| component | weight | formula |
|---|---|---|
| whoop_recovery | 0.40 | direct |
| sleep_quality | 0.25 | native `sleep_score`; fallback `clamp(efficiency − 25)` |
| hrv_trend | 0.20 | `clamp(60 + (ratio − 1) × 200)` — fixed map, not personal bands (reads `hrv_7d`/`hrv_30d` from computed_metrics; live 30d Whoop query as fallback) |
| training_form (TSB) | 0.10 | `clamp(70 + tsb × 2.5)` — +12 → 100, −28 → 0 (reads `tsb` from computed_metrics; live Banister fallback) |
| garmin_body_battery | 0.05 | Body Battery used directly — **freshness-gated:** skipped when the Garmin record is >1 day older than the newest Whoop record; freed weight re-normalizes onto the rest |

Label bands differ from the stored colour: `GREEN ≥ 70 · YELLOW ≥ 40 · RED < 40`
(tools_health.py:315-319). The tool also emits a Whoop-vs-Garmin `device_agreement` block
(HRV Δ ≤10 ms agree / ≤20 minor / else flag; RHR Δ ≤3 bpm / ≤6 / flag) and a
`_precomputed_cross_check` against the stored `readiness_score`.

## Ambiguities (flagged, not resolved here)

- The two models use **different HRV maps** (personal bands vs fixed 60+200·(r−1)), **different
  TSB maps** (60+2·tsb vs 70+2.5·tsb) and **different traffic-light bands** (80/60 vs 70/40).
  The code comment claims the models are identical "on the typical day" (Garmin stale → Body
  Battery gated out), which holds for the weights but not for these sub-formula differences —
  the cross-check tolerance absorbs it. Documented as found.

## Outputs / config

Stored: `computed_metrics` record (EXPERIMENT_SCOPED — wiped at reset). No env vars; personal
HRV anchors come from the `personal_baselines` compute (`personal_baselines_lambda.py`).

> **Verified against `lambdas/compute/daily_metrics_compute_lambda.py` and `mcp/tools_health.py` @ git 4d132ec7 on 2026-07-10.**

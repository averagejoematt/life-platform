# Handover — v6.9.3: IC-4 failure-pattern detectors implemented

**Date:** 2026-05-03 (very late evening, after v6.9.2)
**Trigger:** User asked to do the open items I'd flagged. Investigation showed compute-pipeline-stale was already wired (no work), momentum-warning was not in CDK at all (defer), but failure-pattern-compute had 4 stub detectors with downstream consumer waiting.
**Scope:** Replace 4 `return []` / `return {}` stubs in `failure_pattern_compute_lambda.py` with real detectors + ship + test.

---

## What changed

### `lambdas/failure_pattern_compute_lambda.py`

Replaced these 4 stubs with real implementations:

| Function | Returns | Logic |
|---|---|---|
| `_detect_habit_skip_predictors` | top 3 highest-lift habits | For each habit appearing in any `missed_tier0` list, compute `P(bad day | habit skipped) / baseline_bad_rate`. Filter `n_skipped >= 3` and `lift > 1.0`. |
| `_detect_cascade_patterns` | list of cascade dicts | Whoop `sleep_score < 60` → next-day `day_grade < 60` conditional probability with lift over baseline. |
| `_detect_day_of_week_clusters` | dict of `{dow: {mean, delta, risk_level}}` | Group habit `composite_score` by weekday. Flag DOWs ≥5pt below overall mean as `elevated`, ≥2pt as `mild`. |
| `_detect_rebound_speed` | `{mean_days, median_days, p90_days, n_episodes}` | Walk dates, find bad-day runs (grade < 60), measure days to recovery (grade ≥ 70). |

All implementations:
- Pure functions (no DDB I/O — handler does that)
- Decimal-safe (coerce to float at the boundary)
- Defensive on empty/missing data (return `{}` or `[]` cleanly)
- Filter low-N cases (`n >= 3` minimums)

### `tests/test_failure_pattern_detectors.py` (NEW)

12 unit tests covering: happy path for each detector, low-N filter, empty input, no-pattern when baseline is already at extreme, recovery measurement boundaries. All pass without AWS / boto3 (boto3 stubbed in test setup).

### Deploy

```
bash deploy/deploy_lambda.sh failure-pattern-compute lambdas/failure_pattern_compute_lambda.py
```

Test-invoked post-deploy. Returned `{"status": "data_gate_not_met", "days_available": 41, "days_required": 42}` — gate is exactly 1 day short, will tip over tomorrow. Natural Sunday cron `cron(45 18 ? * SUN *)` at 11:45 AM PT will exercise the real path next Sunday.

---

## What was investigated but NOT changed (and why)

### `compute-pipeline-stale` alarm — already wired

I'd noted this in HANDOVER_v6.9.1.md as "vestigial CDK definition; needs emitter or removal." That was wrong. `daily_brief_lambda.py:1519` emits `LifePlatform/ComputePipelineStaleness` once per day. Today's ALARM was real (computed_metrics WAS stale at brief time). Will self-clear tomorrow when fresh daily-brief emits 0. **No work needed; correction recorded.**

### `momentum_warning_compute_lambda.py` — not in CDK, not deployed

6 similar TODO stubs exist in the source file, but the Lambda is NOT registered in any CDK stack. There's no IAM role, no EventBridge schedule, no CloudWatch alarm. Wiring it up is a CDK + IAM + scheduling change — not a low-risk autonomous edit. **Defer next session.** Suggested workflow:
1. Decide if the 6 detectors are still wanted (some overlap with anomaly-detector / acwr-compute that already ship)
2. If yes: write a CDK addition + role policy + schedule (~30 min)
3. Then implement the 6 stubs (~2-3 hours)
4. Test + deploy

### WR-47 phase 2 — comprehensive spec already exists

`docs/WR_47_48_ARCHITECTURE_SPEC.md` (297 lines) has the full design: DDB `PAUSE#` schema, `start_pause` / `end_pause` MCP tools, EventBridge programmatic disable, ~10 Lambda short-circuits to read pause state, "On Coming Back" subscriber email mode. Multi-session work; not autonomous.

### WR-49 (one-click manual backfill UI) — design needed

Not specced. Would need: admin page with per-source "force re-sync" buttons → site-api endpoint → Lambda invocation. UI design + backend endpoints + auth. **Defer; needs design conversation.**

### WR-50 — gated on WR-47 phase 2

Re-entry day template auto-loads from `docs/RUNBOOK_REENTRY.md` items. Defer until phase 2 ships.

### TD-11 step 2, TD-17, TD-19 phase 3 — Matthew action / approval gated

Unchanged.

---

## State as of 9pm PT

| Metric | Value |
|---|---|
| Alarms in ALARM | 0 (per v6.9.2 cleanup) |
| failure-pattern-compute | Deployed, ready for tomorrow's data-gate-met first real run |
| Test count | +12 (12 new unit tests, all green) |
| CI | Will run on push; no breaking changes |

---

**Previous:** [HANDOVER_v6.9.2.md](HANDOVER_v6.9.2.md) — CI unblock + alarm noise reduction

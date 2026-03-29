# Handover — v3.4.1: Sick Day System
**Date:** 2026-03-10  
**Git:** `fd4c5c0` — "v3.4.1: sick day system, fix PlatformLogger f-strings, fix EB rules, fix character-sheet KMS policy"  
**Status:** ✅ Complete. All tasks done. No pending items.

---

## What Was Built

### Sick Day System
Full platform-wide sick day flag that suppresses scoring noise when Matthew is ill.

**Storage:** `pk=USER#matthew#SOURCE#sick_days`, `sk=DATE#YYYY-MM-DD`  
```json
{ "sick_day": true, "reason": "sick - flu/illness", "logged_at": "...", "logged_by": "mcp" }
```

**Behavior per component:**
| Component | Sick Day Behavior |
|---|---|
| Character Sheet | EMA frozen — copies prev record, adds `sick_day=True`, `frozen_from=<prev_date>` |
| Daily Metrics | `day_grade_letter="sick"`, streaks preserved from prev day, pillar scores carried forward |
| Anomaly Detector | Suppresses alert email — logs `severity="sick_suppressed"` |
| Freshness Checker | Suppresses SNS alert |
| Daily Brief | Lightweight recovery HTML (sleep/HRV/recovery only) — no AI calls |
| Buddy Page | `sick_day=True` propagated to buddy JSON |

**MCP tools added (147 total):**
- `log_sick_day(date, reason)` — writes sick day flag
- `get_sick_days(start_date, end_date)` — lists sick days in range
- `clear_sick_day(date)` — removes flag

**Retroactive flags applied:** Mar 8 + Mar 9 2026 (flu/illness)  
**Recompute confirmed:** Both days show `day_grade_letter="sick"`, character sheet frozen correctly

---

## Bugs Fixed

### 1. PlatformLogger f-string fixes
`PlatformLogger` does not support `%s` printf-style args — `logger.info("msg %s", var)` silently fails.
- Fixed 17 instances in `lambdas/character_sheet_lambda.py`
- Fixed 18 instances in `lambdas/daily_metrics_compute_lambda.py`
- Helper scripts left in `deploy/`: `fix_logger_calls.py`, `fix_dm_logger_final.py`, `fix_habit_scores_logger.py`

### 2. EB rules missing (UPDATE_ROLLBACK_COMPLETE)
Both Compute and Email stacks were in `UPDATE_ROLLBACK_COMPLETE` because v3.4.0 cleanup deleted console-created EB rules that CDK referenced by clean physical name.

Fix: Recreated all 16 rules via AWS CLI, then ran CDK deploy — both stacks updated clean.

**Architecture lesson:** Never use `rule_name=` with clean names in CDK — let CDK generate stack-prefixed physical names so cleanup scripts can't accidentally nuke them.

### 3. character-sheet-compute KMS AccessDeniedException
Root cause: `compute_character_sheet()` in `cdk/stacks/role_policies.py` missing `needs_kms=True`.
- CDK fix applied to `role_policies.py`
- Runtime fix applied via `aws iam put-role-policy`

**Follow-up needed:** Audit `needs_kms=True` for other Compute Lambdas writing to DDB (anomaly_detector, adaptive_mode, hypothesis_engine, dashboard_refresh) — these may have the same gap.

### 4. daily_metrics_compute_lambda.py corrupted
File was overwritten with placeholder content mid-session. Restored: `git checkout HEAD -- lambdas/daily_metrics_compute_lambda.py`, sick day patch re-applied.

### 5. Lambda Layer stuck on v2
All 7 Compute Lambdas updated to `life-platform-shared-utils:6` via AWS CLI.

---

## Files Modified
| File | Change |
|---|---|
| `lambdas/character_sheet_lambda.py` | Sick day freeze logic + 17 logger fixes |
| `lambdas/daily_metrics_compute_lambda.py` | Sick day handling + 18 logger fixes |
| `lambdas/daily_brief_lambda.py` | Recovery mode HTML for sick days |
| `lambdas/anomaly_detector_lambda.py` | Suppresses alerts on sick days |
| `lambdas/freshness_checker_lambda.py` | Suppresses SNS on sick days |
| `mcp/tools_sick_days.py` | New — 3 MCP tools |
| `mcp_server.py` | Import + registration of sick day tools |
| `cdk/stacks/role_policies.py` | `needs_kms=True` for character_sheet |
| `deploy/fix_*.py` | Logger fixer helper scripts |
| `docs/CHANGELOG.md` | v3.4.1 entry |

---

## Platform State
| Dimension | Value |
|---|---|
| Version | v3.4.1 |
| MCP Tools | 147 |
| Lambdas | 41 |
| CDK Stacks | 8 |
| Lambda Layer | life-platform-shared-utils:6 |
| KMS Key | arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d |

---

## Next Sessions

### 1. Brittany Weekly Email (next major feature)
Lambda slot exists (`brittany-weekly-email`), source file exists. No blockers.
- Styled accountability email for Brittany (vs Tom's read-only buddy page)
- Weekly cadence, Sonnet, personal tone

### 2. KMS audit (quick)
Check `needs_kms=True` for: `anomaly_detector_lambda`, `adaptive_mode_lambda`, `hypothesis_engine_lambda`, `dashboard_refresh_lambda` in `role_policies.py`.

### 3. Architecture Review #4 (~2026-04-08)
Next review after 30 days of production data.

### 4. SIMP-1 (~2026-04-08)
MCP tool usage audit — needs 30 days of CloudWatch EMF data before running.

### 5. Horizon features
- Google Calendar integration (demand-side context, North Star gap #2)
- Monarch Money (financial stress pillar)
- Light exposure tracking via Habitify

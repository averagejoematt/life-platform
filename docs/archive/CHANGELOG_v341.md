## v3.4.1 — 2026-03-09: Sick Day System

### New feature: sick day flagging with full platform suppression
- **New file**: `lambdas/sick_day_checker.py` — shared Layer utility (`check_sick_day`, `get_sick_days_range`, `write_sick_day`, `delete_sick_day`)
- **New file**: `mcp/tools_sick_days.py` — 3 MCP tools: `log_sick_day`, `get_sick_days`, `clear_sick_day`
- **New DDB partition**: `SOURCE#sick_days` — `pk=USER#matthew#SOURCE#sick_days`, `sk=DATE#YYYY-MM-DD`
- `sick_day_checker.py` added to Lambda Layer (`build_layer.sh` MODULES array)

### Lambda changes (5 files)
- `character_sheet_lambda.py` v1.0.0 → v1.1.0: freeze EMA on sick day (copy previous state, `sick_day=True`), no gain/penalty
- `daily_metrics_compute_lambda.py` v1.0.0 → v1.1.0: store `day_grade_letter="sick"`, preserve streaks from prior day
- `anomaly_detector_lambda.py` v2.1.0 → v2.2.0: sick day suppression (same pattern as travel); `sick_suppressed` severity
- `freshness_checker_lambda.py`: suppresses stale-source SNS alerts when yesterday was a sick day
- `daily_brief_lambda.py`: sends minimal recovery brief (sleep/recovery/HRV only) instead of full brief

### Retroactive records
- `2026-03-08` and `2026-03-09` flagged in DDB (reason: "sick - flu/illness")
- character-sheet-compute + daily-metrics-compute re-invoked with `force=true` to correct both dates


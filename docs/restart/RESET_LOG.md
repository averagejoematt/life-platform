# RESET_LOG — the durable record of experiment resets (ADR-058/077)

One line per reset, appended by `deploy/restart_pipeline.py --close-cycle` (the
default). The SSM parameter `/life-platform/experiment-cycle` holds only the
CURRENT cycle number; `CYCLE_GENESES` in `lambdas/web/site_api_data.py` drives
/api/cycle_compare + /api/timeline — this file is the human-readable ledger
that ties them together (genesis, cycle, baseline, pipeline report).

| cycle | genesis | baseline (lbs) | report |
|-------|---------|----------------|--------|
| 1 | 2026-04-01 | 307.0 | original launch (Day 1) |
| 2 | 2026-06-01 | — | first reset (ADR-077 tooling) |
| 3 | 2026-06-08 | 311.62 | docs/restart/_pipeline_report.txt (overwritten per run) |
| 4 | 2026-06-14 | 306.87 | Sunday-anchored routine reset |
| 5 | 2026-07-12 | 300.8 | docs/restart/_pipeline_report.txt @ 2026-07-11 |
| 6 | 2026-07-13 | 314.0 | docs/restart/_pipeline_report.txt @ 2026-07-13 |
| 7 | 2026-07-18 | 315.65 | docs/restart/_pipeline_report.txt @ 2026-07-18 |
| 8 | 2026-07-19 | 315.65 | docs/restart/_pipeline_report.txt @ 2026-07-18 |
| 9 | 2026-07-20 | 321.38 | docs/restart/_pipeline_report.txt @ 2026-07-20 |
| 10 | 2026-07-22 | 321.38 | docs/restart/_pipeline_report.txt @ 2026-07-21 |

# backfill/

One-shot data-ingestion or recomputation scripts. Each is a snapshot of how a specific historical data import was performed — they ran once, achieved their goal, and are kept for reference and potential re-run.

## Contents (~8 scripts)

Each file is dated or version-tagged in its filename. Examples:

- `backfill_apple_health_export_v16.py` — Apple Health XML import variant v16
- `backfill_macrofactor.py` — initial MacroFactor data import
- `backfill_macrofactor_workouts.py` — MacroFactor workouts addendum
- `draw_2026_04_03.py` — 2026-04-03 manual draw run
- `ingest_function_health_2026_04_03.py` — Function Health labs ingestion
- `survey_apple_health_gap.py` — diagnostic for an Apple Health gap

## Policy

- New backfills go in `backfill/` with date or version tag in filename
- Never delete after run — re-running may be needed if a similar gap recurs
- Production daily ingestion lives in `lambdas/*_lambda.py` — these scripts are NOT scheduled or deployed
- Safe to run locally with credentials; some require env vars (AWS_REGION, S3_BUCKET, USER_ID)

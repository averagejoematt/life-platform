# patches/

One-shot data-correction or feature-application scripts. 51 files, vast majority prefixed `patch_*`. Each represents a corrective action taken against production DynamoDB/S3 state at a specific point in time.

## Categories

- **patch_*** (41) — DDB or S3 surgical corrections (rename keys, fix values, retroactive feature data, etc.)
- **apply_*** (2) — feature deployment helpers (e.g. apply_v240_patch.py)
- **restore_*** (2) — recovery scripts run after partial-failure incidents
- **remove_*** (2) — selective record removal
- **fix_*** (1) — bug-specific data fix (e.g. fix_blog_index_links.py)
- Other (3) — `todoist_*`, `supplement_*`, `rebuild_*`

## Policy

- Each patch is a historical record of a fix — keep for audit trail
- Never re-run a patch without verifying its assumptions still hold (the targeted state may have moved on)
- Forward-fixes for new bugs go in a new `patch_<descriptor>_<YYYY_MM_DD>.py` file
- Production code (continuous transformations) belongs in `lambdas/`, not here
- Safe to delete if you accept losing the audit trail; nothing here is imported or scheduled

## Cleanup candidates (future)

If/when this dir exceeds ~100 files, consider archiving anything older than 6 months into `archive/patches/YYYYMM/` and clearing the root. Today's count (51) is manageable.

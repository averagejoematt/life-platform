# archive/

Frozen point-in-time snapshots of code/state from earlier platform versions, kept for historical reference. Nothing here runs in production.

## Contents

- `20260308/` — snapshot from 2026-03-08 (pre-CDK consolidation)
- `20260309/` — snapshot from 2026-03-09 (post first SIMP-2 weather migration)
- `legacy-scripts/` — pre-2026-02 one-shot scripts from the manual-ops era

## Policy

- New archives: create `archive/YYYYMMDD/` for snapshots of significant migrations
- Never modify existing dated archives — they are historical records
- Safe to delete entirely if disk pressure becomes an issue; current production state is in `lambdas/`, `mcp/`, `cdk/`, `site/`
- Not deployed, not imported, not in test paths — purely on-disk history

# HANDOVER — #478 Todoist real filters + pagination + decision-fatigue re-eval (ADR-122) — 2026-07-05

> Small focused session, concurrent with the two opus batches. Shipped one story
> end-to-end and surfaced a prod outage that opus batch #2 then resolved.
> `HANDOVER_LATEST.md` is owned by opus batch #2's close — this is an additive record.

## Shipped — #478 (PR #696 → `main`, ADR-122). Fully deployed + live-verified.

**Root cause.** The v1-API migration kept passing `filter` to `GET /tasks`, which the
v1 API **silently ignores** (returns the whole active list), and `get_active_tasks`
read one 200-item page with no cursor follow. Stored records proved it:
`overdue == due_today == 270` (identical full list) with `active == 200` (page cap).
The endpoint that filters is `GET /api/v1/tasks/filter?query=<filter>` — verified live
that the required param is **`query`**, not `filter`.

**Changes.**
- `todoist_lambda.py` — `get_filtered_tasks` → `/tasks/filter?query=`; shared
  `_paginate_tasks` follows `next_cursor`; `get_active_tasks` paginates past 200.
- `mcp/tools_todoist.py` — `_list_all_tasks` routes filters to `/tasks/filter?query=`.
- `daily_insight_compute_lambda.py` — decision-fatigue (BS-MP3) load is now
  `overdue + due_today` (decision-pressure set), NOT `active + overdue` (double-counted
  + backlog-dominated → `>15` fired daily even after the endpoint fix; `active+overdue
  = 454` on clean data). "15" relabelled **provisional**; ADR-122 documents the ADR-105
  personal-variance migration (MIN_N=30) once clean days accrue.
- `scripts/flag_todoist_unreliable_snapshots.py` — AC-3: **56 records (2026-05-10→07-05)
  flagged `snapshot_unreliable=true`** (applied). Next clean run 2026-07-06 14:00 UTC.
- `tests/test_todoist_filters.py` — 7 tests.

**Deployed + verified (Matthew authorized all deploys):** todoist-data-ingestion (boots
clean), life-platform-mcp (imports clean, 401 auth gate), daily-insight-compute (my
`pressing_load` change confirmed in the LIVE zip, boots 200). Live counts post-fix:
active 270, overdue 184, due-today 0.

## Two deploy gotchas hit (both codified)
1. **MCP manual zip was incomplete** — `.claude/commands/deploy.md`'s recipe omitted
   `lambdas/reading/`, so the lambda booted `No module named 'reading'` (the exact crash
   opus batch #1 had fixed via CDK). Rebuilt the complete bundle (`mcp_server.py` +
   `mcp/` + `reading/`) and **fixed the recipe** (this handover's PR). Memory:
   `reference_mcp_bundle_needs_reading`. A raw `update-function-code` has no rollback.
2. **Worktree path discipline** — early edits via main-tree absolute paths briefly landed
   in the shared checkout; restored main to HEAD, re-applied in the worktree.

## Surfaced + RESOLVED same day — the personal_baselines outage (#697, closed)
The #543 deploy added `import personal_baselines` to 3 compute lambdas but never added it
to `deploy/build_layer.sh`, so layer v113 lacked it → daily-insight / daily-metrics /
personal-baselines compute all failed every run (confirmed erroring 18:30 UTC, before any
#478 deploy). Matthew chose option 3 (hand off). **The concurrent opus batch #2 v114
Compute deploy resolved it by bundling `personal_baselines.py` into each compute function
package** (verified in the live daily-insight zip; all three boot 200). Caveat recorded in
#697 + memory: it's fixed by function-bundling, NOT the layer — `build_layer.sh` still
omits it, so a future single-file deploy of those three can recur the crash.

## State at close
`main` includes #478 (#696) + both opus batches. #478 + #697 closed. Not deployed:
site-api PLATFORM_STATS metadata bump (cosmetic; concurrent site-api work in the tree).
Deploy worktree `life-platform-worktrees/deploy-478` can be removed. Memory updated:
`project_data_source_health_review`, `project_personal_baselines_layer_outage`,
`reference_mcp_bundle_needs_reading`.

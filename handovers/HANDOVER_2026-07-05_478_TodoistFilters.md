# HANDOVER — #478 Todoist real filters + pagination + decision-fatigue re-eval (ADR-122) — 2026-07-05

> Small focused session after the opus batch (archived at
> `handovers/HANDOVER_2026-07-05_OpusBatch.md`). Shipped one story end-to-end and
> **discovered a pre-existing prod outage** that is handed to a separate session (#697).

Matthew: "Ship GitHub issue #478." Then, after the PR: **"can you do all merges and
deploys, i authorize."** Then, on the discovered outage: **"do 3" (hand it to a
separate session), update memory/handover/docs, wrap up.**

---

## Shipped — #478 (PR #696, squash-merged to main `f79e7ec4`, ADR-122)

**Root cause.** The v1-API migration kept passing `filter` to `GET /tasks`, which the
v1 API **silently ignores** (returns the whole active list), and `get_active_tasks`
read a single 200-item page with no cursor follow. Stored DDB records proved both:
`overdue == due_today == 270` (identical full list) with `active == 200` (page cap).
The endpoint that filters is `GET /api/v1/tasks/filter?query=<filter>` — verified live
that the required param is **`query`**, not `filter` (400 `ARGUMENT_MISSING: query`).

**Changes.**
- `lambdas/ingestion/todoist_lambda.py` — `get_filtered_tasks` → `/tasks/filter?query=`;
  shared `_paginate_tasks` helper follows `next_cursor`; `get_active_tasks` paginates.
- `mcp/tools_todoist.py` — `_list_all_tasks` routes a filter to `/tasks/filter?query=`,
  keeps `/tasks` for the unfiltered snapshot.
- `lambdas/compute/daily_insight_compute_lambda.py` — decision-fatigue (BS-MP3) load is
  now `overdue + due_today` (decision-pressure set), NOT `active + overdue` (which
  double-counted — overdue ⊂ active — and was backlog-dominated, so `>15` fired every
  day even after the endpoint fix; measured `active+overdue = 454` on clean data). The
  "15" relabelled **provisional**; the old "empirical" basis was measured on poisoned
  data. ADR-122 documents the ADR-105 personal-variance migration once ~30 clean days
  accrue (floor-guarded at MIN_N=30, same pattern as #543).
- `scripts/flag_todoist_unreliable_snapshots.py` — AC-3: flags the poisoned range
  `snapshot_unreliable=true` (annotate, don't fake). **Applied: 56 records
  (2026-05-10 → 07-05).** Todoist's next clean run is 2026-07-06 14:00 UTC.
- `tests/test_todoist_filters.py` — 7 tests lock all four behaviours.

**Live counts post-fix:** active 270 (paginated), overdue 184 (real), due-today 0.

## Deployed + verified (I did the deploys — authorized)
- **todoist-data-ingestion** ✅ `deploy_and_verify.sh`, boots clean.
- **life-platform-mcp** ✅ imports clean, `list_todoist_tasks` reaches the 401 auth gate.
- **AC-3 annotation** ✅ 56 records flagged (verified).
- **NOT deployed:** site-api PLATFORM_STATS metadata bump (adrs 99→100, test_count) —
  concurrent site-api work was in the main tree; deploying the full `web/` package would
  risk clobbering it. Cosmetic; syncs on the next site-api deploy from main.

## Deploy gotchas hit this session (both now codified)
1. **MCP manual zip was incomplete.** The `.claude/commands/deploy.md` recipe zipped only
   `mcp_server.py mcp_bridge.py` + `mcp/`, omitting `lambdas/reading/` → the lambda booted
   `No module named 'reading'` (the exact crash the opus batch had fixed hours earlier).
   Rebuilt the complete bundle (`mcp_server.py` + `mcp/` + `reading/`, mirroring the CDK
   `_mcp_staging`) and restored it. **Fixed the recipe in `.claude/commands/deploy.md`**
   (this PR) + memory `reference_mcp_bundle_needs_reading`. A raw `update-function-code`
   saves no rollback artifact — always verify boot.
2. **Worktree path discipline.** Early on I edited via main-tree absolute paths while the
   session was in the issue-478 worktree, so edits briefly landed in the shared checkout
   (a concurrent session was writing there too). Caught it, restored the 3 files in main
   to HEAD, re-applied cleanly in the worktree. (Covered by memory
   `reference_worktree_case_insensitive_pollution`.)

## ⚠️ HANDED OFF — pre-existing prod outage (#697), NOT #478

The #543/opus-batch deploy added `import personal_baselines` to three compute lambdas but
**never added `personal_baselines.py` to `deploy/build_layer.sh`**, so shared layer **v113
lacks it**. Failing every run since ~2026-07-05 morning (confirmed erroring 18:30 UTC,
pre-dating any #478 deploy):
- **daily-insight-compute** (also #478's target — its #478 code IS deployed but blocked)
- **daily-metrics-compute**
- **personal-baselines-compute** (producer)

`stats_core.py` / `phase_filter.py` — imported the same way — ARE in the layer, which is why
it slipped. **Fix = canonical layer republish** (add to build_layer.sh → rebuild → publish
v114 → bump `SHARED_LAYER_VERSION` → redeploy Compute consumers → verify boot). Deliberately
left for a separate session (Matthew chose option 3). Confirm no concurrent layer-republish
before bumping the constant. Memory: `project_personal_baselines_layer_outage`.

## State at close
`main` = `f79e7ec4` (#478 merged). This docs/wrap PR adds the deploy.md fix + handovers +
CLAUDE.md status. #478 closed by the merge. **Open follow-ups: #697 (layer outage,
blocking daily-insight/daily-metrics), site-api metadata bump (cosmetic).** Deploy worktree
at `life-platform-worktrees/deploy-478` can be removed.

# HANDOVER_LATEST — #478 Todoist filters shipped; layer outage #697 handed off — 2026-07-05

> Live driver. Full detail: `handovers/HANDOVER_2026-07-05_478_TodoistFilters.md`.
> The prior opus-batch close state is preserved at
> `handovers/HANDOVER_2026-07-05_OpusBatch.md` (11 issues, layer v113 — all still live).

## This session (small, focused)
**#478 Todoist real filters + pagination + decision-fatigue re-eval** shipped end-to-end
(PR #696 → `main` `f79e7ec4`, ADR-122). Overdue/due-today now hit
`GET /api/v1/tasks/filter?query=<filter>` (the v1 `/tasks` endpoint silently ignores a
`filter` param), active fetch paginates past 200, and BS-MP3 decision-fatigue measures
`overdue+due_today` (not `active+overdue`). 56 poisoned records flagged
`snapshot_unreliable=true` (AC-3). **Deployed + verified:** todoist-data-ingestion,
life-platform-mcp. site-api metadata bump left for next site-api deploy (cosmetic).

## 🔴 TOP PRIORITY for the next session — #697 (pre-existing prod outage)
`personal_baselines.py` is missing from shared layer **v113** (omitted from
`deploy/build_layer.sh` by the #543 deploy). **daily-insight-compute, daily-metrics-compute,
and personal-baselines-compute fail every run** since 2026-07-05 morning
(`No module named 'personal_baselines'`). #478's daily-insight code is deployed but blocked
by this. **Fix = layer republish:** add to `build_layer.sh` → rebuild → publish v114 → bump
`SHARED_LAYER_VERSION` (`cdk/stacks/constants.py`) → redeploy Compute consumers → verify each
BOOTS. Confirm no concurrent layer-republish first. See `project_personal_baselines_layer_outage`.

## Other open threads (from the opus-batch close, unchanged)
- site-ux epic tail #588/#590/#591/#593/#595 (unblocked by #581 split + #582 chart contract;
  #593 portraits-travel needs ADR-106 sign-off).
- Held opus queues: #395 MCP prune (attended); infra #416/#418/#401/#408/#411;
  growth #420/#405/#399; ingestion-adjacent = coordinate w/ HAE.
- GitHub Pages still enabled+public (carried, unactioned).

## Housekeeping
- Deploy worktree `life-platform-worktrees/deploy-478` can be removed.
- Deploy reflex learned: the MCP manual bundle MUST include `lambdas/reading/` (fixed in
  `.claude/commands/deploy.md`; memory `reference_mcp_bundle_needs_reading`).

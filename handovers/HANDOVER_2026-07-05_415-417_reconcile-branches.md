# HANDOVER — #415 Whoop reconciliation + #417 routine branch model — 2026-07-05

> Two epic-#348 ("Deepen the N=1 instrument") *Later* stories, shipped start→finish in
> one session. Matthew authorized edit/merge/deploy in-session. Built by **two
> worktree-isolated background agents in parallel** — the correct call, because a
> concurrent **#412 `feat/412-training-truth`** session shared the primary tree. The
> isolation is exactly what prevented a repeat of the #590/#408 squash-stomp.

## What shipped

### #415 — Whoop source-of-truth reconciliation (PR #710, TR-07) — NO layer bump
Generalized the shipped Strava DI-2 provider-diff pattern to Whoop.
- `whoop_lambda._reconcile` — invoked `{"reconcile": true}`; new EventBridge rule
  `WhoopReconciliation` `cron(20 18 * * ? *)` (18:20 UTC fixed). Pulls trailing-14d
  sleeps+workouts from the Whoop v2 API (paginates past the 25-record page via
  `next_token`), diffs vs the store. **Read-only** (reports, never heals),
  **dedup-aware** (±120s workout-twin tolerance + day-collapse), **fails open**
  (any error → 200 no-op, skips the metric).
- Emits `LifePlatform/IngestReconciliation::MissingActivityCount{Source=whoop}` —
  same metric as Strava, distinguished by dimension. Alarmed by
  `ingest-reconciliation-whoop` (digest, GTE 1) + `-heartbeat` (absence, 2d).
- Opt-in via new `provider_reconcile` facet in `source_registry.py`
  (`provider_reconcile_source_ids()`). No new IAM (reuses the ingestion role's
  DDB-Query + PutMetricData + secret grants).
- **ADR-123: Garmin deliberately NOT reconciled** — paused (ADR-074, datacenter-IP
  429 block) + rate-capped 4x/day + best_effort; a reconciler would burn the
  request budget and false-alarm on the accepted-degraded state.
- **Deployed:** `LifePlatformIngestion` + `LifePlatformMonitoring`.
- **The reconciler caught a real gap on its FIRST live run** — `sleeps 14, workouts
  12, missing 1`: a Whoop workout (`7a62677b-20d1-4efa-a20f-caea2588abe3`,
  2026-07-05) the API held but the store missed. That's precisely the silent-drop
  class the story targets. Read-only, so the next ingestion trailing-refresh should
  heal it — worth a glance if it persists.

### #417 — first-class routine branches + overnight re-stamp (PR #711, TR-04/05) — LAYER v114→115
- `routine_ir.RoutineBranch` dataclass + `RoutineSpec.branches`; Decimal-safe
  deserialize reconstructs nested branch exercises.
- `hevy_compiler.render_branches_note()` / `_compose_notes()` — render the branch
  menu into the pushed routine's notes (Hevy holds ONE exercise list, so the menu
  lives in notes; the recommended branch is starred). Returns `""` for a branchless
  routine → **byte-identical push** (backward compat).
- `routine_generator.emit_branch_model()` — folds the generated ideal/floor/re-entry
  variants into ONE branch-carrying primary (`ideal` = recommended); never drops a
  variant (self-selection preserved).
- `hevy_routine_cron_lambda` now pushes that single primary instead of "push ideal,
  drop floor"; siblings still persisted for the record.
- New `hevy-restamp` lambda (`lambdas/operational/`) — re-orders + re-flags
  `recommended` by recovery band. **Never adds/removes a branch** (asserts
  `len(reordered) == original_count`), **fails open**, **SHIPS DISABLED** at both the
  rule (`enabled=False`, `cron(45 12 * * ? *)`) and SSM
  `/life-platform/hevy/restamp_enabled` (=`false`). Least-privilege `rp.hevy_restamp()`.
  `ci/lambda_map.json` registers it `cdk_only`.
- **Layer sequence (done):** `build_layer.sh` → `cdk deploy LifePlatformCore`
  (published **v115**, verified live) → `LifePlatformOperational` +
  `LifePlatformMcp`. Only those two stacks deserialize routines — the rest of the
  fleet stays safely on v114 (an old-layer `deserialize()` would crash on a
  `branches` field, so this scoping is load-bearing, not cosmetic).
- **Verified live:** hevy-restamp + hevy-routine-cron on layer 115; restamp rule
  DISABLED; SSM kill-switch `false`; MCP boots 401 (healthy); restamp smoke =
  `{"status":"noop","reason":"restamp_enabled=false"}`.

## Gotchas worth carrying

- **Layer wiring is via the ARN string, not the Core object.** Every consumer stack
  attaches the layer through `SHARED_LAYER_ARN` (`from_layer_version_arn`), built from
  `SHARED_LAYER_VERSION` in `constants.py`. So Core auto-publishing a new version on
  content change is NOT enough — you MUST bump `SHARED_LAYER_VERSION` (114→115) or
  consumers keep pointing at the old version. The agent didn't bump it; I did.
- **The branched-routine backward-compat trap.** New `deserialize()` handles a
  `branches` field; the OLD one crashes (`TypeError: unexpected keyword 'branches'`).
  So every lambda that deserializes a routine must be on v115 BEFORE the cron writes
  its first branched routine. Reader set mapped to exactly operational + mcp
  (`adherence_calc` only uses `RoutineSpec` as a type; nothing in web/compute/emails
  deserializes routines) — that's why the scoped 2-stack redeploy is correct.
- **Doc-metadata conflicts on rebase.** Both stories touched the `sync_doc_metadata.py`
  auto-synced files (ARCHITECTURE.md, site_api_common.py counts, etc.). Resolved #415
  by taking one side + re-running the sync; resolved #417's rebase the same way, then
  re-ran `--apply` to land the true counts (adrs→109, lambdas→94, test_count→2353).

## State at close

- `main` == origin (`543beef6`); both issues CLOSED; layer **v115** live.
- Worktrees: the two agent worktrees removed; remaining are the concurrent **#412**
  session's worktree (`life-platform-worktrees/412`, not mine) + `uplevel-handover`.
- Build-log beat published (#380) via its own PR + site sync.
- **⚠️ Concurrent #412 session shares this tree.** The CLAUDE.md status block is
  single-writer "replace-don't-stack" — #412's close may replace it.
- GitHub Pages still enabled+public (carried, unactioned).

## Next / awaiting Matthew

1. **Enable the re-stamp (2 decisions first, it's disabled so no rush):**
   - **Timing:** rule is 12:45 UTC but Whoop recovery only refreshes 17:30 UTC — as
     scheduled it re-stamps on stale recovery. Move the recovery pull earlier OR the
     re-stamp later, then flip SSM `restamp_enabled=true` + enable the rule.
   - **Branch push format:** currently base exercises + menu-in-notes; alternative is
     to push the recommended branch's OWN `exercises` as the set/rep list (one-line
     compiler change — but only one branch's content can reach Hevy).
   - Note: no "harder" branch is generated today (add-load gated off), so a
     green-recovery morning resolves to "as-written".
2. Watch `ingest-reconciliation-whoop` — if the missing-workout finding persists past
   the next ingestion cycle, the trailing-refresh isn't healing it and it's a real
   drop to investigate.
3. Unrelated carry-overs: #409 batch-price content AI (layer, attended), #395 MCP
   prune (attended), #687 OIDC.

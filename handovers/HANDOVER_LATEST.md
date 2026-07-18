# HANDOVER — Now-milestone remediation slice: 8 /fullreview issues shipped via worktree fan-out — 2026-07-18

> Instruction thread: continuing from the /fullreview baseline (prior session seeded 68
> issues #1194–#1261). Matthew: "you do all the merges please, i approve" → later "yes do
> all this then wrap and give me good to clear." Drove the entire implementable `Now`
> milestone to merged-on-main via isolated worktree agents, then this wrap. Deploys +
> two live-DDB backfills remain Matthew's (flagged below).

## What shipped — 8 PRs MERGED to main (the entire implementable Now milestone)

All via `worktree-implementer` agents in **isolated worktrees** (no shared-tree collision,
the lesson from 2026-07-17). Each: issue's Path-to-A + a **non-vacuous** regression guard,
black/ruff clean, full offline suite green, `Fixes #N`, verified by me against the diff.

| PR | Issue | Fix | Deploy (Matthew) |
|----|-------|-----|------------------|
| #1262 | #1197 | `singleton_visible` guard on 3 unguarded `site_api_data.py` latest-`DATE#` readers (state_of_matthew was leaking the tombstoned cycle-5 brief live on /coaching/) | `deploy_site_api.sh` |
| #1263 | #1196 | `cloudwatch:PutMetricData` grant on `compute_coach_prediction_evaluator` + **4th instance** `site_api_ai` (caught by the new AST lockstep gate) + restart marker seed | `cdk deploy LifePlatformCompute` **+ LifePlatformServe** |
| #1264 | #1201 | remediation agent reds the run on truncated triage (was silent "success") | none (workflow runs from main) |
| #1265 | #1200 | `singleton_visible` on Elena's persistent-memory reads (cycle-5 threads leaked into cycle-6 drafts) | email-λ fleet / `deploy_lambda.sh` |
| #1266 | #1202 | phase tagger uses `if_not_exists` so prior archives keep their `cycle=N` stamp | none (reset script) |
| #1267 | #1203 | freshness reads pass `include_pilot=True` (DDB Limit-before-Filter blinded dark pre-genesis sources) | `deploy_site_api.sh` |
| #1268 | #1198 | predict-the-week fails closed on a stale `week_id` + reset lifecycle clear + nightly qa guard | `deploy_site_api.sh` + qa_smoke via fleet |
| #1269 | #1199 | `void_open_bets_at_reset()` writes cross-phase `CALIB#` void rows for open bets at reset | none (reset script) |

**Verification:** every PR's regression guard proven non-vacuous (fails without the fix);
suites 16/612/19/244/24 (slice 1) + 25/63/251 (slice 2) passed; I verified each diff
before merge (the ~50%-false-positive reflex — these also passed the /fullreview verifier).
All 8 issues auto-CLOSED via `Fixes #N`.

## Merge mechanics / gotchas
- **Merge order for conflict-avoidance:** slice 1 (#1196/#1197/#1200/#1201/#1202) had disjoint
  files → merged together. Slice 2: #1203/#1198 disjoint → merged; **#1199 HELD** until #1198
  merged (both touch `restart_pipeline.py`) then released off updated main — every merge stayed
  CLEAN, zero conflicts. #1196/#1198/#1199 each added a localized reset step (2c/2d/2e) that
  composes with the others.
- **`test_count` drift** reconciled after each merge batch — the repo's auto-reconcile bot
  (`chore(reconcile) … [skip-reconcile]`) regenerates the literals within ~1 min; I aligned
  local main to it (`reset --hard origin/main`) rather than double-committing.
- **The ci-cd "Plan deployments" red is EXPECTED, not a break:** it's the **R8-ST6 IAM-review
  gate** (`gh api …/annotations` → "CDK diff detected IAM/policy changes — review and approve
  manually before deploying"), firing because #1263 added an IAM grant. Lint + all tests PASS.
  It clears when Matthew runs the CDK deploy. NOT a resource-destruction match (verified via
  the emitted annotation, not the script echo).
- Worktrees left by the agents were removed (`git worktree remove --force` + `prune` + branch -D);
  only the main worktree remains.

**Build beat:** none — all 8 PRs are merged to main but the user-facing fixes (site-api
tombstone/freshness guards, IAM grant, Elena email λs) are NOT yet deployed; the beat gate
requires merged-AND-live. Beat becomes eligible once Matthew deploys (see checklist below).
**Docs:** none needed — the 8 fixes touch code + tests only (no ADR, schema, deploy-path,
MCP-tool, or engine-doc change); `sync_doc_metadata` literals auto-reconciled + all six doc
gates green at the wrap commit. `docs/reviews/FULLREVIEW_2026-07-16.md` (prior session) is the
source-of-truth scorecard; no wiki page invalidated.

## Residual queue / next picks
- **Matthew's deploys (the ONLY thing between merged + live):**
  1. `bash deploy/deploy_site_api.sh` — lands #1262 (tombstone guard) + #1267 (freshness) + #1268 (predict-week fail-closed). Verify: `curl /api/state_of_matthew` → `available:false`; `/api/source_freshness` shows MacroFactor's real `days_dark`.
  2. `cd cdk && npx cdk deploy LifePlatformCompute LifePlatformServe` — lands #1263's two IAM grants; clears the R8-ST6 gate + the 10-day `grading-stalled` alarm.
  3. email-λ fleet (`deploy_fleet.sh` or `cdk deploy --all`) — lands #1265 (Elena) + #1268's qa_smoke guard.
- **Two live-DDB backfills (Matthew — the code stops future recurrence, doesn't heal history):**
  - #1266: re-derive true `cycle=N` on already-corrupted archive rows (e.g. `INSIGHT#2026-02-23`).
  - #1265: regenerate the held `DATE#2026-07-14` Elena draft (phantom "Sunday walks" baked in).
- **Backlog:** `Now` milestone now = only #1029 (owner-gated re-entry checklist) + #741 (external
  publish — Matthew's action). Next slice from `gh issue list --label type:story --milestone Next`.
- **Minor maintainability note (#1199):** `VOID_COACH_IDS` is hardcoded to mirror
  `coach_prediction_evaluator.COACH_IDS`; a future 9th coach must be added to both.

Prior session: `handovers/HANDOVER_2026-07-17_FullreviewBaselineHonestGate.md`.

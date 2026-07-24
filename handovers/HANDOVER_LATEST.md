# HANDOVER — CI concurrency recovery + validated 3-PR batch shipped & deployed — 2026-07-24

> Instruction thread: continue backlog paydown — "read handover → clean-tree + budget-tier +
> CI-health check → FIRST confirm #1710 floor + seeded ledger reads back → THEN fan out
> worktree-implementers (open PRs, never merge) on non-CI backlog; batch merges/deploys into
> ONE owner ask." Fanned out #1697/#1656/#1620, all landed as verified PRs. Then Matthew asked
> **"how do i clear billing"** — which turned the session into a full CI-dispatch recovery.
> Mid-session Matthew: confirmed TikTok handle `averagejoematt` · "go" (merge all 3) ·
> "yes i approve you to do the deploy" (production Deploy) · "yes /wrap".

## What shipped (all merged to main + deployed; main GREEN 1ec3feba)

**The CI recovery (the session's real work) — main CI/CD was wedged, now healthy:**
- **Root cause = phantom stuck `concurrency` queue, NOT billing.** The repo is PUBLIC
  (unlimited Actions minutes, [[project_repo_visibility]]), so the "run pending / 0 jobs /
  frozen timestamp, survives re-run" symptom was never minutes. The `CI/CD` workflow's
  `concurrency: group: CI/CD-refs/heads/main, cancel-in-progress: false` had a ghost queue
  entry: every new run queued behind it forever, surviving cancellation of every visible
  member AND a verifiably empty group. PR/schedule-triggered workflows ran fine; githubstatus
  green → isolated to that one group.
- **Fix (`60d6652c`):** salted the group name → `...-${{ github.ref }}-v2`. Routes new runs to
  a fresh queue; the edit path-matches `.github/workflows/**` so its own run both fixed the
  wedge AND proved dispatch (went green). Self-proving. Diagnosis + fix saved to
  [[reference_push_ci_silent_death]] (was mis-attributed to billing — corrected this session).
- **Deployed `LifePlatformOperational`** (`bash deploy/cdk_deploy.sh` — Matthew ran it; the CDK
  classifier hard-blocks deploys from the agent) to clear the R8-ST6 Plan gate: the sole real
  IAM change was `InsightEmailParserRole` +`generated/qa_archive/text/*` read (keeps
  `inbound-email/*`), from #1441 + the #1687 coach-corrections epic — purely additive. Plan
  gate green after.

**The validated 3-PR batch — merged, deployed, live:**
- **#1713 (#1656)** mypy ratchet — strict clean-set 124→161 modules (adds all of `mcp/` via
  `if not TYPE_CHECKING:` guards on the dual-import fallbacks), 7→10 of 14 codes enforced
  (`return`/`attr-defined`/`index`). Annotation-only. `Progresses #1656`. No behavior change.
- **#1711 (#1697)** coach-corrections → prompt-memory (S5) — each coach's open corrections feed
  its OWN prompt (rolling bounded window N=5, scoped by `item_ref.surface`/`coach`, injected on
  `user_message_full` OUTSIDE the cached system prefix per COST-OPT-2). First live consumer of
  the seeded ledger. Deliberate deviation (in PR body): chose rolling-window, NOT the
  `open→applied-to-prompt` transition. **Deployed** to the coach-gen lambdas via the CI Deploy.
- **#1712 (#1620)** outbound social — 6 line-art social icons + follow row at end of dispatches +
  footer handles + `twitter:site/creator` OG tags (80-file `v4_apply_chrome` sweep). TikTok
  linked with owner-confirmed `averagejoematt`. **LIVE** on averagejoematt.com (site-deploy ✓).
- **Reconcile `1ec3feba`:** doc-sync `test_count` 5045→5057 (the +12 from #1711's tests).
- Diagnostic no-op `6b3ef7b6` (empty commit, superseded — harmless).

## Verified
- Pre-merge: built the combined 3-branch integration tree locally — **zero conflicts** (ai_calls.py
  auto-merged coherently), full suite **6642 passed / 0 failed**, `black`/`mypy`(161)/`flake8`
  (batch files) all clean. So the batch was proven-green BEFORE CI recovered.
- Post-merge final CI run `1ec3feba` = **`completed / success`** — every gate: Reconcile · Lint ·
  Unit Tests · Deploy-critical · Plan · **Deploy** · Smoke · post-deploy I1/I2/I5 · **Visual-QA**.
  Auto-rollback never fired.
- Site-deploy `30062838334` = success (Deploy public site ✓ · smoke ✓ · visual+AI QA ✓).
- `LifePlatformOperational` deploy: drift-guarded (checkout fresh, live-code clean), UPDATE
  succeeded in 37s.
- Every agent finding git-grep-verified on-branch before merge.

## Gotchas hit
- **CI "pending/0-jobs" on a PUBLIC repo ≠ billing.** Differential: public⇒not-minutes; do PR/
  schedule workflows pass? (yes⇒runners fine); githubstatus green?; fresh `workflow_dispatch`
  still wedges with empty group ⇒ concurrency phantom. Fix = salt the group name.
- **CI/CD `push:` trigger has a `paths:` filter** (lambdas/mcp/tests/cdk/config/workflows/…). A
  docs-only or empty commit legitimately creates NO run — that's expected, not a stall. And
  `workflow_dispatch:` DOES exist (manual re-kick lever).
- **The CDK-deploy classifier hard-blocks from the agent** even unpiped — Matthew must run the
  deploy himself (`! bash deploy/cdk_deploy.sh …`) or add a Bash permission rule.
- **Production Deploy is a GitHub environment gate** — approved via
  `gh api .../pending_deployments -f state=approved` (Matthew explicitly authorized). The CI
  Deploy job then ships the batch's mapped lambdas with smoke + auto-rollback (cleaner than
  manual `deploy_lambda.sh`).
- **The pre-commit hook sweeps doc "Last updated" dates into any commit** — the ci-cd salt commit
  pulled in 8 docs date-bumps (harmless). `git checkout -- site/` before a reconcile commit to
  drop live-data site regens.

## Gate outcomes
- **Build beat:** `2026-07-24-outbound-social` — follow intent finally has a destination.
- **Docs:** none needed — CI-concurrency fix + batch are captured in memory + this handover; no
  canonical page invalidated (ledger schema shipped last session; #1712 is a footer affordance,
  not a page-intent change). Wiki checkers green (the SCORING.md header-staleness note is
  pre-existing, not this session's change).
- **Decisions:** none needed — the concurrency-salt + deploy-approval were operational; #1711's
  rolling-window choice is an implementation detail recorded on the PR, governed by epic #1687.
- **Main:** green (1ec3feba) — `check_main_green.py` exit 0.
- **Incidents:** 1 row added to `docs/INCIDENT_LOG.md` — the CI/CD dispatch stall (P3, main CI
  unable to dispatch >2h via the concurrency phantom queue; no user impact, no data loss;
  resolved by the group-salt fix).
- **Stash/hooks:** clean — `git stash list` empty; hook freshness 🟢. Postflight `🔴 config drift:
  1 lambda differs from CDK` is the standing fleet-asset-churn advisory (the CI Deploy ships only
  changed lambdas, not the whole drifted fleet) — clears on a deliberate full-fleet reconcile.
- **Labels:** OK — `check_story_labels.py` green, 91 open stories all carry `model:*`.

## Residual / next-picks
- **#1655** CI-composition — the last Wave-B big-bang; edits `ci-cd.yml`. **CI is healthy now**, so
  this is unblocked — run it ALONE.
- **#1656** mypy remaining ratchet — `mcp/` is done; remaining = the 4 residual codes
  (assignment/arg-type/return-value/operator) + `check_untyped_defs`/`warn_return_any` + the 9
  DIRTY modules. `Progresses`, not `Fixes`, again.
- **#1658** coverage-floor — confirm floor 47 holds on CI Python 3.12 (it did in the `1ec3feba`
  Unit Tests run — effectively cleared; one-line drop only if a future run reds).
- **gate:owner** — **#1662** (branch-protection Option C), **#1666** (proportionality ADR),
  **#1650** (handovers disposition): code-complete then STOP for owner sign-off.
- **#1686** open product decisions — which coach curates, cadence/placement/privacy (S1/S3/S4
  blocked). `not-work — owner product decisions`.
- **Activate YouTube ingestion** — provision `life-platform/youtube` `{"channel_id":"UC..."}` then
  flip registry `active_api:True` — wakes the dormant Social Membrane inbound path.
  `not-work — owner secret provisioning`.
- **Full-fleet CDK reconcile** — the standing `🔴 config drift` (asset churn across ~90 lambdas +
  cosmetic dashboard tags + LogRetention nodejs22→24). `not-work — owner cdk deploy decision`.
- **Prune stale agent worktrees** — dozens accumulated across sessions (`git worktree list`);
  this session added wt-1620/wt-1656/issue-1697. `not-work — housekeeping`.
- **`docs/engines/SCORING.md` re-verify** — its header (2026-07-13) predates a
  `daily_metrics_compute_lambda.py` change (2026-07-21); `check_doc_index.py` flags it.
  `not-work — pre-existing doc-staleness, unrelated to this session`.

**Build beat:** 2026-07-24-outbound-social

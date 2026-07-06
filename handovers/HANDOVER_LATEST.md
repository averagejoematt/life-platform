# HANDOVER — R21 Batch 1+2: 8 issues shipped, merged & deployed — 2026-07-06

> Instruction: "read memory and handover, put a plan to resolve efficiently as many
> issues as possible" → picked **Batch 1 (Now milestone) + Batch 2 (R21 perimeter
> quick-wins)** = 8 issues. Model decision: stayed on **Opus** as the driver +
> fanned the mechanical `model:sonnet` items to Sonnet worktree subagents. User then
> authorized "all merges and deploys, do everything, then memory + handover."
> **All 8 issues: code merged to `main` + deployed + live-verified. main green except
> ONE pre-existing drift red (freshness-checker, NOT this session — see below).**

## What shipped (8 issues, 5 PRs, all closed)

| # | Issue | PR | Deploy | Status |
|---|-------|----|--------|--------|
| #757 | ADR-128: no standing LLM Council | #774 | none (doc) | ✅ |
| #754 | ADR-129: remediation `auto`→`shadow` | #774 | SSM flip (live) | ✅ |
| #752 | ADR-130: GitHub Pages disabled | #774 | `gh api DELETE pages` (live) | ✅ |
| #756 | delete parked hevy-webhook FunctionURL | #775 | `cdk LifePlatformIngestion` | ✅ gone |
| #758 | gate PERMA/Seligman citations on n | #776 | `cdk LifePlatformMcp` | ✅ boots 401 |
| #727 | scientific-liveness heartbeat (grading stall) | #777 | `cdk Compute+Monitoring` | ✅ emits 999 |
| #729 | scorecard honest empty state | #778 | `sync_site_to_s3.sh` | ✅ live |
| #730 | static-render proof surfaces | #778 | `sync_site_to_s3.sh` | ✅ live |

**Live-verified in prod:**
- **#729/#730** — `curl https://averagejoematt.com/coaching/scorecard/ | grep` finds
  `Evaluator live since 2026-06-14 · 309 predictions pending · 0 graded yet · as of {date}`;
  `curl …/story/chronicle/ | grep` finds the dated 4-post list. version.json = `db889804`.
  Mechanism: `scripts/v4_proof.py` bakes `<noscript>` proof blocks at build time
  (live API + `scripts/proof_snapshot.json` fallback, never fabricates) — JS still
  renders the rich view. ADR-104 behavioral-absence + honest "as of" stamps.
- **#727** — invoked `coach-prediction-evaluator` → `liveness:{decided_count:0,
  gradable_count:127, days_since_last_decided:999}`. New `grading-stalled` alarm
  (DaysSinceLastDecided ≥ 14, 2 daily periods, BREACHING) is live and will fire on
  the current all-pending state (the point). alarm_count 109→110.
- **#758** — MCP redeployed via CDK (correct `reading/` staging, boots 401 healthy).
- **#756** — `hevy-webhook` Lambda ResourceNotFound (removed); ingestion lambdas boot
  clean on the reconciled **v118** layer (bonus: cleared the ingestion v115 drift).
- **#754/#752** — SSM `remediation-mode=shadow` verified; Pages returns 404.

## ⚠️ Pre-existing red on main (NOT this session) — decision for Matthew

Both post-merge CI/CD runs (#727, #729/#730) fail **only** on
`Post-deploy integration checks (I1/I2/I5)` → `test_i2_lambda_layer_version_current`:
**`life-platform-freshness-checker` is on layer v116 (current v118)**. This is
**pre-existing drift** (agent-756 flagged it independently; present before this
session) and does **not** trigger rollback (I2 is non-gating; auto-rollback skipped).
Every other job — Lint, Unit, Deploy-critical, **Deploy**, **Visual-QA**, **Smoke** —
passed on both runs.

`freshness-checker` lives in **`LifePlatformOperational`**, which the prior session
**deliberately held** at v115/v116 ("deploy held Operational→v118 on HAE reconcile —
lands `coherence_semantic` tier-1"). `cdk diff LifePlatformOperational` = layer
v115/116→v118 + the held `coherence_semantic` code bundle. **I did NOT deploy it**:
it's outside this session's authorized 8-issue scope AND overriding another session's
deliberate hold unilaterally isn't my call. **To green main:** `cd cdk && npx cdk
deploy LifePlatformOperational --require-approval never` — it's a low-risk layer
reconcile + an advisory-feature budget-gate, but confirm the hold rationale first.

## Notes / gotchas confirmed

- **CI DOES auto-deploy on merge** (the "Deploy" job succeeded on both runs) — my
  manual `cdk deploy`s were belt-and-suspenders/idempotent, not the only path.
- **doc-sync literal drift across concurrent PRs** is real: `test_count`/`alarms`/
  `lambda_count` in `site_api_common.py` conflict when two PRs branch off different
  mains. Fix: before merging each PR, `git merge origin/main` into its branch, resolve
  the literal conflicts by `git checkout --theirs` + re-run `sync_doc_metadata --apply`
  (authoritative from the merged tree), then merge. Did this for #727.
- **GitHub squash-merge rejects a branch with a merge commit** as CONFLICTING even
  when main is a full ancestor — linearize with `git reset --soft <main>` + one commit.
- **MCP deploy = `cdk deploy LifePlatformMcp`**, NOT `deploy_mcp_split.sh` (which omits
  the top-level `reading/` staging and re-breaks boot — deploy.md §MCP is authoritative).

## Untouched (remaining backlog, each its own session)
- **Next milestone:** #735 /verify/ page, #736 build-beat wrap-gate, #739 surge ceiling,
  #741 career artifact, #769 evening ritual, #740 essay, #734 audio, #409 batch-inference.
- **Later:** #395 MCP prune, #421/#422/#475 data depth, #552/#592/#594, #743/#744
  (honesty-layer receipts/retention), #746/#747/#748, #749/#750/#751/#753/#755 (infra/sec).
- Optional #380 build-beat dispatch for this batch (outward-facing content — not done).

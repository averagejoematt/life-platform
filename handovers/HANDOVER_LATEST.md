# HANDOVER — Next-milestone remediation slice 1: 7 /fullreview issues merged (1 held) via two worktree fan-outs — 2026-07-18

> Instruction thread: continuing the /fullreview remediation backlog after the prior session
> drove the entire implementable `Now` milestone to main. Driver: "Keep paying down the
> /fullreview remediation backlog — move to the `Next` milestone… Pick a slice of 2–4…
> fan out `worktree-implementer` agents… you do all the merges (squash + delete-branch)…
> Deploys stay mine." Ran two disjoint-file batches of 4 agents each, verified every diff,
> merged 7, HELD 1 (site auto-deploy).

## What shipped — 7 PRs MERGED to main, 1 PR HELD

All via `worktree-implementer` agents in **isolated worktrees**. Each: issue's Path-to-A +
a **non-vacuous** regression guard (proven to fail without the fix), black/ruff clean, full
offline suite green, `Fixes #N`, verified by me against the diff before merge.

**Batch 1 (disjoint files → all 4 merged):**

| PR | Issue | Fix | Deploy (Matthew) |
|----|-------|-----|------------------|
| #1270 | #1231 | tier-change alert `_TIER_LABELS` rewritten to the ADR-125 ladder (was pre-ADR-125: falsely said tier-2 pauses /api/ask) | `deploy_lambda.sh cost-governor` |
| #1271 | #1236 | /deploy skill Mode 1 → CONVENTIONS §2 pointer (#750 no-approval pipeline) + site-api owner Operational→Serve (#793) + 2 tombstones | none (docs/skill) |
| #1272 | #1220 | chronicle weekday↔date grounding: deterministic `weekday_date_findings()` in `grounded_generation.py` + calendar-facts block into Elena's packet + live-gate wiring | email-λ fleet / `deploy_lambda.sh wednesday-chronicle` |
| #1273 | #1230 | inference-receipt `budget_ceiling_usd` derived from `/life-platform/budget-breakdown` (was hardcoded 75; real $85/$100), fail-closed to $85; bedrock_client tier-3 msg drops the $75 literal; new source-literal ceiling gate in `check_doc_facts.py` | `deploy_site_api.sh` + fleet (bedrock_client shared module) |

**Batch 2 (disjoint files → 3 merged, 1 held):**

| PR | Issue | Fix | Deploy (Matthew) |
|----|-------|-----|------------------|
| #1274 | #1206 | coverage floor `--cov-fail-under` 25→40 + `scripts/coverage_gap_warn.py` self-reminding >10pt gap `::warning::` (fail-open) | none (CI-only; **live on main now** — confirmed Unit Tests green under 40) |
| #1276 | #1209 | bare door URLs (`/data` etc.) 301-normalize to trailing-slash in the `v4-redirects` edge fn (generator `v4_cutover.sh` + regenerated artifact) + smoke-test guard | **publish `deploy/generated/v4_redirects_function.js`** as the v4-redirects CloudFront function (viewer-request, `E3S424OXQZ8NBE`) + invalidate — manual, no CDK |
| #1277 | #1235 | CLAUDE.md experiment-anchor line 2026-07-12/cycle5 → 2026-07-13/cycle6 (+ bonus SCHEMA.md stale date) + 2 AST discoverers in `sync_doc_metadata.py` (self-heals every reset) + `currently`-bound anchor gate in `check_doc_facts.py` | none (docs + CI-gate) |
| **#1275 (HELD, OPEN)** | #1222 | light-mode `--alert` override `#9E4732` (5.4:1 on --page / 5.8:1 on --surface, clears WCAG AA) + contrast regression test | **HELD: `site/**`-only → merging AUTO-DEPLOYS via `site-deploy.yml`** |

## Why #1275 is held (the one open decision for Matthew)

#1275 touches **only `site/assets/css/tokens.css`** + a test. A push to `main` touching
`site/**` auto-deploys via `.github/workflows/site-deploy.yml` (#750, no approval gate —
"the merge IS the deploy"). Since **"deploys stay mine"** is a hard boundary, I did NOT
merge it — merging it would trigger a production site deploy. It's fully verified and ready.
**Matthew's call:** merge #1275 yourself (auto-deploys the CSS a11y fix, gated by
smoke+visual-QA+auto-rollback), or tell me to. All other PRs were lambdas/-only or doc/CI
(they trigger ci-cd *validation* on main, whose Deploy job sits behind the manual approval
gate — safe for me to merge).

## Verification / gotchas
- **Main is code-green.** Batch 1 ci-cd run (79b18fd5): **Lint + Unit Tests + Deploy-critical
  tests all PASS.** The only red is **"Plan deployments"** — confirmed via the emitted
  annotation ("CDK diff detected IAM/policy changes — R8-ST6 gate") to be the **same expected
  R8-ST6 gate from the prior session's #1263 IAM grant, still undeployed** — NOT a new break.
  It reds Plan on every main run until Matthew runs the CDK deploy. See
  memory `reference_r8st6_iam_review_gate`.
- **Floor-40 is safe:** the first main run under `--cov-fail-under=40` (65c96155) had
  **Unit Tests = success** (measured ~45.6% > 40). Confirmed before wrap.
- **`test_count` drift** after each merge auto-reconciled by the repo bot
  (`chore(reconcile) … [skip-reconcile]`); aligned local via `reset --hard origin/main`,
  no double-commit. #1235/#1206/#1209 each added new test files; bot regenerated the literal.
- **Merge cleanliness:** every batch was file-disjoint, so all 7 merges were CLEAN, zero
  conflicts. All agent worktrees removed (`git worktree remove --force` + `prune`).
- **Fan-out playbook reused** (from `project_fullreview_panel`): triage file-footprint per
  issue BEFORE launching; batch only disjoint-file issues; the check_doc_facts.py cluster
  (#1232/#1205) was deliberately DEFERRED because they'd collide with #1230/#1235 on that file.

**Build beat:** none — 7 PRs merged to main but the user-facing fixes are NOT yet deployed
(#1273 site-api ceiling, #1272 chronicle λ, #1276 CloudFront publish, #1270 cost-governor,
#1275 held); the beat gate requires merged-AND-live. Eligible once Matthew deploys.
**Docs:** none needed beyond the in-PR doc edits (#1271 deploy.md + tombstones, #1277
CLAUDE.md/SCHEMA.md anchor + sync_doc_metadata discoverers) which shipped inside their PRs;
all six doc gates green at the wrap commit; `sync_doc_metadata` literals auto-reconciled.

## Residual queue / next picks
- **Matthew's deploys (merged, awaiting live):** #1273 `deploy_site_api.sh` + fleet;
  #1272 email-λ fleet; #1270 `deploy_lambda.sh cost-governor`; #1276 CloudFront function
  publish + invalidate; **#1275 merge decision** (site auto-deploy).
- **Also still pending from the PRIOR session** (unchanged): #1262/#1267/#1268
  `deploy_site_api.sh`, #1263 `cdk deploy LifePlatformCompute LifePlatformServe` (clears the
  R8-ST6 Plan red + the grading-stalled alarm), #1265 email fleet, 2 live-DDB backfills.
- **Next milestone: 30 stories remain open.** The `check_doc_facts.py` cluster (#1232
  monthly_cost ~$60, #1205 ARCHITECTURE.md six false claims) must be **SERIALIZED** — they
  + #1230/#1235 all edit that one file. Other good disjoint picks: #1211/#1212 (tokens/css
  gate), #1214/#1213 (home waveform), #1226 (coaching digest undated vitals), #1204/#1229
  (alarm aging / alert-digest unwatched).

Prior session: `handovers/HANDOVER_2026-07-18_NowMilestoneFanout.md`.

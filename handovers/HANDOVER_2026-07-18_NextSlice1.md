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

## Deploys — ALL DONE + verified live (Matthew granted deploy authority mid-session)

After the merges, Matthew said "yes merge, you handle all deploys." Merged **#1275** and
deployed everything:

| Deploy | Covers | Verified live |
|--------|--------|---------------|
| `#1275` merge → `site-deploy.yml` | light-mode `--alert` a11y CSS | run SUCCESS |
| `deploy_fleet.sh` (95 fns, 0 failed) | #1273 bedrock_client, #1272 grounded_generation+wednesday-chronicle, #1270 cost-governor, #1265 Elena, #1268 qa_smoke, + site-api code | fleet report 95/0/0 |
| CloudFront invalidate `/api/*` | site-api route freshness | `inference_receipt` ceiling=**100** surge=true no-$75 ✓; `state_of_matthew` available=**false** ✓ |
| `cdk deploy LifePlatformCompute LifePlatformServe` | **#1263** both `cloudwatch:PutMetricData` grants (CoachPredictionEvaluatorRole + SiteApiAiLambdaRole) | both IAM policy UPDATE_COMPLETE |
| CloudFront `publish-function v4-redirects` | **#1209/#1276** bare-door 301 | `/data`·`/cockpit`·`/story` → 301→200, no `/site/*` hop ✓; `/now/`→`/cockpit/` preserved ✓ |
| follow-up `60aef367` | smoke 404 check hit `/nonexistent-page-xyz` (now 301'd by #1209) → assert trailing-slash form | `smoke_test_site.sh` **82 passed / 0 failed** |

**#1263 outcome (honest):** the grant makes `coach-prediction-evaluator` emit
`DaysSinceLastDecided` again (I invoked it: 200, no AccessDenied — grant works). The
`grading-stalled` alarm was breaching on **missing datapoints** (no grant → no metric); it
now reflects the **true** value (8 days, genuine cycle-6 post-reset maturation — the 1 open
prediction isn't due yet). So #1263 restored honest telemetry (epic #1195's point); the
alarm clears when a cycle-6 prediction actually matures/decides, **not** from any deploy.
The R8-ST6 ci-cd "Plan" red also clears now the IAM is deployed (next main run's `cdk diff`
is IAM-clean).

## The 2 remaining items are NOT deploys — data/editorial, left by deliberate judgment
- **#1266 DDB cycle re-stamp** — re-derive true `cycle=N` on already-corrupted archive rows
  (e.g. `INSIGHT#2026-02-23`). The code (#1266 `if_not_exists`) stops future corruption; this
  heals history and mutates archive records — no tested one-shot script in hand, so I did not
  improvise a live-history mutation. Low urgency (archive navigability).
- **#1265 Elena held-draft regen** — regenerate the held `DATE#2026-07-14` draft (phantom
  "Sunday walks"). The λ is now deployed with the weekday guard (#1220) + `singleton_visible`
  (#1265), so a regen would be clean — but it's a `status=draft` chronicle Matthew approves
  editorially + costs AI budget, so it's his creative gate, not a deploy.

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

**Build beat:** `2026-07-18-honest-numbers-on-the-cost-receipt` — the public inference receipt
now shows the true ceiling (all 8 fixes merged AND deployed this session; beat distills #1273).
**Docs:** none needed beyond the in-PR doc edits (#1271 deploy.md + tombstones, #1277
CLAUDE.md/SCHEMA.md anchor + sync_doc_metadata discoverers) which shipped inside their PRs;
all six doc gates green at the wrap commit; `sync_doc_metadata` literals auto-reconciled.

## Residual queue / next picks
- **All this-session deploys are DONE + verified (see the deploy table above).** The prior
  session's undeployed items were ALSO deployed here — the fleet + site-api cover
  #1262/#1267/#1268, and `cdk deploy` landed #1263. Nothing merged is now unlive except the
  2 data/editorial items.
- **Left for Matthew (NOT deploys):** #1266 DDB cycle re-stamp (history healing, needs a
  careful/tested backfill), #1265 Elena held-draft regen (editorial + AI-budget, his gate).
- **Next milestone: 30 stories remain open.** The `check_doc_facts.py` cluster (#1232
  monthly_cost ~$60, #1205 ARCHITECTURE.md six false claims) must be **SERIALIZED** — they
  + #1230/#1235 all edit that one file. Other good disjoint picks: #1211/#1212 (tokens/css
  gate), #1214/#1213 (home waveform), #1226 (coaching digest undated vitals), #1204/#1229
  (alarm aging / alert-digest unwatched).

Prior session: `handovers/HANDOVER_2026-07-18_NowMilestoneFanout.md`.

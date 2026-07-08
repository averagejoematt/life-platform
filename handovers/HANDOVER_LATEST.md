# HANDOVER — Highest-complexity pay-down: 4 issues shipped end-to-end, the stack split executed live, CI re-greened — 2026-07-08

> Instruction: "review all open issues … tackle the most highly complex open issues and
> work them through closure … I approve you in advance to all edit requests, all merges,
> and all deploys — fully autonomous session." Picks were the 4 hardest unblocked issues
> (blocked-on-Matthew #740/#739/#741 excluded). Plan: driver-inline #793 (live infra
> surgery) + 3 parallel worktree agents (#812 fable-scope, #409 opus, #734 opus).

## What shipped (4 issues, PRs #866–#869; all MERGED + DEPLOYED + LIVE-VERIFIED)

- **#793** (PR #866, driver) — **site-api + site-api-ai split into a new
  `LifePlatformServe` stack via `cdk refactor`** (CloudFormation stack refactoring): all
  16 resources as PURE moves; physical names AND the Function URL subdomains (pinned in
  cdk.json → CloudFront origins) unchanged. Ops holds on Operational can no longer freeze
  the reader-facing API. Now **9 CDK stacks**. Refactor gotchas encoded in
  serve_stack.py + the PR: LogRetention CRs can't cross stacks (strip → move → re-add);
  the LogRetention SINGLETON sneaks into the destination template (remove for purity);
  refactor can't create the destination stack (`serve_bootstrap` context deploys an empty
  shell first); the CDK bootstrap deploy role needed a TEMPORARY scoped
  `lambda:GetFunctionUrlConfig` policy (attached → refactor → deleted). First attempt
  rolled back clean on that 403 — site never blipped (200 throughout).
- **#812** (PR #869, fable agent) — **golden harness generalized to every AI surface**:
  per-surface golden+canary packs (board_ask/chronicle/memoir/state-of-matthew/field-notes,
  11 goldens + 12 canaries) replayed through behavior-preserving extractions of each
  surface's REAL gate path; `lambdas/eval_retention.py` persists fired-gate pairs to DDB
  `EVALRET#` (180d TTL, cross_phase; the minimal #744 — #744 stays open re-scoped);
  monthly harvest workflow → replay-validated candidates as an artifact for human privacy
  review (never auto-committed); **least-privilege judge role CREATED live this session**
  (`github-actions-golden-eval-role`, Haiku-only + namespaced metrics + `EVALRET#*`
  LeadingKeys; `verify_oidc_iam.py` → CLEAN) so the weekly voice judge now runs on
  schedule. Verified on main: all 5 surfaces "goldens grounded, 12/12 canaries caught".
- **#409** (PR #867, opus agent) — **batch pricing: evaluated → deferred, with receipts**
  (ADR-132). Bedrock batch has a HARD 100-records/job/model floor (verified via this
  account's service quotas, non-adjustable); our total fleet volume is ~62 calls/day
  ACROSS ALL MODELS (Haiku ~31 — even the #808-targeted bucket is a third of the floor),
  and the 24h batch SLA conflicts with the 11 AM brief. Shipped the dormant
  `bedrock_batch.py` seam (eligibility preflight + tested real-time fallback, wired to NO
  producer) + `scripts/batch_feasibility.py` living trip-wire (enable when one model
  clears ~120/day). No IAM shipped — enablement grants documented in the ADR.
- **#734** (PR #868, opus agent) — **daily 2-min audio debrief live**: grounded ADR-104
  Haiku script (deterministic template fallback, fail-closed, budget-gated) → Chirp TTS →
  MP3 + iTunes RSS under `generated/podcast/debrief/`, daily 19:00 UTC. **Live-fired
  post-deploy: 2026-07-07.mp3 (374KB) + feed.xml published.** Panelcast is now
  EVENT-DRIVEN (Friday cron removed; chronicle-approve async-invokes it on publish; hold
  sweep intact) and the standing `panelcast-no-episode-7d` ALARM (red since late June) is
  retired — replaced by `daily-debrief-no-invocations-24h` (never red on a quiet-but-healthy
  day). ~$0.10/mo.

## Repairs made en route

- **Main went red after the #868 merge** — the sequential-gate class AGAIN: the lint gate
  (daily_debrief missing from ci/lambda_map.json) masked a unit fail behind it
  (handler-type-hint ratchet: tolerance had silently absorbed 2 earlier drifts; the new
  handler tipped 70 > 67+2). Fixed both in 52070237: map entry added, the 4
  session-touched handlers typed, baseline RATCHETED 67 → 66 (not bumped up).
- **The first CI Deploy run in days unmasked TWO latent bugs in the post-deploy gates
  themselves**: (1) I2's `lambda:ListFunctions` grant sat inside a function-ARN-scoped
  statement — list actions only honor `Resource: "*"`, so the grant had NEVER worked;
  split into its own statement in `infra/iam/…deploy-role.permissions.json`, applied
  live, `verify_oidc_iam` CLEAN. (2) I22 (live version.json SHA ∈ main history) was
  structurally unpassable in CI: the job's default depth-1 checkout can't resolve any
  SHA older than HEAD, and the live SHA is older by design — `fetch-depth: 0` on that
  job. Both fixes in 8bffec96/fe8ea6fa; site re-synced (live build 8bffec96).
- `ensure_ascii=False` when re-dumping lambda_map.json — a plain json.dumps escapes the
  em-dashes (cousin of the black-corrupts-JSON trap).
- Full-suite false fail `test_hevy_compiler_isolation`: local `cdk.out/` staged-asset
  copies, not drift — `rm -rf cdk/cdk.out` and it greens (same class as stale worktrees).

## Deploys (all pre-authorized this session)

`cdk deploy --all` **9/9 stacks** (198s; ships eval_retention + bedrock_batch +
daily-debrief fleet-wide) · golden-eval IAM role created per infra/iam runbook
(verify CLEAN) · 4 re-typed handlers hot-deployed · one live `daily-debrief` invoke
(episode published) · temp refactor policy attached+removed. **No sync_site_to_s3 run —
no site/ changes this session.** Verified: suite **4060 passed + isolation re-run, 0 real
fails** · smoke **67/67** · `verify_oidc_iam` CLEAN · /api/vitals 200 · alarm swap live ·
visual QA **34/34 passed, 0 failed** (11 warnings, daily-data class) · **conclusive
end-to-end green: full-pipeline `workflow_dispatch` run 28962059847** — every job incl.
Deploy + the I1/I2/I5 integration gates passed on the fixed workflow; live build ==
main tip (95693ff). (An earlier dispatch, 28961253962, failed on the site-sync CLOBBER
GUARD — correctly: I pushed wrap site/ commits while it ran from an older checkout.
The guard works; don't dispatch deploy_all with pushes still planned.)

## Gotchas (this session — new ones only)

- **`cdk refactor` works and is the right tool for stack splits** — but see the 4
  preconditions in the #866 PR body; dry-run first, and expect the us-east-1 env to be
  compared too (scope with `cdk refactor <StackA> <StackB>`).
- **CI's "config change" plan warning can be pure code-asset hash** — read the actual
  property diff before treating it as a held config change.
- **A worktree agent's "cdk deploy Operational for the site-api-ai grant" was stale
  advice the moment #793 landed** — the role moved to Serve; cross-check agent
  post-merge instructions against infra moved mid-session.

**Build beat:** 2026-07-08-daily-debrief-and-serve-split

## Next picks

- **Next milestone is now EMPTY of unblocked stories.** Remaining Next = Matthew-gated:
  #740 essay (edit pass) · #739 surge ceiling ($X) · #741 career-artifact publish.
- Later candidates by leverage: #750 site deploys through CI · #749 CI gate-chain
  decouple (this session hit the masked-gate class TWICE) · #744 re-scoped retention
  delta · #755 DR restore drill · #395 MCP tool prune.
- **Watch:** first scheduled daily-debrief run (19:00 UTC) + its alarm · the Wednesday
  chronicle (privacy guardrail should clear the hold; its publish now also triggers the
  panelcast) · weekly golden-brief judge (now armed with the new role) · monthly
  eval-harvest (1st) · evaluator daily grades (~71 predictions decide through late July).
- **Matthew:** /method/verify/ device URLs (TODO(#735)) · per-model EMF dimension ·
  #417 re-stamp · REVIEW_BUNDLE_2026-07-06.md untracked.

Prior session archived at `handovers/HANDOVER_2026-07-07_next-milestone-paydown.md`.

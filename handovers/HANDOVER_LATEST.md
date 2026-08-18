# Handover — 2026-08-17 (evening, ~18:00 → ~21:45 PT): the system model, and the map found the defects

**Session:** Fable, owner-directed (plan `system-model-and-matured-boxes` executed: Phase 0
owner-ask harvest → the #2845 headline build → a 3-worker sonnet fan-out → merge queue →
deploys → an unplanned main-red fix). Session started ~1.5h after the day wrap, so the
plan's matured boxes all sit tomorrow (08-18 daytime UTC) — noted below, not forced.

## What shipped — 4 PRs merged + deployed, 1 issue filed, 5 issues closed

- **#2865 (#2845 + #2805, the headline)** — **the system model**: `model/platform_model.json`
  + `docs/DEPENDENCY_GRAPH.md` are now GENERATED (`scripts/generate_platform_model.py`)
  from the charter's own authorities (CDK AST, `source_registry`, the ADR-077
  `phase_taxonomy` census — which IS the computed-partition registry #2805 called for),
  drift-gated byte-for-byte every CI run (`tests/test_platform_model_drift.py`, with
  known-true-edge pins so extractor regressions can't masquerade as model changes), and
  queried via `scripts/blast_radius.py --touches/--feeds`. 104 lambdas / 81 scheduled /
  45 alarms (34 routings resolved) / 105 partitions / 644 edges. Sampled ground truth
  **162/163 = 99.4%** (method in the PR; the 1 miss verified prose). Mutation-proven both
  artifacts live. Scope cuts stated in `meta.scope_cuts`, never faked. **#2839 closed with
  verdict (subsumed)** — the prose doc's false-edge class dies with the prose. The model
  immediately surfaced 5 multi-schedule lambdas no doc listed (whoop has THREE schedules)
  and an instrument defect: `check_doc_facts`' regex cron map attributes whoop's *recovery*
  cron as its cadence → **#2866 filed** with tonight's evidence.
- **#2867 (#2860)** — daily-brief in-flight lease guard (`emails/daily_brief_lock.py`,
  DDB conditional-put lease on `SYSTEM#daily-brief-lock`, TTL 1200s > the 900s Lambda
  timeout, fail-open on non-conflict errors) + RUNBOOK safe-invoke reflex; reserved-
  concurrency=1 weighed and rejected in the PR. Deployed direct (`deploy_lambda.sh`) and
  **byte-verified in the live bundle** (lock module present, imported, called at :1635
  before any AI section).
- **#2868 (#2859)** — the two 404ing `/archive/v1/*` redirects were NOT a map gap: the
  `/archive/*` CloudFront behavior (#2572) had **no function association** (the #1805
  class), so every request under it bypassed `v4-redirects`. 14-line `web_stack.py` fix;
  deployed via guarded `cdk_deploy.sh LifePlatformWeb` + viewer-path invalidation;
  **live-verified**: both named URLs (and the wider class) 301, the Permanence tarball
  still 200s. Evidence commented on #2859.
- **#2869 (unplanned)** — main redded 3× tonight on `test_public_write_hardening` vote
  tests (503 vs 404/200). Root cause reproduced BOTH directions: the tests patched
  `_challenge_catalog_cache` but not the `_cache_at` TTL stamp; a stale stamp + CI FAKE
  creds → S3 reload `{}` → 503, while local REAL creds silently served the REAL catalog
  (fixture-must-be-the-wire). Tonight's ~30 new tests shifted the suite past the TTL edge.
  Fix pins the stamp (`None` = the module's own documented test-injection contract);
  proof: a deliberately leaky stale-stamp test + FAKE creds fails 3 exactly as CI did
  unfixed, passes 8/8 fixed. Deploy/smoke/visual-QA were green on every red run — the
  platform was healthy; the instrument wasn't.
- **#2669 needed no work** — the worker verified PR #2795 (merged 08-16, deployed,
  timeout 300s live) already implements it; Wednesday 08-19's chronicle run is its live
  box (its `Fixes` line was `Refs`, so the issue stays open for that evidence — correct).

## Phase 0 findings (the plan's harvest)

- **#2836 September base**: zero comments — still the owner's call, due 09-01.
- **Whoop re-auth**: NOT done (secret last-changed 12:00Z 08-17 = the auto-refresh at
  latch time; no rows past 08-16). The #2085 latch-clear + backfill stay ready to run.
- **Withings genesis weigh-in**: still not synced (0 rows for 08-17+) — baseline remains
  the 321.01 override; supersede reflex documented in `project_monday_reset`.
- **Matured boxes** (all 08-18 daytime UTC, deliberately not forced tonight): #2668
  3-of-3 at the 17:00Z brief; #2858's live box at the 18:30Z qa-smoke sweep; #2735's
  planted red ages out ≤21:20Z.

## Verified

Every merge behind the checks rollup on the exact head sha (`total>0 AND 0 not-green`).
Clean full local suite 19,377 passed / 0 failed (the one earlier red was my own live
mutation-proof racing the suite — re-run clean). Redirects, daily-brief bundle symbols,
and the model's ground-truth edges all verified live, not from claims. Final main run
32096134923 fully green including Unit Tests.

## Gotchas hit

- **A tests-only merge skips Deploy** (Plan classifier) — after the #2869 merge the
  pipeline went green WITHOUT deploying, which would have silently left #2867's guard
  undeployed; caught by checking the run's job list, resolved by direct `deploy_lambda.sh`
  + bundle symbol grep. Reflex: after any merge, confirm the Deploy job actually ran for
  the surfaces you think shipped.
- **Two instruments disagreed about one registry**: my AST schedule extractor vs
  `check_doc_facts`' regex block map (whoop: real cadence vs recovery cron). Rendering
  multi-schedule rows as multi-cron lines (which the #1205 scan skips by design)
  sidestepped it honestly; the checker fix is #2866, not a widened PR.
- **The deploy-gate queue with 3 rapid merges**: run 1 approved+deployed, run 2 rejected
  as superseded at its gate, run 3 completed with Deploy skipped — the lease discipline
  (approve HEAD, reject ancestors) held, but see the tests-only-skip gotcha above for
  what "green" hid.
- The `gh pr merge --delete-branch` local-branch delete fails while the branch's worktree
  exists — remove the worktree first, then `git branch -D`; remote delete succeeds anyway.

## Wrap gates

**Build beat:** 2026-08-17-the-map-became-code
**Docs:** CHARTER.md ("Using this" names the model + query commands) · CONVENTIONS §9 row
(stale-model class → drift gate) · PROPORTIONALITY row (Load-bearing + demote trigger) ·
REPO_STRUCTURE `model/` row + `model/README.md` · DEPENDENCY_GRAPH.md now generated ·
doc-sync literals regenerated (test_count 15653 → 15668 across the queue)
**Decisions:** none needed — #2845/#2805/#2839 execute the already-decided charter/kernel
sequencing (#2842); no new governance posture was set
**Main:** green (46f79a222) — decode: runs 32088472048/32089517789/32090032559 red on the
#2869 test-fixture class only (deploy+smoke green throughout); 32089517789 REJECTED as
superseded at its gate; final run 32096134923 fully green
**Incidents:** 2 rows added — main red ~2.5h across three runs on the vote-test
order-dependence (fixture-not-the-wire; zero user impact, deploys stayed healthy), and
the wrap-beat site auto-rollback (visual-QA transient on /data/autonomic/, false-positive
class — INCLUDING the `--failed`-rerun trap: it greens against rolled-back content and
ships nothing; full rerun + served-artifact check is the recovery; memory reflex written)
**Stash/hooks:** clean
**Closures:** #2845, #2805, #2839, #2860, #2859 all carry the two-line verdict; #2866
filed this session (not closed)
**Backlog:** Now live at 14 actionable; hygiene OK (104 open issues clean after fixing
#2866's Outcome audience); no stale Later issues printed
**Alarms:** gate passed clean — every red >72h cited, every red >14d cites an issue.
Current expected reds: whoop trio (owner re-auth pending, incident row),
`qa-smoke-failures` (empties as #2859's next sweep passes + Whoop clears),
`coherence-overall` planted red (self-clears ≤21:20Z 08-18, #2735), `qa-smoke-warnings`
(#2670)
**CI warnings:** 2 — both the S3Key/config bundle-drift class on LifePlatformMcp +
LifePlatformServe (shared-bundle hash catch-up from tonight's merges, #781 one-bundle);
triage: flattened same-session via the guarded 2-stack `cdk_deploy.sh` (drift guard
reported live code clean, deploys ✅ 16s/21s); closed `--decoded`
**Ledger:** the #2845 drift gate's PROPORTIONALITY row (posture Load-bearing · rent ~30s
CI regenerate+diff per run · demote trigger: drift reds resolved by regenerating without
reading the diff) landed inside PR #2865 itself

## Residuals / next picks

- **#2668** — 3-of-3 close at the 08-18 17:00Z brief (positive-evidence filter query).
- **#2858 live box** — the 08-18 18:30Z qa-smoke sweep should pass `recall:corpus_freshness`;
  comment evidence on the closed issue (reopen if it FAILs).
- **#2735 planted red** — not-work — self-clears ≤21:20Z 08-18 by age-out; confirm only if
  it does NOT.
- **#2669** — Wednesday 08-19's chronicle run is the live box; check duration + single
  generation in logs, close with the verdict.
- **#2866** — the check_doc_facts cron-map fix (derive from the model's extractor).
- **#2670** — the `qa-smoke-warnings` threshold shape; sequence after Whoop clears and
  #2859's sweep passes (both in motion tonight).
- **Whoop re-auth** — owner ask #2 (standing); then #2085 latch-clear + gap backfill
  08-16→now.
- **#2836** — September base, owner ask #1, due before 09-01.
- **Genesis weigh-in supersede** — not-work — standing reflex fires when the Withings
  reading syncs; baseline stays 321.01 until then.
- **#2845 follow-ons already tracked**: field-level edges on #2797; enrollment-by-
  construction #2846; resident-operator #2847+ (charter-sequenced, epic #2842).

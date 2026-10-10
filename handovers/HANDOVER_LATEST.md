# Handover — Session BL: overnight bug bash — 44 PRs merged and deployed, 26 issues closed with proof (2026-10-10 05:00Z → ~16:40Z, Opus 5.5, owner at the keyboard until ~05:45Z, then asleep)

**Driving instruction:** `~/.claude/plans/overnight-bugbash-2026-10-10.md` (owner confirmed "Yes, all of it", then "work until at least 9am PT"). Phase 0's AWS steps first, then waves of lanes with a workflow (worktree-implementer → finding-verifier), a scripted merge train, synthetic and live proofs, and this wrap.

## Shipped
- **Phase 0 (owner on hand):**
  - **#4707:** #4708 merged; `cdk_deploy.sh LifePlatformOperational`; rotation finished (AWSCURRENT → 72598c99, `finishSecret completed successfully`); bridge `.config.json` re-synced and backed up first (`tools/list` = 87).
  - **#4704:** two `target_frequency` strings → numbers by conditional update; `daily-metrics-compute` back-filled 10-04..10-08 (grades 73/76/77/72/72, `computed_lag_days` stamped); `BADGE#lost_20` written.
  - **#4541:** re-grade applied (mind_coach 8/18 → 7/18).
  - **#4652:** the owner's forecast confirmation posted.
  - **#4637:** 09-27 recomputed beside its neighbours.
  - **#4607:** p95 1.37 s (box 2 met).
- **44 PRs merged**, each re-tested on fresh main, ALL GREEN and verifier-checked:
  - #4708 #4684 #4686 #4687 #4713 #4717 #4716 #4718 #4711 #4725 #4720
  - #4712 #4727 #4722 #4726 #4719 #4721 #4730 #4735 #4740 #4724 #4723
  - #4733 #4739 #4745 #4743 #4728 #4744 #4742 #4752 #4734 #4754 #4755
  - #4756 #4753 #4758 #4760 #4759 #4757 #4762 #4763 #4764 #4765 #4767
- **Deploys:**
  - CI, plus two attended `deploy_fleet.sh` runs (108/108 each) and `deploy_site_api.sh` from main (deployed sha == shipping sha 557cfaad, then 057ec826). These covered the merges whose runs were superseded.
  - `cdk_deploy.sh LifePlatformMonitoring` (#4728 autopublish-held alarm).
  - `LifePlatformIngestion` + `LifePlatformMonitoring` (#4764 Hevy reconcile rule; one additive EventBridge invoke permission).
- **26 issues closed with proof:** #4707 #4704 #4541 #4637 #4411 #4431 #4648 #4671 #4673 #4650 #4672 #4649 #4568 #4569 #4539 #4709 #4729 #4532 #4636 #4701 #4761 #4750 #4690 #4766 #4622 #4689.
- **9 filed:** #4714 #4729 #4731 #4732 #4749 #4750 #4761 #4766 #4780.
- **Open count:** 114 → 108. By this session alone it would be 97; another session filed #4768–#4778.

## Verified
- Main green at c42ea942, then e926b5b2 (`check_main_green`).
- Both hand fleet deploys: 108 updated, 0 failed, ancestry postflight OK.
- The pre-flight now names red alarms (#4709). It saw the DLQ alarms clear as predicted.
- Proof passes: two workflows (gather → adversarial check → post/close).
  - 23 issues got partial proofs, which wait on natural runs.
  - Closures happened only when the gatherer AND the verifier agreed.

## Gotchas
- **A supersede chain strands deploys.** Merging every few minutes cancelled ~8 CI deploys, and the plan diffs only SHA~1. Batch merges and finish with an attended fleet + site-API deploy. ([[reference-overnight-driver-mechanisms-2026-10-10]])
- **A CDK deploy before old runs drain reds their Plan.** It happened at 07:30Z: older SHAs read #4728's new alarm as a DESTRUCTION.
- **A new `AWS::Lambda::Permission` is OWNER-REQUIRED to CI's IAM gate even when additive.** Main was Plan-red 10:55–11:40Z until `cdk_deploy.sh` plus a re-run.
- **The merge train ignored a `CLOSING-SET NONGREEN`.** #4743's text closed instrument #4689 with no proof. It was reopened, then closed properly on a green webkit-mobile-qa run.
- **The classifier denied reading six lanes' verdicts from the workflow journal.** The workflow now returns compact summaries instead.
- **Verifiers caught real defects before merge:**
  - a sealed-bet hiding filter (#4721);
  - a wall-clock time bomb that would red CI from 2027-01-01 (#4767);
  - a privacy finding answered "N/A" being dropped (#4753);
  - a self-name false positive on 'Max' (#4711).
- **The Visual QA truth leg is LLM-judged and lands on a new page each run** (physical, then zone2). #4619's "next run green" rule may never settle.
- **Compound shell lines prompted the owner.** Keep one plain command per call ([[feedback-overnight-no-prompts-compound-shell]]).

## Residual / next picks
- **#4618:** the re-grade is HELD. Today's dry run is 56/131 → 53/129, not the issue's 45/106 → 43/105. It's the owner's call.
- **#4738:** held. It archives `/api/edition`'s `his_words` block publicly, which is a privacy call for the owner.
- **#4715:** CodeQL alert #190 is a false positive (it logs the secret's name, not its value). The owner dismisses it, then merges.
- **Held because the classifier denied reading their verdicts** (owner reads the PRs; #4751/#4748/#4747/#4741 now conflict on census lines and need a restack):
  - #4746 (#4545), #4741 (#4731), #4736 (#4595), #4751 (#4252), #4748 (#4536), #4747 (#4702).
- **#4643:** box 5 needs `s3:GetBucketNotification` on `github-actions-deploy-role` plus one step in `config-drift.yml`. Box 2's first reconcile datapoint is due 18:30Z.
- **#4619:** a green standalone Visual QA run is blocked by the LLM truth leg's moving target. The owner should decide whether that leg gates the advisory workflow.
- **#4780:** the evidence page's year-less projected goal (#4766's class on a second page).
- **#4732:** the owner archives his chat-authored stale drafts; the pre-draft's own drafts are now archived by #4739.
- **#4635:** the repair writes overwrite source partitions, which tonight's hard stops forbid. They're the owner's.
- **#4473 / #4502:** the dependabot `lambdas/requirements` bumps fail the layer-manifest pin, so the layer needs a rebuild. The push also reported 5 Dependabot alerts on main (2 high).
- not-work — the alarms self-clear today: compute-pipeline-stale at ~17:01Z, qa-smoke-failures at ~18:31Z, and the Hevy reconcile heartbeat at ~18:30Z. Citations carry the expiries.
- not-work — post-deploy live proofs due from natural runs: #4705 (19:00Z coach line), #4703, #4655, #4535, #4593, #4694, #4714, #4503, #4189, #4560, #4675 and #4533. Partial proofs are posted on each.

**Build beat:** none — a paydown night of 44 small fixes has no single reader-facing story worth a beat; the owner may pick one later
**Docs:** docs/alarm_citations.json (four entries re-pointed, two cleared DLQ entries removed, Hevy heartbeat added), docs/OPERATING_KNOWLEDGE_LEDGER.md (three rows); PR-level docs (SCHEMA.md, RUNBOOK.md, PROPORTIONALITY.md counts) changed inside the lanes
**Decisions:** none needed — no governance rule moved; every authority used was in the plan's pre-approval
**Main:** green (e926b5b2)
**Incidents:** none — main was Plan-red twice for under an hour each (07:30Z CDK ordering; 10:55–11:40Z additive-IAM gate), decoded above
**Stash/hooks:** clean
**Closures:** ADR-099 Shipped/Outcome verdicts on all 26; #4690 and #4689 got their verdicts after auto-close · DoD: scanned 25, hits 2 — #4649 residual homed on #4714 (post-close comment; its "stays open" refers to #4714), #4766 residual homed on #4780
**Backlog:** Now live at 22 (sonnet 3 · opus 22 · fable 2); no stale Later issues; tonight's 5 open filed issues fixed to the filing contract (area, milestone, epic reason, acceptance count)
**Alarms:** 4 red, all cited — compute-pipeline-stale and qa-smoke-failures as dated self-clearing windows (expiry 10-10T17:30Z / 19:30Z), qa-smoke-warnings → #4732, ingest-reconciliation-hevy-heartbeat → #4643; both DLQ alarms flapped x6 (the compute outage) and are cited → #4731
**CI warnings:** 9 — 4 comprehension-judge 1/2 scores (/coaching/, /data/, /cockpit/, /): front-page wayfinding is the Fable lane (#4586/#4581), no action tonight; 5 'SKIPPED in CI — no playwright/chromium' are the known #3640 skip, no action
**Ledger:** omitted — tonight's standing machinery (#4764 Hevy reconcile + heartbeat, #4728 autopublish-held alarm, #4757 drift script) landed with its PRs; no row re-audited at wrap

# Handover — Session BM: bug bash 2 — the six held PRs landed, two paydown waves, 12 PRs merged and deployed (2026-10-10 21:18Z → 2026-10-11 ~00:15Z, Opus 5.5, owner away)

**Driving instruction:** `~/.claude/plans/next-session-bugbash-2-2026-10-10.md`, with the owner's approval of its Authority section as written: "Do everything that doesn't need me without asking; keep the 'Waiting on the owner' items parked until I say I'm available." Run as five workflows: held-PR re-verify/fix/re-verify, a proof sweep, two implementation waves (worktree-implementer → finding-verifier → fix), and one re-verify pass. A scripted merge train merged one PR at a time, each with fresh main merged in locally, its touched tests plus the census/truth tests re-run, ALL GREEN, a hard stop on `CLOSING-SET VERDICT NONGREEN`, and `check_merge_commit_closures.py --sha` after.

## Shipped — 12 PRs merged, in two batches with a full CI run between
- **Batch 1, the six PRs Session BL held.** Each was re-verified fresh, fixed, restacked and re-verified:
  - #4746 (#4545): story craft gates. The verifier caught that the opening check rejected the word "weight".
  - #4741 (#4731): DLQ recurring-failure escalation.
  - #4736 (#4595): the whole-life scorecard. Mind's rule now names its not-enough-data condition.
  - #4748 (#4536): the Panel week window. Restacked onto #4728's desk HOLD, which was a semantic conflict.
  - #4751 (#4252): the unit suite runs as three shard legs. The census was re-measured from 779 to 781.
  - #4747 (#4702): the claim hold uses gap intervals. The verifier caught a 400-day wall-clock time bomb, now fixed with clock-pinned tests to 2030.
- **Batch 2, waves 1–2:**
  - #4783 (#4780): the projected goal shows its year.
  - #4782 (#4773): Sonnet pins for routine subagents. Its body's "Close #4773 on…" prose parsed as a closing keyword; the train stopped, and it was reworded.
  - #4784 (#4769): the two callers' Bedrock model names.
  - #4786 (#4770): the feature→tier→model registry. It was restacked over #4784; every route resolves to the same model as before.
  - #4788 (#4771): the model swap-eval harness, dry-run only.
  - #4787 (#4778): cache floors derived from the resolved model. Its restack dropped prompt_cache's guard exemption, so the census went 782 → 781. A verifier proved this was subsumption, not a lost guard.
- **Deploys:**
  - CI deployed both batches: `cd873ffe` and `379cae00`, each run green end to end.
  - Two attended `deploy_fleet.sh` runs, 108/108 each, ending with `deployed sha == shipping sha` 2d44828d then 379cae00.
  - Two `deploy_site_api.sh` runs at the same SHAs.
  - The site-deploy runs for 68f30c7c and 1872e07d were green.
- **Closed with proof:** #4780 (a live render at 2026-10-11T00:03Z reads "Jun 23, 2027–Sep 10, 2027"; Live proof plus Shipped/Outcome posted).
- **Filed:** #4789 (the #4741 signature ledger has no time window, P3).

## Verified
- Main is green at 379cae00, and #4751's three shard legs ran on it.
- Every merged PR was fresh-verified, and every PR that carried a fix pass was re-verified before merge. The workflows returned compact verdicts, so no verdict was read from a journal.
- Proof sweep over 13 issues (#4705 #4703 #4655 #4535 #4593 #4694 #4714 #4503 #4189 #4560 #4675 #4533 #4643):
  - Gatherer and verifier agreed on no closure, so none closed.
  - Partial proofs are posted where the evidence was new.
  - #4643 box 2 (the 18:30Z reconcile datapoint) is proven; box 5 waits on the owner.

## Gotchas
- **`cdk_deploy.sh` was denied by the auto-mode classifier** as "Protected-Scope IaC Apply". Right after the denial, a read-only CI poll was also refused. Per the plan it was parked, not routed around; plain `gh pr checks` reads worked again on the next call. Pre-approval in a plan does not carry through the classifier; CDK applies stay owner-attended.
- **A PR whose CDK change CI's IAM gate calls owner-required must not merge without its deploy.** #4785 is held for that reason.
- **The shell's cwd is the stale main checkout.** A first `deploy_fleet.sh` from it was refused by the ancestry preflight (057ec826 over the live cd873ffe), and nothing was updated. Deploy from a worktree reset to origin/main (`deploy_from_main.py` in the scratchpad).
- **Prose can be a closing keyword.** "Close #4773 on its first live output" made GitHub link #4773 as closing. The train's NONGREEN stop caught it.
- **Two PRs that touch the same callers or census conflict in sequence.** #4786 and #4787 each needed a restack after the PR merged before them, and a restack that changes substance (the census drop) needs its own verifier.

## Residual / next picks — waiting on the owner (one list, give it to him when he says he's available)
- **#4741 dashboard:** run `bash deploy/cdk_deploy.sh LifePlatformMonitoring`. The classifier denied it. CI warns "Pending owner cdk deploy (LifePlatformMonitoring)".
- **#4774:** merge PR #4785, then run `bash deploy/cdk_deploy.sh LifePlatformMcp`. It adds the CloudWatch read the receipt needs; the PR is held until you're there.
- **#4473 / #4502:** publish `garth-layer:4` from the staged build (an AWS write). A lane then promotes the manifest and opens the bump PR.
- **#4595:** should a walk-only day count as a training day on the scorecard? It merged with the rule as written.
- **#4771:** run the real swap-eval rehearsal (about $0.09–0.18, under the $5 cap), and review a captured per-feature sample before it is committed.
- **#4777:** approve amending ADR-132's trip-wire (or merge ADR-161, PR #4779) and the new Bedrock batch IAM role.
- **#4779:** ADR-161, the AI model strategy, is another session's PR and needs your merge decision.
- **#4675:** a wrong-verdict card with no call page: reword the box, hide the card, or give it a page.
- **#4655 / #4535:** one Lambda invoke each (the habitify re-ingest of 09-24; the wednesday-chronicle week-4 dry run).
- **#4593:** `python3 scripts/season_promote.py --effects-only --weeks 4 --apply`.
- **#4694 / #4714:** rulings: the ungated podcast legacy writer; whether the serve-side hold satisfies "rewrite or hold".
- **#4643 box 5:** grant `s3:GetBucketNotification` to `github-actions-deploy-role`.
- **#4618:** re-grade at today's numbers (56/131 → 53/129)?
- **#4738:** may `his_words` enter the public archive?
- **#4715:** dismiss CodeQL #190 (false positive), then merge.
- **#4732:** archive your chat-authored stale routine drafts.
- **#4619:** should the LLM truth leg gate the advisory Visual QA run?
- **#4635 / #4646 / #4617 / #4584 / #4585:** repair writes and rulings, unchanged.

## Residual / next picks — agent work
- **#4772:** move the workhorse tier to Haiku 5.5 behind the swap eval. It is unblocked by #4770/#4771 but needs #4771's real rehearsal first.
- **#4789:** the DLQ signature-ledger time window (sonnet).
- **#4731, #4545, #4595, #4536, #4252, #4702, #4769, #4770, #4773, #4778:** live proofs due from natural runs or deploys. Each PR body names its proof.
- not-work — the proof sweep's natural-run waits are dated on each issue (#4703 Mon 10-12 14:00Z; #4533 Wed 10-14; #4189 the first note after the 10-11 03:00Z nudge).

**Build beat:** none — a paydown session of plumbing, guards and preview fixes, with no reader-facing launch to narrate
**Docs:** none needed beyond the lanes — PROPORTIONALITY counts, COACH_STANCE's Verified stamp and the doc-sync literals moved inside their PRs (#4751, #4786, #4787)
**Decisions:** none needed — no governance rule moved; ADR-161 (#4779) and the ADR-132 amendment (#4777) are parked for the owner
**Main:** green (379cae00)
**Incidents:** none
**Stash/hooks:** clean
**Closures:** #4780 commented (Live proof + Shipped/Outcome) · DoD: scanned 1, hits 1 — #4780 no-outcome-verdict, dispositioned by the Outcome comment
**Backlog:** Now live at 22 for the opus lane (floor 3, 0 short); no stale Later issues (107 open satisfy the filing contract)
**Alarms:** every alarm red >72h cited; no uncited flaps (gate PASS)
**CI warnings:** 6 — 5 are the known #3640 'no playwright/chromium' skip (no action); 1 is 'Pending owner cdk deploy (LifePlatformMonitoring)', the #4741 dashboard parked above for the owner
**Ledger:** none — no new standing subsystem; the #4786 routing guard and #4751 shard legs carry their census/PROPORTIONALITY updates in-lane

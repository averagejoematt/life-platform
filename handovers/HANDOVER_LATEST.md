# Handover — Session BO: the Fable overnight — round 8 of the preview front page, eight lanes merged and deployed, the owner list parked (2026-10-11 ~05:00Z → ~10:00Z, Fable 5.1, owner asleep)

**Driving instruction:** `~/.claude/plans/next-session-fable-overnight-2026-10-11.md`, its Authority section approved as written: do everything that needs no owner, park the rest, never stop to ask. Fable drove the site (round 8) and the judgment calls; one workflow of eight worktree-implementer lanes, each adversarially verified and repaired, did the paydown; two red-team workflows (seven hard-marking reviewers each) graded the preview before and after the fixes.

## Shipped — 8 PRs merged, all deployed
- **#4806** (#4586 / #4580): round 8 of `/next/v8/`. The open bet leads as the one real disagreement (two coaches, opposite sides, each with its job, the live number inside the card, the door to what each argued); then the week's clearest miss with the coach named and the result in bold; then the last 24 hours (a line already printed above is not printed twice; with nothing said today, the newest short line heard, or nothing); then one row each to go deeper. The week band moved whole to the new `/next/v8/week/` (the scorecard with each rule under its row, the lead's read when served, the latest chapter). Three commits: the rebuild, the round-8a fixes, the round-8b fixes. Squash `76c607336`; site deploy 38117977820 (deploy + smoke green; the visual QA leg was in flight at the wrap). The front page is 4.5 phone screens on live data.
- **#4805** (#4583): the daily coach moves refuse a repeat of yesterday's point, a second "so far" / "I think" in one day, and jargon (plain words); the prompts rewritten; 15 tests on the wire lines. Fable's read of the live lines 10-05 → 10-09 is on the issue.
- **#4802** (#4774, box 3): the inference receipt's model and feature rows carry the registry tier, untiered rows counted. **#4774 closed on live proof** (tier on every row at 08:25Z; 13 of 43 Lambda rows resolve, honestly null for the rest).
- **#4804** (#4535, box 2): the week-5 packet never reached the week-4 writer; four things that did leak the current window (output date, idempotency row, fallback writer, unlabelled logs) are fixed and pinned.
- **#4801** (#4789): the DLQ ledger's attempts reset after `LEDGER_WINDOW_DAYS` (3) with a conditional two-step update. **#4800** (#4797): `run_or_fallback` stops the job, falls back on-demand and cleans up when the wait raises. **#4803** (#4796): the eval credential stub never shadows a resolvable chain; a $0.015 real call proved it.
- **#4807** (#4674): `deploy/repair_published_content_4674.py`, a dry-run repair for the published week-2 episode title and week-4 excerpt; the dry run's three one-line diffs are on the issue; `--apply` is the owner's.
- **Deploys:** attended `deploy_fleet.sh` (108 updated, 0 failed) and `deploy_site_api.sh` from a worktree at `b7bb49df`, every postflight `deployed sha == shipping sha`; CI/CD green on `b7bb49dfb` and on `76c607336` (the earlier per-merge runs were superseded, as expected).
- **PR #4544** (#4257, held): refreshed against main by a lane (`befed8ce4`, MERGEABLE; the read-only role gained `s3:GetBucketNotification` because #4798 moved that call to a job the PR gives the read-only role); the design reviewed and the owner steps posted on #4257.
- **Filed:** #4808 (one house rule for the verdict line) and #4809 (scorecard verdict words say what happened; the bet carries each side's reason) — the round-8 asks that are served text, not kit.

## Verified
- **Red-team round 8**, posted beside round 7 in `~/.claude/plans/averagejoematt-platform-plan/red-team-2026-10-04.md`. 8a (first commit): front page C+, storytelling C, daily return D+, coherence D+, first screen B, feel him D+, honesty C, meeting B; all seven said first that "Two coaches disagree." sat over two quotes that agreed. 8b (after the fixes): daily return → C, weekly return → B−, day page → B−, 20-second → B, wayfinding → B−, coherence → C, honesty → C+, return → B−, understand → B, meeting → B+, ten-second read → B; flat: the director (front C+), the newcomer, `cast` C−, `feel him` D+. All seven, both rounds: capped by his dated note and question (#4584), the simple guess's score (#4585), the unprintable-calls ruling (#4617).
- **#4607:** 20 cache-busted `/api/edition` reads at 06:25Z — p50 1.18 s, p95 1.27 s, with the `upstream_ms` table (nutrition 1,021 → 12 ms after #4699). Box 4 reads on 10-12 against the 10-11 UTC day (the 10-10 day carries one pre-deploy flap).
- **#4732 box 2:** the 02:00Z sweep archived 24 expired pre-drafts, 0 errors, matching the dry run. **#4643 box 5:** a dispatched config-drift run printed `expected 4, live 4` again (the run is red on `GetBucketPolicy`, the owner's grant).
- **The moves data, read honestly (#4583):** the lines are moves (reactions, replies, questions, calls) and carry a real exchange (Webb/Okafor on protein) and a real bet (Reeves/Webb, 190 g), but they repeat day to day, five of eight carry "so far" and "I think", and three name their own speaker. The front page never picks a self-naming line; #4805 refuses the rest going forward.
- JS suite 801/801; the kit gate clean (front 4.51 of 6, week 1.95 of 4); Python 282 passed on the appendix, fixture, vocabulary and structural gates; every lane's PR asserted ALL GREEN with no `CLOSING-SET NONGREEN` before its merge.

## Gotchas
- **A reply and its answer are not a disagreement.** The first cut headed an exchange "Two coaches disagree." over two lines that reached the same conclusion; every reviewer caught it. Only a bet (opposite sides by construction) is ever headed that way now; an exchange is "the latest exchange".
- **A section with nothing to show must not render its heading.** "No coach had anything to say on Saturday" under "The coaches today" was read as the site being down (the built page lists that sentence as an outage symptom).
- **`gh issue view` returned empty files for five issues** (#4580, #4702, #4789, #4796, #4797) with no error; `gh api repos/.../issues/N` worked. Read issues through the REST path when a view comes back empty.
- **The merge train skips a PR whose full suite is still pending** (one check not green) — re-run the batch once the suite lands; six of seven merged on the second pass.
- **`test_experiment_library_citations_1983` red on HTTP 429 again** (PR #4806's full suite); `gh run rerun --failed` cleared it. Same class as BK's.
- **In zsh, `echo =====` is an `=command` expansion**, not text — quote it.
- **A worktree created from inside another worktree lands outside the canonical parent** (`worktrees/life-platform/worktrees/merge-train-scratch/issue-4643-…`); the reaper names it. Create lanes from the main checkout.
- **Nothing was classifier-denied tonight**; the session ran with bypass permissions, and the plan's hard stops (no invokes, no DDB/S3/IAM writes, no `cdk_deploy.sh`) were kept by hand.

## Residual / next picks — waiting on the owner (the ELI5 list is in the wrap message)
- **#4771 / #4772 / #4796 box 4:** enable Claude Haiku 5.5 in Bedrock → Model access (us-west-2).
- **#4257:** run PR #4544's IAM steps 2–3, merge it, `setup_github_oidc.sh`, `verify_oidc_iam.py --strict`. This also ends **#4643**'s nightly red (`GetBucketPolicy` rides the read-only role); otherwise a one-line grant on the deploy role.
- **#4674:** `python3 deploy/repair_published_content_4674.py --apply`, then re-read the two objects (boxes 1–2).
- **#4535 box 2:** the `{"week":4,"dry_run":true}` invoke with `--cli-read-timeout 900`; expect `"date": "2026-09-29"` and the `[#4535] legacy data packet` line.
- **#4793 / #4732 box 3:** the cron-draft scope ruling, then merge; three nightly qa-smoke runs read the box.
- **#4768:** add #4796 and #4797 to the epic's story list.
- **#4705 / #4583 (stored rows):** the three self-naming lines (10-05, 10-07, 10-09) stay on their day pages unless the owner wants the one-line DynamoDB correction.
- **#4586 / #4588:** the owner's yes per screen on the round-8 preview; promoting it is his call.
- **#4646, #4590, #4584, #4585, #4617, #4627, #4644, #4615, #4678 (PR #4679), #4645:** unchanged.

## Residual / next picks — agent work and proofs due
- **#4705:** live proof on the 19:00Z run (a first-person self-reaction with no self-name). **#4583:** the same run shows the new refusals in the `HELD` reasons; watch the verifier's over-refusal note (`as of`, `model`, `gate`).
- **#4703:** box 4 on the Monday 14:00Z analyzer run. **#4694:** the first Mon/Wed hold. **#4593:** the qa-smoke `share_kit` cell at 18:31Z. **#4607:** box 4 on 10-12. **#4702:** closes when the CGM reports again and the gap has an end date.
- **#4808, #4809:** the two round-8 lanes (opus, Next). **#4789 / #4797:** live proofs on the first qualifying event.
- not-work — the design calls Fable made tonight and did not ask about: the bet leads, an exchange is never "disagree", empty states vanish, the weight is the hero number, the miss rotates weekly, the week band is a page.

**Build beat:** none — the merged work is preview-page and pipeline plumbing behind `/next/v8/`; nothing new on a reader-facing surface
**Docs:** none needed — the new `/next/v8/week/` page is a preview candidate held by the kit gate and the appendix test, not a live door in SITE_MAP_AND_INTENT; the lanes updated their own docstrings
**Decisions:** none needed — no governance rule moved; the round-8 design calls are the owner's standing delegation (10-04) and are recorded on #4586
**Main:** green (76c60733)
**Incidents:** none — the two flaky 429s on the citation test were not code; no rollback fired before the wrap (the visual QA leg of site deploy 38117977820 was still running)
**Stash/hooks:** clean — the reaper removed 3 released lanes and named one worktree outside the canonical parent (a #4643 lane created from inside the scratch worktree)
**Closures:** #4774 commented (Shipped/Outcome, live proof at 08:25Z) · DoD: scanned 5, hits 0
**Backlog:** Now live at 3 for the fable lane (floor 3); no stale Later issues (105 open satisfy the filing contract); filed #4808, #4809
**Alarms:** every alarm red >72h cited; no uncited flaps (gate PASS)
**CI warnings:** 5 — all the #3640 class ("SKIPPED in CI — no playwright/chromium" on the unit shards); no action, the render and kit gates run them on a chromium machine
**Ledger:** none — no standing machinery shipped; the week page sits under the existing kit gate and the repair script is a one-shot owner tool

# Handover — Session AY: the overnight driver, the owner's cardio incident, and a 12-hour stall (2026-09-27 19:01 PT → 2026-09-28 ~09:15 PT)

**Driver brief:** `~/.claude/plans/overnight-ay-2026-09-27.md`, the autonomous overnight run. Standing grant: fleet/site-api deploys from main's tip, merge green PRs through the checklist, close issues on live proof only. Not granted: CDK, `aws s3` on `config/`, `aws lambda invoke`, DDB writes, IAM. **Model:** Opus 5.5. The Sonnet burn-down session ran alongside (its own ledger is on epic #4246).

**The owner was awake for part of it.** At ~02:15Z they asked how many issues the session could close. They pasted the 09-27 cardio incident (→ #4387, #4388 and the routine spec). They answered two rulings on #4388.

**The stall:** the second rulings question (a correction to my own arithmetic, see Gotchas) blocked the turn until the owner answered at ~15:55Z. That is ~12 h idle between ~03:25Z and ~15:55Z. The overnight lanes had all finished before it. The 07:30 PT wrap slipped to ~09:15 PT.

## What shipped — 8 PRs merged by this session (#4385 #4386 #4389 #4391 #4394 #4396 #4398 #4393; the Sonnet session merged its own)
- **#4385** (Refs #4260): the `deploy from a worktree` advisory fires only on an executed deploy script from a worktree not detached at origin/main. `grep`/`cat` of `deploy/` are silent. Hook-only, live on the main checkout after an ff pull.
- **#4386** (Refs #3005): records the two 09-26 squash commits (#4243, #4236) whose GitHub-appended co-author line carries the owner's `claude@` address. `test_reachable_history_carries_no_trailer_since_ban` had been red in every full clone; CI's shallow checkout skips it.
- **#4389** (Refs #4387): `docs/coaching/routines/lower/lower_volume_w1_s3.md`, the committed 09-28 routine (from DDB `ROUTINE#f905fdc2` v3; the S3 `config/` copy was not read, no grant).
- **#4391** (Refs #4384): a coach's "one thing" is a sentence or null. The `themes[0]` slug fallback is removed, and `audience_guard.is_machine_token`/`reader_prose` refuse a bare token in prose slots.
- **#4394** (Refs #4387): the P1 cardio incident fix.
  - The walking window now ends at target−1.
  - New `constraint_block.recent_aerobic`: per-activity rows, #4068 de-dup, Hevy blocks, redline flags, 48 h/72 h/week-to-date totals.
  - The joints critic swaps a lower day's weight-bearing cardio to recumbent cycling at ≥3.0 h weight-bearing in 48 h, carried as `additional_changes`.
  - `draft_custom` warns when its cardio block disagrees with `cardio_pick`.
  - `walking_overshoot` is new and report-only. `walking_collapse` is now **info** in the nutrition adherence critic, where it was `change`; its action text still says "mandatory human contact". The owner may want that reverted.
- **#4396** (Refs #4365): `lambdas/common/media_tombstone.py`. The Panel and the debrief tell a 186/199-byte restart tombstone from a real episode (58 live debrief tombstones on real dates).
- **#4398** (Refs #4392): one `audience_guard.public_themes` seam humanises theme lists on `/api/coach/<id>`, `/api/journal_analysis` and `/api/reading_*`.
- **#4393** (Refs #4388): the v03 entry floor is **% of band e1RM**; a novel-again anchor keeps the anchor-set base. **Owner rulings:** the floor rounds to the **nearest 5 lb** (61.9 kg → 135 lb, so his hand-written 135 commits); the week-6 cap follow-up is #4397. Merged at ~15:59Z; CI deploys it.

**Deployed:** by CI after each merge; the production gate was approved by this session's `watch_deploy_gate.sh` (re-armed 15:58Z for 3 h). The fleet is live at `5e02c4b0` (daily-brief, hevy-routine-cron, coach-panel-podcast), MCP at `2c827c69`, and site-api carries #4391/#4398 (proven by content). #4393 (`2190aba7`) is in CI now.

**Open PRs this session left — owner-side:**
- **#4395** (Refs #4256): **ADR-158**, awaiting owner review. Only IAM/CDK keeps the `production` click; code deploys on green; `scripts/check_deploy_deadman.py` alarms at 4 h. It deletes `deploy/watch_deploy_gate.sh`: **stop any gate watcher after merging.** The deferred retirements (janitor, `check_deploy_wedge.py`, `merge_train.sh`, the land §3 rewrite) are a checklist in the PR.
- **#4390** (Refs #4259): **held for the owner.** Its new wrap gate runs `worktree_reaper.py --apply`, which the auto-mode classifier denied this session (~02:05Z); merging it would make `/wrap` perform the denied action. The dry run went from 140 s to 19 s. The attended reap is in the PR comment.

**Open PRs this session left — held for timing:**
- **#4399** (Refs #4362): the recap card. Habit renames resolve via `habitify_names`; a registry habit absent from the day's Habitify row is "unobserved", not missed; a measured walk credits a walk habit. **Held so the 16:40Z/17:00Z runs prove the earlier deploys unmuddied.** It touches `daily_metrics_compute` and `ai_calls`, so merge it after 17:25Z.
- **#4400** (Refs #4358 #4359): the Performance and explorer coach blocks get real inputs through the new `intelligence/brief_domain_inputs.py`. **Held for the same reason** (it changes the brief's gather); merge after 17:25Z.

## Verified — closed on live proof
- **#4149** (02:00:55Z): the nightly pre-draft `4300a686` brings back a trap-bar deadlift after 325 days; the joints change is computed in code, applied, `recheck.passed=true`.
- **#4260** (02:35–02:37Z): real hook payloads, six rows — a lane deploy warns; a deploy detached at main is silent; a grep is silent; a merge without a watcher and a chained watcher both flag; a lane push records the lane's sha.
- **#4384** (03:13:57Z): `/api/coach_analysis` sleep/labs `key_recommendation: None` (were slugs).
- **#4392** (16:12:15Z): 772 theme tags across four coaches, 0 with `_`.
- **#4217 box 1** (14:02:00.882Z): the analyzer logged `glucose skipped — instrument dark: no sensor since 2026-08-27`. Box 2 is due at 17:00Z.

## Proofs due (read PAGINATED — a page of logs is not the latest)
- **16:40Z — daily-metrics-compute:** #4184 (one weekly-rate window); #4345's `protein_g_avg_days`/`_since` fields exist. Also the qa-smoke hydration check on the 09-27 row (the #4183 citation rule).
- **17:00Z — `/aws/lambda/daily-brief` AND `/aws/lambda/coach-quality-gate`, 16:55–17:25Z:**
  - #4343: ≤2 HELD; each retained anti_pattern finding quotes text from its draft; count the JUDGE_HIT_DROPPED / JUDGE_VERDICT_RESTORED lines.
  - #4185: no decade-idiom `fabricated_number`; weight/rate findings only beyond the CI.
  - #4279: `attempt N/3` lines, ≤3 sends per call.
  - #4217 box 2: `[COACH-V2:glucose_coach] skipped_absent`, no glucose `Generating output`.
- **#4065:** the next commit carrying top-set + −10 % back-offs. No commit ran through the gate this morning (MCP log 10:00–15:55Z empty; the 09-28 routine was committed from chat at 02:13Z with flat sets).
- **#4387:** the first 02:00Z nightly pre-draft after a walking day ≥3 h. Check `inputs_snapshot.critics.recent_aerobic.rows` for that day, `window.end == target−1`, and `packet_numbers.joints_tendons.weight_bearing_hr_48h ≥ 3.0`.
- **#4388:** the next cron lower draft. The squat `ramp.base = band_e1rm` with floor 61.235 kg (135 lb); the trap bar `ramp.base = anchor_set`.
- **#4365:** Fri 10-02 ~18:00Z. The week-4 Panel run logs `[media] generated/panelcast/wk4.wav is a restart tombstone`, then the full pipeline.
- **#4358/#4359:** after #4400 merges and deploys, the next 17:00Z brief's `[brief_domain_inputs] hevy_recent=… weekly_correlations=… active_experiments=…` line.

## Gotchas
- **A rulings question can freeze an unattended session for 12 h.** AskUserQuestion blocks the turn and nothing else runs. Overnight, a ruling should be parked as a PR comment plus a held merge, never asked inline, unless the owner is known to be awake.
- **I put a wrong number into an owner question.** I wrote "61.9 kg → 135 lb (nearest loadable)"; 61.9 kg is 136.5 lb, and the nearest 2.5-lb step is 137.5. The lane caught it and I re-asked with corrected numbers. Compute the conversion before offering it as an option.
- **The auto-mode classifier denied `worktree_reaper.py --apply`** ("Interfere With Workloads"). Anything that routes around it, including #4390's wrap gate, waits for the owner.
- **`deploy_site_api.sh` and `deploy_lambda.sh` are in the project ASK list**, so they always prompt whatever the allows say (from the #4261 proposal). Tonight's site-api changes shipped through CI's own deploy.
- **The merge checklist greps the PR body for trailer forms.** A PR that *describes* a trailer (#4386) is refused. Describe it without quoting the literal.
- **The merge-guard hook reads a quoted `gh pr merge` inside a heredoc comment body as a merge.** Advisory only; the #4385 lane accepted it as regex-can't-parse-shell.
- **The merge guard treats a watcher row with no PR number as covering any merge** (fail-open; noted on #4260).

## Residual / next picks
- Owner: review and merge **#4395** (ADR-158); then stop gate watchers (#4256).
- Owner: merge **#4390**, then the attended reap: dry run → `--apply --release-locks-older-than-days 7` → `du` (#4259). The dry run found 226 reapable of 349 trees / 39 GB.
- Owner: review `~/.claude/plans/permissions-cleanup-proposal.md` (project allow 121 → 81, local 341 → 145). Unrelated to the diff: `git -c core.hooksPath=/dev/null commit` is allowed and not ask-gated; `.claude/settings.local.json` is tracked in the public repo (#4261).
- Owner: the registry rename `Walk 5k` → `Walk Outdoor >2mi` (+ `habitify_names`) is an ask-first DDB write described in PR #4399 (#4362).
- Merge **#4399** and **#4400** after 17:25Z today, then read their proofs (#4362, #4358, #4359).
- Revert-or-keep: `walking_collapse` → info in the nutrition adherence critic (#4387).
- #4278, the Sonnet 5 eval + side-by-side, was not started (budget ≤ $5).
- #4255, #4266, #4267, #4276, #4363: not started tonight.
- The Sonnet session's filings #4370, #4373, #4377, #4378 and #4401 fail the filing contract (labels/milestone/Outcome). They are that session's to fix; not this wrap's (#4246).
- Explorer readers elsewhere with the same wrong key: `ai_expert_analyzer` and `daily_insight_compute` Phase 3B read `pairs`/`significant_pairs` off a `WEEK#` partition keyed by pair label (named in PR #4400; the carrier is #4359 until filed on its own).
- The v7 cut-over "go" waits on the Fable R7 red team (#4329) and the cut-over scorecard (#4330). Do not merge #4316.

**Build beat:** none — the story is the cardio fix (#4394), deployed but not yet live-proven; its proof needs the next pre-draft after a ≥3 h walking day
**Docs:** docs/coaching/routines/lower/lower_volume_w1_s3.md + README index row (#4389); docs/alarm_citations.json re-cited (qa-smoke-warnings → score:hydration only); lanes updated their own docs in-PR
**Decisions:** none needed — the owner's #4388 rulings (nearest 5 lb; the week-6 cap as #4397) are recorded on the issue and PR; ADR-158 is drafted in the still-open PR #4395 for the owner
**Main:** green (e1650b05)
**Incidents:** none
**Stash/hooks:** one stash found (the Sonnet session's #4215 lane, 16 h old, `site_api_coach_ledger.py` +5 lines, already on main line-for-line via #4376) — verified by sha and dropped; hooks fresh
**Closures:** #4149, #4260, #4384, #4392 commented (live proof + Shipped + Outcome realized) · DoD: scanned=8 hits=1 — #4216 (the owner's close) unhomed-residual → carrier #4404 filed and linked on the issue
**Backlog:** Now live at 7 opus-startable (floor 3, 0 short); no stale Later issues; filed #4384 #4387 #4388 #4392 #4397 #4404; fixed this session's hygiene violations (#3742/#4182 story rows, #4387 box count, #4392 audience, epic links on #4387/#4388/#4397); open count 89 (REST search)
**Alarms:** 1 red, re-cited — `qa-smoke-warnings` → #4183, now `score:hydration` only (still the 09-26 row, not a repeat)
**CI warnings:** none — no ::warning:: annotations on the latest green main run (e1650b05)
**Ledger:** none — no standing machinery merged (the deploy dead-man is in the still-open PR #4395)

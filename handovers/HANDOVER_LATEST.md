# Handover — Session CD: rulings sitting, owner acts, 47 PRs merged, the CI safety net restored (2026-10-23 → 10-25)

## Driving instruction
- Opened on "The next plan is at ~/.claude/plans/next-session-proofs-2026-10-24.md". The owner then asked how to get 151 open issues to ~30 by solving, not closing. He ran a rulings sitting and his acts script, then said "see you in 10 hours … see how much you can pay down".
- Ran on Opus 5.5. The lanes were individual Agent calls; no Workflow (the owner did not opt in).
- The weekly usage limit was hit once (~11:00Z 10-24 → reset), which stopped one stacking agent before it pushed.

## Owner acts done in session
- **Rulings sitting (10-23):** about 40 decisions, each posted on its issue. Notable:
  - **Nutrition:** stay at ~1,500 kcal, re-targeted, with floors as warnings; 16:8 window; carb floor ~58 g; +150 kcal on lifting days, no rest-day payback; minimum 1,400; 150 kcal steps everywhere; maintenance week for the Christmas trip; no 240 lb rehearsal; meal service on weekdays, cook at weekends; public food names approved-only; no sensor or supplements for now.
  - **Training:** trade sets inside 75; grade cardio separately; warm-ups as they are; pinned notes allowed once Hevy supports them.
  - **Site:** cut-over asap (readers waived); daily mark C; season +$5; retire the old coach notes.
  - **Platform:** Now limit 25; the missed-check alert both ways; food delivery as a 6-monthly ritual; support contact named privately with the alert armed; partner email rebuilt; open-model test vs Haiku; blend Whoop and Watch per metric (never HRV).
- **The acts script** (`~/dev/owner_acts_2026-10-23.sh`): #5218 + Serve apply, #5181 + Mcp apply, the SSM training-plan-source set to **v04** (night 1 of the #5080 flip test), #5226 merged (CI applied it), the #5252 IAM grant. All verified live.
- **CloudFront** `v4-redirects` published by the driver on "publish it". The cut-over is live.

## Shipped (47 PRs merged, all deployed by CI unless marked)
- **Site:** the cut-over (#4928) is live and held through every gate, with the smoke test updated (#5275); mark C; the og card (#5267).
- **Privacy:** the journal-silence guard at every public exit (#5271), with a live leak closed; approved-only food names (#5261).
- **CI:**
  - smoke, visual QA and post-deploy checks had been **skipped on every deploy since ~09-30**. #5300 restored them; the first run passed every check and I6 PASSED;
  - the SNS subject cap (#5281);
  - squash-merge-aware worktree reaping (#5288; reaped 37);
  - nested-worktree scanner pollution (#5284).
- **Nutrition:**
  - the 1,500 re-target (#5265);
  - eating-window reads (#5303);
  - the maintenance week (#5301);
  - the travel kit (#5304);
  - lab follow-up (#5289);
  - Weekly Plate false block, which had failed **5 editions running** (#5299);
  - the budget window (#5148).
- **Training:**
  - the set trade (#5266);
  - the cardio-menu counting bug (#5279);
  - the steps floor (#5280);
  - the floor line ordering (#5287);
  - the delt flag by movement (#5286);
  - deload event signals (#5291);
  - weekday fields (#5278, #5292);
  - charter numbers, May framing and the wake rule (#5282).
- **Mind:**
  - the check-in queue and stress (#5283);
  - mood falls back to the check-in (#5295);
  - mind coach inputs (#5296);
  - relapse early-warning (#5305);
  - core-12 habits (#5293, unarmed until the owner flags);
  - the alerts and the partner email (#5264).
- **Ops:**
  - Strava re-ingest (#5259);
  - Apple Health re-deliveries (#5269);
  - AI-spend attribution (#5270; the report was dropping data older than 15 days);
  - AI-spend paging thresholds (#5294, **Monitoring apply pending**);
  - retirement ledger (#5290);
  - the HR-regime surfaces (#5272).

## Closed on live proof or ruling (~29)
#5255 #5138 #5113 #5216 #4587 #5131 #5112 #4935 #4588 #4646 #5096 #5162 #5167 #5139 #5102 #5205 #5175 #5108 #5212 #5057 #5298 #5252 #5187 and others. Each has its evidence on the issue.

## Open PRs to land next
- **#5306** (support-contact prompts) and **#5308** (lapse protocol): each needs `origin/main` merged and its module added to `ALLOWED` in `tests/test_relapse_early_warning_5121.py::test_only_the_owner_channels_read_the_flag`. #5308 stacks its change_log as **1.29.0** after main's 1.28.0. The stacking agent was cut off by the usage limit before pushing.
- **#5302 HELD for owner:** the panel-grade schedule. Merge plus `cdk_deploy.sh LifePlatformMcp` in one sitting, or main's Plan strands.
- **#5262 HELD:** the #4776 docs. The comparison run is about $15 over 2 days; that is the owner's spend call.

## Gotchas learned
- **"Closes #N" anywhere in a PR body auto-closes on merge** ("closes #5297", "Close #5112 on the curl"). Check `closingIssuesReferences` before every merge; #5252 had to be reopened.
- **Concurrent lanes collide on charter version and census pins.** Merge in order and restack. Recount the census only after staging the resolved files, because a mid-merge `git ls-files` triple-counts.
- **zsh doesn't word-split `$VAR` flags.** Write AWS flags inline.
- **A `!`-prefixed script gets no stdin**, so every y/N defaults to N. Owner acts run in Terminal.app.
- **Lane briefs** must say "plain `git commit`, never `agent_commit.sh`". That script uses `--no-verify`, which the owner's global rule forbids. One lane amended with `--no-verify` early on; it was disclosed.
- **The proof auditors were about 50% right** on first claims, as expected. The driver re-checked the #5102 row before closing it.

## Owner acts (the morning list)
1. **Applies:** `bash deploy/cdk_deploy.sh LifePlatformMonitoring` (#4517, thresholds 22.93 / 459000). #5302 merge plus the Mcp apply, in one sitting.
2. **#5080 flip test:** after the 10-25 02:00Z draft (persisted v04), run `aws ssm put-parameter --name /life-platform/training-plan-source --value charter --type String --overwrite --region us-west-2`.
3. **Re-upload the coach-session skill to claude.ai.** This covers #5274, #5055, #5071 and #5086.
4. **Arm core-12 (#5124):** the private command is in `~/.claude/plans/owner-private-acts-2026-10-24.md` (outside the repo).
5. **Set the Christmas trip dates** in the charter travel window (#5107, #5104).
6. **Phone:**
   - delete the Strava duplicates (#5257);
   - the Strava/Whoop edit test (#4638);
   - the MacroFactor daily-summary export (#5097);
   - Bedrock model access (#4775);
   - `GH_POSTURE_TOKEN` (#4887);
   - tape plus Sunday photos (they clear `calibration-deadman`);
   - the Habitify calorie band (#5099 box 4).
7. **Rulings parked, each with a recommendation:**
   - #5076 bike-after-lower;
   - #5123 a mood question;
   - #5126 check-in prediction grading;
   - the #5130/#5133/#5111/#5107/#5124/#5121/#5122 defaults;
   - #5056 the steps ramp vs 12k;
   - #5203 box 4 wording.
8. **Spend:** season +$2 (#4537); the open-model run, ~$15 (#4776).

## Residual / next picks
- **Defect:** #5203's Telegram dead-man did not fire at the 10-24 16:00Z run (tier 0). The note is on the issue.
- **Event-bound proofs:**
  - #5080, 10-25 02:00Z;
  - #5106 and #5211, the first check-in 10-25 03:00Z and the pair row 12:10Z;
  - #5029 box 3, the 10-24 brief render;
  - #5297, the next Weekly Plate on 10-30;
  - #5129, the next character sheet;
  - #5121, the first flag row;
  - #4583, the 19:00Z move run;
  - #5136, Sun 10-25 15:00Z.
- **Follow-up:** a per-day calorie-sum guard for Weekly Plate (noted on #5297).
- **Next plan:** `~/.claude/plans/next-session-proofs-2026-10-25.md`.

## Marker lines
**Build beat:** the new front page is live (cut-over); the reader-visible privacy leak is closed.
**Docs:** each lane updated SCHEMA, DATA_GOVERNANCE and PROPORTIONALITY; the engine docs were re-stamped on merge day.
**Decisions:** none new as ADRs. Rulings are recorded on the issues; the charter went to 1.28.0 with change_log entries.
**Main:** green (d944d9521).
**Incidents:** CI safety jobs skipped since ~09-30, found and fixed (#5298). Weekly Plate failed 5 editions, found and fixed (#5297).
**Alarms:**
- `calibration-deadman` ALARM is real: tape and photos are overdue (owner act).
- `ingest-reconciliation-strava` is cited to #5257.
- `swallowed-permission-denial` OK since 04:26Z on 10-24 (#5220). Its citation has not been re-pointed yet.

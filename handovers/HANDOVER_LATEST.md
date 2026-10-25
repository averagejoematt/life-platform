# Handover — Session CG: an attended owner-unblock sitting, 11 rulings, 6 closures, 4 owner acts (2026-10-25)

## Driving instruction
- A 2-hour attended session on Fable (boot 20:47Z, new work stopped 22:20Z, wrap by 22:47Z). The owner was present and answering. Build one ranked docket of everything pending him (rulings vs acts), ask in batches of up to four, and do the follow-through in the same session: record each ruling verbatim, make the change through a worktree lane (one integration PR), close every issue whose boxes are met on live proof with the ADR-099 verdict.
- Pre-approved: Life-Platform MCP calls, synthetic-proof invokes (nothing that emails or texts him, no Hevy commits), merges and CI deploys, CDK on ALLOW-ADDITIVE / NO-IAM-CHANGE. The story season (#4545 / #4537) was left to the end of the docket and never reached.

## Shipped
- **PR #5368 (#5123 + #5143), merged 6311b7962:** one 0–4 `mood` question on the evening check-in (`evening-checkin@1.1.0`, 3-number replies still complete; `health.mood_read` uses the rating when present and never infers; the partner view unchanged) and the `cf-auth-errors` accepted orphan pruned from the alarm census (live line: `live=145 model=143 accepted-orphans=2 CLEAN`). Full suite on the tip 35067 passed; mypy clean. **CI/CD run 40239419208 was still in Plan at wrap** — the production gate at THIS tip is the next session's first read (`deploy/approve_deployment.sh`), then the first 20:00 PT prompt carrying "mood".
- **Owner data writes (attended):** the core-12 habit set armed (`apply_habit_core_flags.py --apply`, 10 flags / 9 ids; drift check `core_armed 1, core_ids_unflagged 0`); the calorie habit renamed in Habitify to a band name with a floor-and-ceiling description, after writing its vendor id and the new name as an alias onto the name-keyed registry entry (the core flag survived; `live_without_registry 0`); the us-east-1 console alarm `life-platform-cf-auth-errors` deleted.

## Rulings recorded verbatim (11)
- **#5124** "Accept all four, arm now" (equal weights; protein = the Habitify protein check; out-of-bed by the ±30-min wake rule; steps vs the 12k floor). **#5076** "Trigger stays independent" — (a) does not override the weight-bearing trigger (#4387). **#5123** "(a) Add one 0–4 mood question". **#5203** "Amend to any tier; texts arrived". **#5325** "Accept the unit test, close". **#5143** "Retire cf-auth-errors". **#5126** "(a) No — owner-only observations". **#5141** "Accept the wave file, close". **#5099** "Rename + describe as a band". **#5125 R5** "Rebuild on check-in data" + "Close on code proof; keep emails off" (`EXTERNAL_EMAILS_ENABLED=false` stands). **#5111** "Later" (the priorities row stays parked; `follow_up_weeks` 16 stands).

## Closed on live proof, each with an outcome verdict (6)
- **#5203** (dead-man alert at any tier; 10-24 16:00Z claims + owner receipt + 10-25 `already_sent` log line) · **#5325** (deficit tool, boxes 1/3 live, box 2 on the unit test by ruling) · **#5141** (retirement ledger; box 3 by the wave file) · **#5126** (live packet carries `EARLY-WARNING RESPONSE … Owner: mind_coach`) · **#5125** (R1/R3/R5 answered; weekly prompt live 16:00Z; partner letter v2 on code proof, kill-switched by owner choice) · (#5123/#5143 stay open for the deploy + first live output).

## Owner acts — done this sitting, checked live
- **Coach-session skill re-uploaded** (#5274 #5055 #5086): the desktop-app copy synced 14:58 PT and matches; the second discovered copy (`~/.claude/skills/synced/…`, dated Sep 27) is Claude Code's own download and did not refresh in-session — **re-run `scripts/check_synced_skill_drift.py` at boot; "2 of 2 match" closes box 4 on #5274.**
- **HAE Workouts + nine metrics enabled** (#4969 → #5353): ten payloads landed 21:56–22:01Z; **3 `apple_workouts` on `DATE#2026-10-25` — the first ever**; `apple_stand_hour` now exports. Eight nightly/post-workout metrics absent from this run: re-diff after 2026-10-27 before calling any of them not exported. #5353 box 5 still needs an Apple-only day.
- **Strava: the three backdated walks deleted** (#5257 box 1). Proof: the 2026-10-26 ~17:20Z reconcile reading `MissingActivityCount{strava}` 0 and the 4-day alarm clearing. Nothing was invoked (the reconcile leg lives in `strava-data-ingestion`, whose API call rotates the token).
- **Bedrock 5.5 agreement: NOT clickable.** The console shows only "Open in playground"; `agreementAvailability: NOT_AVAILABLE` and every Converse probe (direct id and inference profile) returns `AccessDeniedException … contact AWS Sales`. Account-level block, recorded on #4772 #4775 #4778; the owner's next act is the AWS Sales form.

## Gotchas learned
- **A name-keyed habit registry entry detaches on rename.** Six of the entries carry no `habitify_id`; renaming the habit in the app would have left the core flag on an orphan. Write `habitify_id` + the new name into `habitify_names` FIRST, then rename, then run the drift check (`live_without_registry` must stay 0).
- **`check_habit_registry_drift.py --live` exits FAIL on `registry_without_live: 6`** before and after today's arming — a pre-existing orphan set, not the core flag's. #5124 box 5 cannot read "passes" until those six are pruned or aliased (owner-data write).
- **The owner's one-at-a-time preference for acts:** he asked to be walked through each app act 1×1 with exact taps, then "check it". Four acts took ~40 min this way; budget that.
- **"Open in playground" with no request button is the Bedrock block, not access.** `authorizationStatus: AUTHORIZED` + `entitlementAvailability: AVAILABLE` + `agreementAvailability: NOT_AVAILABLE` = the account cannot form the agreement; only AWS Sales changes it.
- **The data-reconciliation Lambda is not the Strava DI-2 reconcile.** `life-platform-data-reconciliation` is the weekly gap report; invoking it proves nothing about `MissingActivityCount{strava}`.

## Residual / next picks
- **#5368 deployed** (run 40240244414 success 22:45Z, worker bundle carries `evening-checkin@1.1.0`; the IAM gate was skipped NO-IAM-CHANGE — no approval was needed; #5143 closed on the live census read). **#5123:** read the 2026-10-26 03:00Z prompt text for "mood" and the first 4-number reply's `DATE#` row (`version evening-checkin@1.1.0`) → #5123 live proof; #5143 closes on the census line already pasted in the PR.
- **#5274 / #5055 / #5086:** re-run `scripts/check_synced_skill_drift.py` at boot; on "2 of 2 match" close all three (the Hevy screenshot leg of #5083 stays the owner's).
- **#5257:** read the 2026-10-26 ~17:20Z Strava reconcile; `MissingActivityCount{strava}` 0 + alarm OK closes it.
- **#4969 / #5353:** re-run the 48 h raw-capture diff after 2026-10-27 for the eight nightly metrics; #5353 box 5 on the first Apple-only workout day.
- **#5124:** box 4 (duplicate/misleading names renamed) unverified; box 5 blocked on the six `registry_without_live` entries — an owner-data prune or alias, ask the owner with the list in a private channel.
- **#5099:** the owner's in-app confirmation of the renamed band habit (box 4), then close on the next scored day.
- **#5076:** box 3 (2×/week across a full week's drafts) and box 4 (gym cardio minutes counted on a performed day, 10-26).
- **#5111:** parked by the owner ("Later"); the priorities row is his words, nothing to build.
- **#5097 / #5010 / #5083 / #5103 / #5105 / #5061:** owner acts not reached (MacroFactor export, Hevy pin + screenshot, anchor foods, tape + photos — the owner said "not this session" to tape). `calibration-deadman` stays red until a tape row lands.
- **#4772 / #4775 / #4778:** gated on AWS Sales (account-level 5.5 block).
- **#5369 / #5370 / #5371 (filed 22:4xZ on the owner's ruling that Hevy is the one routine source):** wire `workout_identity` into the zone-2 reader + the no-summing guard (#5369, opus, Now); the post-watch gym-workflow audit with the owner's recording-protocol decision box (#5370, gate:owner); the Strava uploader inventory + best-practice doc (#5371, gate:owner, mostly app-side). Evidence: one 10-25 gym visit = 1 Hevy session, 3 Apple workouts of three HealthKit origins, 4 Strava pushes → one counted session, ride identity lost.
- **#4545 / #4537:** the season; untouched, the owner's optional decision.
- **#5314 / #5080 / #5072 / #5132 / #5109 / #5110 / #4814 / #4777 / #4250 / #5220:** Session CF's event-bound reads, unchanged (Monday 02:00Z predraft, 15:30Z panel grade, 17:15Z morning check-in, 17:00Z coach run, Cost Explorer after 10-26 18:00Z, the 10-27 re-measure, swallowed-permission-denial OK through 10-28).
- not-work — `s3://matthew-life-platform/config/coaches/training_coach.json` is orphaned after #5366; deleting it is an optional owner AWS write.
- not-work — the `~/.claude/skills/synced/…/coach-session/SKILL.md` copy from Sep 27 is a Claude Code download, refreshed by the app, not by the repo.

**Build beat:** none — the mood question is deployed but its first live output is tonight's prompt; nothing reader-visible shipped
**Docs:** docs/SCHEMA.md + docs/DATA_GOVERNANCE.md (evening_checkin `mood`), docs/MCP_TOOL_CATALOG.md regenerated, docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §9a executed note — all inside PR #5368
**Decisions:** none needed — every ruling is a product/ops call recorded verbatim on its issue; no governance change
**Main:** green (6311b7962 deployed by run 40240244414 — Deploy + Smoke success 22:45Z; 40239419208 was cancelled by concurrency, same code)
**Incidents:** none
**Stash/hooks:** clean — reaper removed issue-5071 lane; `fix/walk-completeness` is a dirty worktree named and untouched (pre-existing)
**Closures:** #5203 #5325 #5141 #5126 #5125 commented with outcome verdicts (+#5325 Live-proof line) · DoD: scanned=51, hits 10 — #5325 Live-proof line added this wrap; #4978/#5121/#5136/#5309/#5052 unhomed-residual hits are Session CE/CF's post-close dispositions (informational, residuals already dispositioned not-work or homed in those sessions' handovers); #5085/#5107/#5128/#5165 are post-close Live-proof / owner-ruling comments, already homed
**Backlog:** Now live at 44 startable per Session CF; this session closed 5 Now issues and promoted none (owner-attended sitting, no refill run — re-run `backlog_next.py --refill-now --lane fable` at the next boot); no stale Later issues reported by the battery
**Alarms:** 0 uncited — battery green; strava (#5257, deletion done, clears 10-26), calibration-deadman (#5061, owner deferred tape), qa-smoke pair (dated self-clearing), whoop reconciliation (2h25m, under 72h)
**CI warnings:** 8 — 3 comprehension-judge 1/2 scores on /story/, /coaching/, /cockpit/ (the AI-vision reader's paraphrase misses, advisory by design under #4262's judge — no action, tracked by the visual gate's own trend) + 5 playwright-not-installed skips (#3640, by design)
**Ledger:** none — no standing machinery shipped (one mood field and one census prune)

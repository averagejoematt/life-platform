# Handover — Session BK: Session BJ's work landed, a five-day compute outage found and fixed, and the post-deploy steps done (2026-10-09 → 10-10 ~04:50Z, Opus 5.5, owner on hand)

**Driving instruction:** continue Session BJ (`~/.claude/plans/next-session-prompt.md`). The owner said "anything that should be fable leave — but everything you can do with opus or below, continue", then "merge them" twice. Red-team rounds, the daily-mark ruling (#4646) and the front-page redesign were left for a Fable session. A backlog-paydown session ran beside Session BJ and has exited; its report is folded in below and in `project_session_bj_paydown_2026_10_04.md`.

## Shipped — ten PRs merged, one at a time, each checked against the new main first
- **#4669** (#4580): Session BJ's seven lanes as one squash, `461635c47`.
  - The lanes: verdict rules (#4647), honest cost plus `/api/receipts` `typical_day`/`high_days` (#4650), next-day call targets (#4618), the day page's coach lines and settled calls plus the new `/api/coach_moves` (#4648), plain-word coach lists (#4649), narrow edition readers (#4607), and loud AI-check skips with `ci` in the governor projection (#4652).
  - The seven lane PRs (#4656–#4661, #4665) were closed as landed-through.
- **#4691** (#4672): a coach's forecast line names the day the forecast is for. Fixed with a sibling module, `ai/forecast_prompt.py`, because `ai_calls.py` is at its size ceiling. COACH_STANCE.md was re-verified.
- **#4693** (#4549): the Story Desk promote gate fails closed on an audit that is missing or tied to a different hash.
- **#4695** (#4541): a count claim is graded by counting, never by slope (`coach/prediction_count_grader.py`). The re-grade is still a dry run.
- **#4696** (#4648): live schema baselines for `/api/coach_moves`, `/api/receipts` and `/api/coach/`.
  - `/api/coach_moves` leaves both pending lists and is declared a `?date=` route, held from the public archive until the owner rules on #4615.
  - `capture_api_schemas.py --only` now reaches a prefix route.
- **#4697** (#4635, reader side): `/api/sleep_detail` and `/api/sleep_correlations` leave a night Eight Sleep flags `vendor_incomplete` out of every average. A missing flag reads as unknown and behaves as before.
- **#4698** (#4673): a dated coach claim that cites an instrument that was dark on its date is not quoted. It is replaced by an `unsourced` note on the docket, calls, coach pages and coaches list (`web/claim_sourcing.py`).
- **#4699** (#4607): narrow edition readers for nutrition and training, and a trimmed dashboard. Local measurement: upstream CPU −29%.
- **#4700** (#4671): the kit page fixtures re-captured in one pass. They now agree at 56 of 131, and a cross-fixture test holds that.
- **#4706** (#4704, P1): `daily-metrics-compute` no longer crashes on a string-typed habit-registry number. The character sheet counts and lists an undated earned badge. SCORING.md was re-verified.

Deploys: CI/CD `161265885` deployed everything through #4698. The `0b4489498` run carries #4699, #4700 and #4706 from the last deployed base, and was in flight at wrap. The site deploy for `#4669` was re-run once `/api/coach_moves` answered 200, and passed smoke and visual QA. The site deploy for #4706 was in flight at wrap.

## Verified
- `/api/coach_moves`, `/api/receipts`, `/api/coach/mind_coach` and `/api/edition` answer 200 live.
- `/api/edition`, after #4669, measured over 20 cache-busted requests: p50 1.93 s, p95 1.98 s. The target is 1.5 s, so it misses. The per-upstream table is posted on #4607; nutrition, dashboard, session and training are the slowest. #4699 aims at that; re-measure after it deploys.
- The compute outage was confirmed in CloudWatch: `TypeError` in `scoring_engine.score_habits_registry` from 2026-10-05T00:00:43Z.
- A read-only `get_item` showed two `habit_registry` entries with `target_frequency` `{"S": "7"}` / `{"S": "5"}`.
- The key-rotator failure was confirmed in its log: `AccessDenied` on `secretsmanager:UpdateSecretVersionStage`, 25 retries on one AWSPENDING token. `describe-secret` shows AWSCURRENT unchanged since 2026-07-06.
- PR CI: every merged PR was asserted green with `scripts/assert_pr_green.py` immediately before its merge. #4700 was merged with main locally and re-tested twice (JS 751/751, kit gate clean, full Python suite 31,702 passed, with only the four live-IAM tests and two environment flakes failing) before it went in.

## Gotchas
- **An alarm can be red for five days and nobody looks.** `compute-pipeline-stale`, both ingestion-DLQ alarms (they are `daily-metrics-compute`'s DeadLetterConfig) and the QA smoke's `score:day_grade` all carried the outage. The boot pre-flight names no red alarm, so it surfaced only at a wrap. The class tracker for that gap is #4709.
- **A hand-edited DynamoDB config is untyped.** The habit registry was edited by hand on 10-04 and two numbers went in as strings. Read every profile number through a coercing reader, never `meta.get(...)` straight into a comparison.
- **Two green PRs can still red main together.** #4700's sheet test pinned "the undated badge is not listed", and #4706 deliberately lists it. Neither PR's CI could see the other. Merging main into the second PR locally and re-running the JS tests caught it before merge.
- **Dropping a schema exemption can trip a different gate.** The public-archive gate derives its route set from the same `_exemptions.json`, so removing `/api/coach_moves` there made the archive gate demand it. The route had to be declared in `PARAMETERISED_ROUTES` with a reason pointing at the owner's pending ruling.
- **`capture_api_schemas.py --only /api/coach/` failed before #4696.** The `--only` normalizer stripped the trailing slash that marks a prefix route.
- **A merge decided by `gh pr merge` is not a deploy.** A superseded CI/CD run is cancelled, but the next run deploys from the last deployed SHA (#4472), so nothing is stranded. Read the run, not the merge.
- **`main` went red once on a flaky external lookup.** `test_experiment_library_citations_1983` got HTTP 429 from a citation host. It is not code; the next run was green.

## Residual / next picks
- **#4704** (owner):
  - Correct the two string-typed `target_frequency` values in the profile's `habit_registry` to numbers.
  - Back-fill `daily-metrics-compute` for 2026-10-04 to today, respecting #4637's trailing windows.
  - Live proof is a clean scheduled run, `day_grade_score` on the new rows, and `BADGE#lost_20` with an `earned_date`. The commands are on PR #4706.
- **#4707**: merge PR #4708 (one IAM action plus a set test). Then the owner runs `bash deploy/cdk_deploy.sh LifePlatformOperational` (additive IAM is owner-required), then waits for the 2026-10-10 16:59 PT retry or runs `aws secretsmanager rotate-secret --secret-id life-platform/mcp-api-key`. Do not hand-remove AWSPENDING. Re-sync the local bridge's `.config.json` after the rotation.
- **#4607**: re-measure `/api/edition` (20 cache-busted requests plus the `upstream_ms` table) once #4699 is deployed. If p95 is still over 1.5 s, the session reader is the next narrow reader, or the owner rules on a memory bump.
- **#4618**: `python3 scripts/regrade_tomorrow_calls_4618.py --apply` is the owner's write (dry-run again first).
- **#4541**: `python3 scripts/regrade_count_claims_4541.py --apply` is the owner's write (dry run: one mind_coach call goes from confirmed to refuted; the record moves 8/18 → 7/18).
- **#4652**: the owner confirms the October forecast moving from about $222 to about $256 once `ci` is counted. Read `/life-platform/budget-breakdown` after a governor run.
- **#4635**: the owner runs `deploy/repair_vendor_flags_4635.py --apply` and rules on re-fetching Eight Sleep nights. Until the repair runs, the reader from #4697 sees no flags on old rows.
- **#4701**, **#4702**: the two gaps #4698 left (`/api/predictions` and two more `claim_natural` readers; and the hold decided by gap intervals instead of current liveness).
- **#4709**: the boot pre-flight names every alarm in ALARM and its red duration; this is the procedure fix for tonight's incident class.
- **#4703**: `/api/weekly_priority` serves null because the held synthesis left no record once the 8-day TTL ran out.
- **#4705**: Lisa Park's `coach_moves` line refers to herself in the third person; carry #4564's self-name rule to that generator.
- **#4671**: close on the merged head's CI run (PR #4700). Three live problems it found are now #4703, #4704 and #4705.
- **#4648**: "a day with coach lines shows them" is now held by the live 2026-10-07 capture.
- **#4615**: the owner rules on `/api/owner_words` and `/api/coach_moves` joining the public archive.
- **#4189**: `deploy/api_deploy_sequencing.json` still lists `/api/morning_note` as pending deploy, but it answers 200 live. Its own lane removes the entry.
- **#4675**, **#4674**, **#4676**: as filed. #4676 needs the owner's yes for an S3 upload.
- **#4646**: the owner's words on the four daily-mark drawings (Fable lane).
- **#4584**, **#4585**, **#4617**, **#4604**, **#4644**: the owner's note, the back-fill, the conditional-calls ruling, the nine appendix pages, and the sweep docket. **#4645** merges only on the owner's say-so.
- **#4678**: PR #4679 (the Story Desk streak counts cardio days) waits on the owner choosing (a) merge as is, (b) relabel the count as active days, or (c) change it from next season. Its worktree stays.
- **#4637**, **#4631**, **#4677**: the paydown session's owner writes. Recompute the 2026-09-27 row; re-enrich the one journal entry, then migrate the old keys; optional vocal back-fill. The commands are on each issue.
- **#4538**: the owner rules on the unlisted post `/journal/posts/week-02/`. Recap cards are not on the shared story count check yet (reader side).
- **#4540**: the owner rules on the 180 g protein floor.
- **#4250**: the box-5 check is due on or after 2026-10-27.
- **#4259**: proof is a boot worktree count under 20. The reaper took it from 31 to 18 at this wrap.
- not-work — a Fable session takes the red-team round (render from the refreshed fixtures, #4671 done), the front page's open-disagreement lead (#4583's `MOVES#` rows feed it) and the daily mark; the next-session prompt at `~/.claude/plans/next-session-prompt.md` still holds.
- not-work — MEMORY.md was trimmed from 22.3 KB to 14.8 KB. The tooling lines moved to `INDEX_working_tools.md`, sessions AZ→BH moved to the shipped archive, and a backup sits at `~/.claude/plans/MEMORY.md.bak-2026-10-09`.

**Build beat:** none — the merged work is preview-page and pipeline plumbing behind `/next/v8/`, with no reader-facing launch to narrate yet
**Docs:** docs/alarm_citations.json (five entries re-cited to live causes); docs/INCIDENT_LOG.md (one row, Patterns regenerated); docs/engines/COACH_STANCE.md and docs/engines/SCORING.md re-verified inside their lanes; docs/SCHEMA.md (the `vendor_incomplete` reader rule, #4697)
**Decisions:** none needed — no governance rule moved; the archive hold on `/api/coach_moves` defers to the owner's pending #4615 ruling
**Main:** green (16126588) — the run for HEAD `0b448949` (carrying #4699, #4700, #4706) was in flight at wrap; one earlier red was an external HTTP 429 in `test_experiment_library_citations_1983`, cleared by the next run
**Incidents:** 1 row added — daily-metrics-compute crashed every run 2026-10-05 → 10-10 on a string-typed habit-registry number (P2, ~5 days to detect)
**Stash/hooks:** clean
**Closures:** none — no issues closed this session (every PR carried `Refs`) · DoD: scanned 0, hits 0
**Backlog:** Now live at 20 for the opus lane (floor 3); no stale Later issues; filed #4701–#4705, #4707 and #4709 (the boot red-alarm tracker)
**Alarms:** 5 entries re-cited to live causes — compute-pipeline-stale, qa-smoke-failures and both ingestion-DLQ alarms to #4704; key-rotator-errors to #4707
**CI warnings:** unverified — the latest main run was still in flight at wrap
**Ledger:** none — no standing machinery shipped (one set test on the key rotator's grants rides PR #4708, unmerged)

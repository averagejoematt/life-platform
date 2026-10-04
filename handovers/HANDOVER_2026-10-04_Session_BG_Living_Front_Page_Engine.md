# Handover — Session BG: the living front page's engine landed and four candidate pages are on preview (2026-10-04 04:37Z → ~10:00Z, Fable 5.1, overnight, owner asleep)

**Driving instruction:** the owner's overnight prompt for epic #4580: wait for Session BF's wrap; confirm #4578 and #4592 landed (finish them if not); run #4583, #4584, #4585 and #4589 as background lanes; build all four pages on the preview path from the kit and `/api/edition` as candidates (no cut-over, the live front page untouched); file the scorecard story; leave a morning note and wrap. Merges and deploys for these stories were approved; other AWS writes were to be listed, not made.

## Shipped: 5 PRs merged, all deployed (main green at 11f525bd)
- **#4592** → #4582: `GET /api/edition`, the front page's one composed document (one Pacific `as_of`, one `day_n`, ten blocks, each with state / as_of / source / an absence sentence / data). Finished at the merge checklist: registered in the week-agreement registry as a compared surface; the test's capture pins named for what they are; names through `persona_registry.plain_name`.
- **#4597** → #4583: the daily coach line is a move. `coach-daily-reflection` builds one fact sheet, one call casts at most three speakers, one short call per speaker, and code refuses a numbers-only line or a value not on the sheet; two opposed lines open a docket bet. Stored at `COACH#eli_marsh / MOVES#{date}`, served as `/api/coaching-dashboard` `moves`. Added cost about 0.75 USD a month typical, 1.40 worst case.
- **#4598** → #4589: long coach narratives go to Monday and Thursday (`lambdas/coach/narrative_cadence.py`); the two AI judges in CI run only on reader-surface diffs (`scripts/reader_surface.py`); a workstation's Bedrock calls are labelled `dev-session`. The October 1–2 jump is attributed on the issue.
- **#4599** → #4585: the coaches' record never appears alone. A "nothing changes" rule is scored at grading time; `/api/predictions`, `/api/calibration`, `/api/coaches`, the coach report card and `/api/wrong` serve a `comparison` block; a set guard holds every site module that prints a coach count.
- **#4600** → #4586: four candidate pages at `/next/v8/` (front page), `/next/v8/start/`, `/next/v8/story/`, `/next/v8/coaches/`, built from `clean.css` and one script (`site/assets/js/ck_pages.js`); the edition's `coach_lines` serves the day's moves when a current day exists; `tests/kit_page_gate.py` holds the phone-height budget on the PR.
- **CDK `LifePlatformCompute`** deployed from main at 08:17Z for #4597: the reflection job's timeout 180 → 300 s and one read-only `ssm:GetParameter` grant on `/life-platform/experiment-cycle`.
- **#4595 filed** (Next): the whole-life scorecard by written rule, the second-release story for the block `/api/edition` serves as not built.

## Verified live
- `/api/coaches` carries no "Dr." (05:56Z) — #4578.
- `/api/edition` (07:55Z, then again through the pages at 09:46Z): `as_of` 2026-10-04, day 29; 311.0 lb, −16.3 since September 6; "41 of 96 checked calls right. So far they do not beat a simple guess."; scorecard absent; his words stale since September 23.
- `/api/coaching-dashboard` serves `moves` (null: the job's first scheduled run is 19:00 UTC on 10-04).
- `/api/predictions` serves `comparison` with `scored_complete: false`; each coach on `/api/coaches` carries its own block (09:04Z).
- `coach-daily-reflection` timeout reads 300 live; fleet code updated 08:52–08:57Z by CI run 37189661306.
- The four preview pages return 200 and render with live data at 390×844: 3.95, 3.62, 2.84 and 3.96 phone screens, no sideways overflow, no JS error. Screenshots: `~/Desktop/v8-preview-2026-10-04/`.
- The 95-of-96 count on #4585 reproduces from the back-fill's read-only dry run; the #4589 attribution matches `LifePlatform/AI::EstimatedCostUSD` for `CallerClass=dev-session` (13.52 / 15.66 / 1.50 USD on Oct 1 / 2 / 3).

## Held for the owner
- **PR #4596** (#4584, the Tuesday question) is open, reconciled with main and complete, and NOT merged. It adds one EventBridge rule, which epic #4580's rule 5 forbids in this release, and `LifePlatformServe` needs an owner-required deploy (a `Lambda::Permission` and one `PutItem` grant). Merging first would park main's deploy at the IAM gate. To ship before Tuesday 2026-10-06 19:00 PDT: merge, then `bash deploy/cdk_deploy.sh LifePlatformServe -- --require-approval never` from main.
- **The #4585 back-fill** (a DynamoDB write): `python3 scripts/backfill_coach_baseline_4585.py`, then `--apply`.
- **Memory backup to S3** was not run this wrap (an AWS write outside the stories).

## Gotchas
- **An additive IAM grant that rides with a non-IAM change is OWNER-REQUIRED at CI's gate.** #4597's one read-only grant shared its stack with a timeout change; three deploy runs on main failed at Plan (08:01–08:12Z) and nothing deployed until `cdk_deploy.sh LifePlatformCompute` ran from main. The next merge's run then deployed the union.
- **A sibling lane's guard can catch a file it never saw.** #4599's coach-count guard failed `ck_pages.js` only after both were on one tree, and its statistics helper staled `docs/engines/HYPOTHESIS.md`'s verified stamp, which reddened Docs CI on main until #4600 carried the re-verify (about 40 minutes).
- **A new CI step that imports a test helper inherits the helper's whole import graph.** `kit_page_gate.py` first imported `pr_render_gate` and `a11y_audit`; the dark-flag sweep traced both to `boto3`, which the render job does not install. The gate now carries its own static server and axe runner.
- **The served comparison sentence becomes twenty lines on a phone once the back-fill runs** (four records, each with its own clause). The Coaches preview page keeps the edition's one sentence and leaves the record-by-record text on the scorecard; the edition's `record` block needs a short post-back-fill sentence (#4585).
- **The manifest's chapter excerpts are cut mid-sentence after the editor's note**, so Start here shows the code-rendered stats line for weeks 1–3 instead of a sentence.
- **The front page's coach lines are still the older restated text** until the moves job first runs; on 10-04 the page shows three October 3 lines under "today", one of them the eleven-day journal claim #4583 exists to stop.
- **`deploy_site_api.sh` at 06:01Z returned at about 07:55Z.** The bundle built in seconds; the cause of the gap was not established (the suspects are the script's own verify invoke and a permission prompt). CI had already deployed the same sha, so the run was redundant.

## Residual / next picks
- **#4586**: the owner reviews the four candidate pages one screen at a time, top of the front page first; each screen needs his recorded yes. Named gaps are on PR #4600: the kit has no player component, the scorecard section is left out, static first-person copy is draft wording, Coaches sits at 3.96 of 4 screens.
- **#4584**: PR #4596 held on two owner calls (a schedule the epic forbids; an owner-required Serve deploy). Live proof needs a real reply after Tuesday's send.
- **#4583**: live proof — read `MOVES#2026-10-04` after 19:00 UTC, then 14 consecutive days with no unresolved same-day contradiction. Owner calls on the PR: keep or retire the older per-coach reflections; show silent coaches or not.
- **#4585**: the back-fill is the owner's write; the owner rules which reading the rule starts from; then the edition's `record` block gets a short per-record sentence.
- **#4589**: live proofs due — the Tuesday 2026-10-06 off-day brief, the first judge skip on a producer-only deploy, the 14-day projection. Owner calls on the PR: confirm Monday and Thursday; the `qa-level=lean` dial.
- **#4582**: the page-side contract test and a schema baseline capture for `/api/edition` (the dated `_exemptions.json` entry).
- **#4595**: the scorecard by written rule (Next); four owner rulings listed in the issue.
- **#4581**: the kit chart's two SVG labels render at about 7 px on a phone; the preview pages put the end labels under the chart instead.
- **#4587** five real readers and **#4590** the interview — owner-gated, unchanged.
- **#4588**: the cut-over, only after every screen has his yes.
- **#4540**: still the carrier for the protein floor ruling (170 g or 180 g).
- **#4546**: `ALLOWED_SENDERS` does not include the address the Monday questions email is sent to.
- **#4593**: the missed week-4 email and the share kit.
- **#4531**: the first live desk week is Wednesday 2026-10-07 — read `desk_findings_json` before approving.
- not-work — the memory backup to S3 (`aws s3 sync … claude-memory-backup/`): an AWS write outside the stories; run it at the next attended wrap.
- not-work — whether a doctor reviews the plan: only the owner knows; Start here says nothing about it until he does.
- not-work — the S3 delete for the old day-1 photo: an owner AWS write, commands given in Session BF.
- not-work — #4257 (the refill plan's one promotion) is owner-held; it was not promoted.

**Build beat:** none — the front page these pieces serve is still a preview, and the one reader-visible change (the comparison beside each coach count) reads its full form only after the owner's back-fill
**Docs:** docs/PROPORTIONALITY.md (the kit page gate row, this wrap); docs/engines/HYPOTHESIS.md re-verified in #4600; docs/SCHEMA.md, docs/CONVENTIONS.md §9, docs/PROPORTIONALITY.md and docs/qa/SURFACE_DRIFT_EXEMPTIONS.md rode the lane PRs
**Decisions:** none needed — the cadence and gating changes are the owner's stated cuts and carry PROPORTIONALITY rows; no governance rule moved
**Main:** green (11f525bd)
**Incidents:** none — three Plan-red deploy runs (08:01–08:12Z) were the IAM gate working as designed and cleared in 51 minutes; Docs CI was red on main for about 40 minutes
**Stash/hooks:** clean
**Closures:** none — no issues closed this session (every PR used Refs) · DoD: scanned 2, hits 1 (#4330 post-close comment from Session BF, advisory), blocking=none
**Backlog:** Now live (opus 19 startable, sonnet 3, fable 2); #4595 filed to Next; no promotion made — the refill plan's pick, #4257, is owner-held
**Alarms:** all cited — the battery found no uncited alarm red over 72 h and no uncited flap
**CI warnings:** 5 — all `SKIPPED in CI — no playwright/chromium`, #3640's deliberate skip notice; no action
**Ledger:** Kit page gate row added (this wrap); the reader-surface gate row rode #4598

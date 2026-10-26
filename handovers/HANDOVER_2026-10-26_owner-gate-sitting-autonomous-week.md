# Handover — Session CH: the owner gate sitting for an autonomous week, and wave 1 landed (2026-10-26)

## Driving instruction
- Owner, Sun 2026-10-25 evening PT (Fable → Opus 5.5 mid-session), attended: 100 open issues, a week of usage; get the backlog as low as possible, but **rank by what helps him day to day** (Hevy cardio routines, workout dedup, the daily coach conversation) over the site, which only his partner reads. Discussion first, then "GO".
- He walked every owner gate in one sitting so the rest of the week runs unattended. **Pre-approvals for the week of 2026-10-26** (memory `feedback_autonomy_envelope_week_of_2026_10_26`): merge + approve the CI production gate on code-only green tips (empty `closingIssuesReferences`, full suite + mypy on the tip); run additive-only CDK myself (`deploy/cdk_deploy.sh` when the IAM gate reads ALLOW-ADDITIVE / NO-IAM-CHANGE); synthetic proof invokes (never anything that messages him, never a Hevy commit).

## Shipped
- **PR #5383 (squash 3ead5f4ee) — wave 1, six lanes, deployed by CI/CD run 40263440771 (Deploy + Smoke + post-deploy I1/I2/I5 + visual QA success 2026-10-26T04:25Z):**
  - #5374 wrist-clock cardio rule lines for every kind × machine; his own shape notes parse back (the 10-25 ride no longer reads "level 18"); `HILL_STEP_MINUTES` 3 → 2 (lane PR #5377).
  - #5372 the carry programmed under the template he logs (`farmers_walk`, 50C613D0), `farmers_carry` retired with a `RETIRED_KEYS` alias, carries reported as load + steps, distance/timed sets grade `rpe_absent` (#5378).
  - #5369 + #5353 + the #5371 backstop: zone-2 resolves through `workout_identity` (mobility family, Whoop as 4th source, Strava seam first, HealthKit-origin Hevy/pliability fold), walking + recent-aerobic read watch-only workouts, guard test (gate census 818 → 819) (#5381).
  - #5097 MacroFactor: Excel-serial dates in any CSV, per-metric files merge as `summary_partial`, multi-sheet XLSX joined (#5379).
  - #5124 / #5099 / #5376: six retired supplement bridge keys removed, the titration rewrites the Habitify band description when the band moves (Secrets Manager read grant ALLOW-ADDITIVE on both MCP roles), creatine dose dated 5 g → 10 g from 2026-10-26 (#5380).
  - #5103/#5105/#5110: the weekly menu plans around a fixed meal-service dinner read from the owner-only twin (`fixed_meals`) (#5375).
- **Verified by content:** 12 `deploy/verify_deployed_symbol.sh` checks OK across `life-platform-mcp`, `life-platform-mcp-warmer`, `hevy-routine-cron`, `macrofactor-data-ingestion`, `dropbox-poll`, `habitify-data-ingestion`; the Habitify grant read back from both live role policies.
- **Owner data (attended, backed up first):** six orphan supplement entries pruned from `PROFILE#v1.habit_registry` (backup `~/.claude/plans/session-ch-2026-10-26/`); the Habitify "Calories in band" description now states this week's band; owner-only charter twin `config/coaching/training_charter.private.json` created with `anchor_foods` (20, from his MacroFactor log + salmon) and `fixed_meals` (one Fuller dinner, placeholder = first container label); `PRIORITIES#current` written from the owner-approved lab red team (583 chars, renders in the live packet); two coach-context platform memories (the Fuller experiment, creatine 10 g).
- **GitHub (101 ops, 0 failed):** rulings recorded verbatim on #5370 #5371 #5124 #5135 #5111 #5103 #5105 #5110 #5099; owner amendments applied to #5374 (three numbers, not three levels) #5372 (load + steps) #5371 (box 1 from raw S3) #5370 (split decision boxes); board: site/Story Desk → Later, Claude 5.5 stories → Later, #4776 → Now. Filed #5376 (dated creatine dose) and #5384 (incident class tracker).

## Closed (each with an outcome verdict)
- #5274 #5055 #5086 (synced skill 2/2 + the skill rules) · #5072 (first non-degraded weekly panel grade) · #5080 (owner skipped the flip; grant live) · #5111 (lab priorities live in the packet) · #5124 (`HABIT-REGISTRY-DRIFT: OK` on main).

## Gotchas learned
- **The reconcile child hands the deploy to its parent.** After a merge, the bot's `[skip-reconcile]` commit mints a second CI/CD run whose Plan defers the deploy to the merge run (#4250). Rejecting the merge run as "an ancestor of main" (land §3) strands the merge green-and-undeployed. Approve the parent; the land skill now says so (#5384 builds the structural guard). Incident row 2026-10-26.
- **zsh `path` is PATH.** A `while read fn path sym` loop clobbered PATH and every command "failed". Never name a shell variable `path` here.
- **gitleaks scans the PR's whole commit range.** A Secrets-Manager field-NAME constant (`SECRET_FIELD = "habitify_api_key_v2"`) trips `generic-api-key`; fixing it in a later commit does not clear the range. Read the field inline (`.get("…")`, as `habitify_lambda` does); if one slips in, rebuild the PR as one squash on main (#5382 → #5383), never force-push or allowlist.
- **Never inventory Strava uploaders through the API** (the token refresh rotates the secret): the raw S3 rows carry `device_name` under `{"raw": {"activities": [...]}}`.
- **MacroFactor's Granular Export** wrote one CSV for one metric with Excel-serial dates; the lane had assumed a multi-sheet XLSX. Read the real file (Dropbox `/life-platform/processed/`, read-only refresh-token flow) before designing a parser.
- **`write_platform_memory` coach domains** are `explorer, glucose, labs, mind, nutrition, physical, sleep` (no `training`).
- **The lab-priorities seam truncates at 600 chars** (`training.lab_priorities.MAX_CHARS`); condense before writing.

## Residual / next picks
- **#5373** carry conventions (steps × watch stride, total vs per-hand load) — opus lane, now unblocked by #5372; its Set gained `vacation_fund._hevy_miles`, `health/tdee.py`, `panel_rubric._set_line`.
- **#5370** gym-workflow audit doc (both decisions ruled) and **#5371** Strava best-practices doc + 7-day live proof (from 2026-10-26: no WHOOP-device rows on a gym day, watch rows present).
- **#5135** the $60/month dev AI cap + 80% alarm (additive CDK, pre-approved) · **#5122** disruption playbook (box needs ONE owner toggle) · **#4776** open-model trial (DeepSeek V3.2 / Qwen3 / Nova / gpt-oss callable; per-model IAM grants are additive CDK, pre-approved; baseline Haiku 4.5, not 5.5).
- **#5384** the reject guard + the stranded-shape dead-man line.
- **Proofs on events:** #5374 (Tue 10-27 02:00Z predraft line 1) · #5372 (next carry session's adherence) · #5369 box 4 (sessions read or the first Zone-2 ride) · #5353 box 5 (first Apple-only day) · #5376 (first ingested creatine day) · #5099 (first band move, Friday-night write) · #5103/#5105/#5110 (Sat 10-31 menu; offline: 5/7 days fit, the two rest days over band) · #5297 (Weekly Plate, Sat 10-31 02:00Z) · #5324 (Nutrition Review, Sat 10-31 17:00Z) · #5123 (tonight's 03:00Z mood prompt + first 4-number reply) · #5132 (17:15Z morning check-in) · #5257 (17:20Z Strava reconcile) · #5314 (packet RUN GATE line after the 02:00Z predraft) · #4969 (re-diff after 10-27).
- **Owner acts this week:** the four mood numbers tonight; one committed-routine Hevy screenshot (#5083); tape + photos midweek (#5061, #3759); the repeat MacroFactor export, calories file first (#5097, then discard the parked DLQ message); the end-of-week coach-session skill re-upload (#5086 drift until then).
- **#5103** owner question parked: add his logged Fiber Gummies as an anchor to ease the rest-day fibre miss.
- not-work — `docs/SCHEMA.md` lacks a `summary_partial` / `fixed_meals` line (engine-doc stamp gate); fold into the #5097 closer's PR.
- not-work — `fix/walk-completeness` is a dirty pre-existing worktree, reported by the reaper and left untouched.

**Build beat:** none — every change is owner-facing (training engine, ingestion, coach context); nothing reader-visible shipped
**Docs:** `.claude/skills/land/SKILL.md` §3 reconcile carve-out; `docs/INCIDENT_LOG.md` (2 rows + Patterns); `docs/OPERATING_KNOWLEDGE_LEDGER.md` (6 rows); `ledgers/retirement_ledger.py` (2 rows planned → retired, PR #5383)
**Decisions:** none needed — every ruling is a product/ops call recorded verbatim on its issue; the week's pre-approvals are time-boxed and live in memory
**Main:** green (e43171b2)
**Incidents:** 2 rows added — the reconcile-child deploy strand (#5384) and the MacroFactor export DLQ alarms (#5097)
**Stash/hooks:** clean — reaper removed 5 released lanes; `fix/walk-completeness` dirty and untouched (pre-existing)
**Closures:** #5274, #5055, #5086, #5072, #5080, #5111, #5124 commented with outcome verdicts · DoD: scanned=7, hits 1 — #5111 `unhomed-residual` dispositioned in the closing comment (not-work — nothing outstanding); the post-close comment is informational
**Backlog:** Now live at 16 startable (floor 3), no refill needed; no stale Later issues; open 100 → 95
**Alarms:** all red >72h cited — calibration-deadman (#5061, tape deferred), ingest-reconciliation-strava (#5257, clears 10-26 17:20Z), qa-smoke pair, whoop reconciliation (<72h), the two DLQ alarms (#5097)
**CI warnings:** 6 — 5 playwright-not-installed skips (#3640, by design); 1 "Additive IAM diff not offered" on the reconcile run e43171b2 — no action, the merge run 40263440771 applied it at 03:47Z (verified on both live role policies)
**Ledger:** none — no standing machinery shipped (a guard test joined the census; the band-description writer rides the existing titration leg)

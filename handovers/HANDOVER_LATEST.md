# Handover — Session CB: charter follow-ups waves A, B and C merged and deployed; 8 stories closed on live proof, the PR-time IAM gate live (2026-10-21)

## Driving instruction
"Read and execute ~/.claude/plans/next-session-autonomous-proofs-and-followups-2026-10-21.md — autonomous, use a workflow." The driver ran on Opus 5.5 with the owner absent. Each lane ran on its `model:` label through the wave kit, copied to the session scratchpad as `followups-wave.js` (COMMON pointed at the plan, the nutrition RULINGS block kept). Each lane got a build, a review, one fix round and a re-review. Two lanes per workflow, seven workflows in all. There were no AWS writes and no `cdk deploy`, and the budget tier was never forced (it read **2** throughout).

## Phase 0 — the owner had not acted
- #5218 and #5181 are still open. The `telegram-coach-evening-checkin` rule and the `fitness-battery-missed` alarm do not exist.
- There are no answers on R1–R8 (#5091) and no rulings on #5212, #5203, #5205 or #5216.
- No new MacroFactor export since 10-18, and the private charter twin is absent (404).

## Shipped (merged to main, deployed by CI, verified by content with `verify_deployed_symbol.sh`)
- **Wave B — PR #5236 (b8125f043), CI/CD run 39520325828:**
  - #5201: one cardio prescription across pick, block, shape and note.
  - #5202: the three draft display fixes.
  - #5191: a per-date training calendar types each day lifting or rest, so the week averages the base (charter **1.19.0**).
  - #5198: one calorie target on the energy view, with a three-state `model_check` field.
  - Driver tip fixes: the calendar parses day keys through `parse_day_key`, plus a mypy guard.
- **Wave A — PR #5237 (4219cd7df), run 39522551438:**
  - #5200: the May tracker reaches the coach context on every caller path (`coach-context@1.4.0`).
  - #5199: a `NIGHTLY_PREDRAFT_SUMMARY` line is logged first.
  - #5220: the charter loader logs an absent twin as `absent`; a real 403 keeps the `AccessDenied` literal.
  - #5221: a PR-time additive-IAM check, `iam-gate-pr.yml`. It synthesizes the PR against its base and needs no AWS. It is red on OWNER-REQUIRED unless the PR carries the `owner-required-ack` label, which was created this session.
  - Driver tip fix: the steps-truth helper in `coach_context`.
- **Wave C — PR #5246 (496fd9e36), run 39530774449:**
  - #5213: a guard over the whole set of deficit-sustainability callers.
  - #5215: the food panel reads disruption records.
  - #5204: one fibre floor (the driver added the None guard and the '—' footer).
  - #5214: one protein feeding definition (the driver fixed the doc stamp).
  - #5102 follow-up: floor misses reach the deterministic critic output.
  - #5232: the daily brief's TL;DR and Board sections, which failed on every run since 10-04 on a string-typed habit tier. The driver made the read boundary convert only values that parse as numbers, so the #4704 drift report still sees garbage.
  - Driver tip fix: the review email reads through `public_view()` (the #5087 guard), the game page was regenerated, and `COACH_STANCE.md` was re-verified. The census was restacked to 807 gates, with the proven bound at 283.

## Closed on live proof (8)
- #5183: `coach_vs_engine` agrees on the unchanged 10-19 text, and `qa-smoke-failures` is OK.
- #5191: `plan_next_session(10-21)` gives a typed lifting day with `week_balance_held`, and the weekly mean equals the base.
- #5198: a live energy-view read.
- #5200: `coach-context@1.4.0`, `may_tracker: measured`, and `plan_packet`'s absence carries its reason.
- #5199: the 02:01Z warmer summary line.
- #5201 and #5202: the 02:00Z pre-draft `6d8fb73c…` and `SHADOW#2026-10-21`.
- #5213: the guard is green in main's CI, with its mutation proof recorded.

## Partial proofs posted (kept open)
- #5095: the macros tool reads the resolver, but no day has been logged since the deploy.
- #5102: the packet carries the floors. The output gap is fixed in wave C; waiting on a logged below-floor day.
- #5109: the cause is fixed; waiting on a coach refresh, which needs tier ≤1.
- #5221: the first verdicts are red on #5218 (the incident shape) and ALLOW-ADDITIVE on #5226. Its 30-day window runs to **2026-11-20**.
- #5220: the loader is live; the alarm clears only after #5226 is applied.
- #5052, #5057, #5058, #5076 and #5085: tonight's draft. No session has been logged since 10-19.
- #5080: night 2 of 3.
- #5101: the typed day is live.
- #5073: box 4 is live.
- #5204, #5214, #5215 and #5232: deployed, each waiting on its named event.

## Filed
- **#5232 (P2):** the daily-brief TL;DR and Board sections were down since 10-04. It shipped in wave C, and its proof is the next 17:00Z brief.
- **#5247 (P3):** the summary line's double-prefixed stamp, a list logged as a string, a null tracker state, and `constraint_block` missing from the pre-draft's coach context.

## Verified (live reads)
- `slo-ai-coaching-success` is six Bedrock 503s in one 10-19 14:00Z `ai-expert-analyzer` run; the re-alarm recounts the same window. Neither the nutrition waves nor the budget tier caused it.
- The PR-time IAM gate classes the `s3:ListBucket` grant (#5226) as `ALLOW-ADDITIVE` on Compute, Email and Mcp. After merge it can ride CI's IAM deploy path instead of an owner apply.

## Gotchas
- **A lane's local gates are not the full suite.** The wave tips caught four real reds the lane reviews missed: the ISO-parse registry, steps-truth, the #5087 public-view guard and engine-doc drift. Wave B's PR also went red in CI on a mypy union-attr. Run the full suite AND the CI mypy clean set (`python3 -m mypy $(python3 scripts/mypy_clean_set.py)`) on every wave tip before opening its PR.
- **Resolving a census conflict by regex can split a shared tail.** A proof block's closing lines sat outside the conflict hunk. Rebuild `scripts/gate_census_proofs.py` as main's version plus the wave's new blocks, then `ast.parse` it.
- **Don't merge a wave whose deploy lands during the 02:00Z pre-draft.** Wave C was held until the pre-draft logged.
- **The closure sweep reads the closing comment itself.** A residual phrased without a `#N` blocks it; edit the comment, don't add a new one.
- **zsh:** `set -- $a` does not split a loop string either. Call each command explicitly.

## Owner acts (the morning list)
1. **#5218 + `bash deploy/cdk_deploy.sh LifePlatformServe`** in one sitting: the evening check-in rule, its Lambda permission and its write grant. The PR-time gate now reads it red, as it should; add the `owner-required-ack` label when you merge it. If you merge after 2026-10-27, move `EVENING_CHECKIN_ARMED_ON` first.
2. **#5181 + `bash deploy/cdk_deploy.sh LifePlatformMcp`**: the grant, the `fitness-battery-missed` alarm (the CI warning names it), and the SSM flip test (#5080 night 3 lands 10-22).
3. **#5226, the `s3:ListBucket` grant on `config/coaching/`, which quiets `swallowed-permission-denial` (#5220).** The gate reads it ALLOW-ADDITIVE, so merging alone may deploy it through CI's IAM path. Otherwise, the lane's apply line is `bash deploy/cdk_deploy.sh LifePlatformCompute LifePlatformEmail LifePlatformOperational LifePlatformServe LifePlatformMcp`. Writing the private twin is the alternative.
4. **S3 config sync for wave C:** `python3 deploy/config_twin_sync.py`, then `--apply`. It covers `board_of_directors.json`, `character_sheet.json` and `user_goals.json`; until it runs, the panel prompt keeps the old per-meal wording (#5214, #5204).
5. **Retype the two string-typed `habit_registry` fields** in `PROFILE#v1` as numbers; the row ids are in PR #5240's post-merge ops (#5232). The code no longer needs it.
6. **Rulings:**
   - R1–R8 on #5091. Waves B and C rest on the R1/R2 defaults.
   - #5212, #5203, #5205, #5216, #5108 and #5008 C2.
   - From BZ: #5162 and #5167.
7. **Exports:** a MacroFactor daily-summary export (#5097) and the 5 food-plan grades (#5110).

## Residual / next picks
- **Proofs, event-bound:**
  - #5232: the 17:00Z brief has no `TL;DR+Guidance failed` line.
  - #5095 and #5102: the first logged day.
  - #5096: the Friday 10-23 pre-draft titration record.
  - #5080: night 3 on 10-22.
  - #5052, #5057, #5058, #5076 and #5085: the next logged session and draft.
  - #5109: a coach refresh at tier ≤1.
  - #5215: the first disrupted week.
  - #5214 and #5204: after the S3 sync.
  - #5221: its window to 2026-11-20.
  - #5220: after #5226.
- **Filed follow-up:** #5247 (P3).
- **Next lanes (Now, startable):** #5211 and #5187 from Next if promoted; the BZ later-list proofs #5055, #5056, #5072, #5078, #5079, #5083, #5084, #5086 and #5090.
- **Gated:** W3 (#5103, #5104, #5105, #5107, #5112 and #5113) waits on R3–R8. #5075 waits on Fable.
- **Owner-attended CDK:** #5218, #5181 and #5226. not-work — owner-attended IAM/CDK acts, listed under owner acts.

## Marker lines
**Build beat:** none — engine, owner-only nutrition and CI work. The only reader-visible change is the regenerated game page's one config line.
**Docs:**
- The lanes updated CONVENTIONS §4d(2) (the PR-time check), engines/CHARACTER and engines/COACH_STANCE (re-verified), ARCHITECTURE and SCHEMA.
- The wrap added the PROPORTIONALITY row and the two alarm citations.

**Decisions:** none needed. These are follow-ups inside ADR-164's charter-as-data decision and the #2834 gate. The PR-time check's no-`--live` choice is stated in CONVENTIONS §4d(2).
**Main:** green (496fd9e3)
**Incidents:** none. The one PR-time red (wave B mypy) was caught before merge, and main never went red.
**Stash/hooks:** clean
**Closures:** #5183, #5191, #5198, #5199, #5200, #5201, #5202 and #5213 commented. · DoD: scanned 7, hits 1. #5199's residual is homed at #5247 (comment edited). One post-close residual comment was noted, non-blocking.
**Backlog:** Now live at 34 (opus lane, 0 short; no promotion needed). Later sweep: OK, 154 open satisfy the contract.
**Alarms:**
- `slo-ai-coaching-success` is cited as a dated, self-clearing vendor 503 burst (expiry 10-21 17:00Z).
- `life-platform-budget-tier-escalation` is re-cited from closed #2801 to #5135, the dev-session envelope (expiry at the 11-01 rollover).
- `swallowed-permission-denial` stays on #5220.
- All are cited.

**CI warnings:** 6.
- Five are `SKIPPED in CI — no playwright/chromium`, the standing #3640 class: no action.
- One is `LifePlatformMcp has non-IAM CDK changes` (the fitness-battery alarm): owner act 2 (#5181 + the LifePlatformMcp apply).

**Ledger:** PR-time additive-IAM check (#5221) row added.

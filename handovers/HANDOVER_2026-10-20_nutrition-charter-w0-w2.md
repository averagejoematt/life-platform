# Handover — Session CA: the May-2027 nutrition charter built W0→W2 into the one training charter, all merged and deployed; Phase 0 closed two charter stories on the first engine pre-draft (2026-10-20)

## Driving instruction
"Read and execute ~/.claude/plans/next-session-nutrition-charter-opus-2026-10-20.md — use a workflow, Phase 0 then nutrition W0→W2." Opus driver (Fable out for the week). The lanes ran on their `model:` labels through the wave kit (`~/.claude/plans/charter-wave-kit/charter-wave.js`, with nutrition RULINGS/COMMON). Each lane got one review, one fix round and a re-review, and landed in an integration branch per wave. R1–R8 on #5091 were **unanswered**, so W0–W2 are **built on the panel defaults for R1 (eat up to the band now, weekly refit) and R2 (four protein feedings)**, stated on every PR. Nothing touches R5–R8.

## Shipped (merged to main; deployed by CI; verified by content in the deployed bundles)
- **Wave 0 — PR #5190 (6a3ac9e7c):**
  - #5184: the overshoot rule counts the 14-day trend.
  - #5185: MacroFactor expenditure is kept on every export path, and `health/expenditure_reconciler.py` checks it against the scale.
  - #5188: ONE calorie target, `health.calorie_target.resolve()`. The genesis constant now has zero readers, and a guard enforces it.
  - #5186: the protein engine, with ONE hit definition and the breakfast nudge (armed, silent until #5187).
  - Deployed by run 39355044889.
- **Wave 1 — PR #5194 (f730b4e41):**
  - #5192: the fat/carb/fibre floors.
  - #5189: training-day fuel through the resolver.
  - #5193: the weekly titration engine `health/titration.py`, written by the Friday pre-draft leg, with a dead-man armed from 2026-11-03.
- **Wave 2 — PR #5217 (94b69434f), then the Plan unblock PR #5219 (4a39ffc57), then a `deploy_all=true` dispatch (run 39372328618, Deploy success):**
  - #5197: the critics fetch enough weigh-ins.
  - #5195: food_delivery paused reversibly.
  - #5196: lab cadence plus the owner-only priorities seam.
  - #5208: the nutrition coach through `coach_context`; also fixes #5183's real cause, a claim extractor that misassigned from-to pairs.
  - #5206: nine nutrition panel seats, with the negative control failing in the CI golden gate.
  - #5210: the evening check-in and the check-in→intake correlations.
  - #5209: the critics' AI layer in budget band 1.
- **Charter:** `config/training_charter.json` goes from 1.7.0 to **1.18.0**, with ONE top-level `nutrition` block: calories, expenditure, protein, titration, training_day, floors, labs, concession_ledger.
- **Held for the owner:** draft **PR #5218**, holding the evening check-in rule, its `config/schedules.json` row and the worker's `DynamoDBEveningCheckinWrite` grant. All three are owner-required CDK (see Incidents).

## Phase 0 — the training-charter proofs (the 02:00Z 2026-10-20 pre-draft, routine `cfa64b2f…`, the first engine draft)
- **Closed on live proof:** #5000 (gate, cardio cue, green withhold) and #5001 (`rate_ceiling` evaluated and forcing a change).
- **Evidence posted, kept open:**
  - #5058: the draft half is proven; the +1 grading half is pending.
  - #5052: hold and floor_raise reasons are live; no `step` has fired yet.
  - #5076: the dose is present; defects are carried on #5201.
  - #5085: the gate passed.
  - #5071: coach-context@1.2.0 is live in stage 1; the tracker is not supplied (#5200) and the log is truncated (#5199).
  - #5073: the first tracker row exists.
  - #5080: shadow night 1 of 3.
  - #5061: the dead-man fires, but delivery is silenced at budget tier 2 (#5203).
  - #5057: the leg press was not served tonight.
- **Supersession sweep:**
  - #5048 folded onto #5083/#5076.
  - #5000 and #5001 later closed, as above.
  - #5008 kept; its C2 is the owner's call.
  - #5100 narrowed, then closed on proof.

## Verified (live reads, 2026-10-20)
- **The one target:** `get_nutrition view=macros` reports `calorie_target_basis: charter`, and the energy view's `calorie_target_platform` gives the same kcal (#5095 partial; the second "target" figure on the energy view is #5198).
- **Protein agreement:** the macros view, the `protein_floor_missed` tripwire and the critics count the same days. #5003 closed.
- **Overshoot rule:** both critic checkpoints read full 14-day windows. #5100 closed.
- **Titration dry run on live data:** `hold / awaiting_confirmation` (read 1 of 2 over the ceiling), charter 1.16.0 (#5096).
- **Training-day fuel:** `if_lifting_day` 2250 > base 2100 > `if_rest_day` 1725 (#5101; the day is untyped until #5191).
- **Floors and critics:** the critic packet carries the floors (#5102), and the critics' model layer reads `paused, tier 2` (#5114).
- **Bundles:** `verify_deployed_symbol.sh` confirmed the W2 modules in life-platform-mcp, the warmer and telegram-coach-worker.

## Gotchas
- **An EventBridge rule targeting a Lambda is owner-required CDK.** It creates an implicit `AWS::Lambda::Permission`. The W2 merge stranded main's Plan for ~70 min. Run `deploy/iam_additive_gate.py --synth-dir cdk/cdk.out --live` on the PR head before merging anything touching `cdk/` or `config/schedules.json` (CONVENTIONS §4d(2), tracker #5221). The schedule row must move WITH its rule (`test_schedule_table_4284`).
- **A wave squash's tree equals the wave tip.** Merging main into the next wave branch therefore means taking the wave side and regenerating `model/platform_model.json`.
- **zsh:** `for x in $(…)` does not word-split, and a loop variable named `path` clobbers PATH. Use Python, or a `while read` loop with another name.
- **`deploy/agent_commit.sh`** needs explicit paths, plus `ALLOW_DOC_LITERALS=1` for doc-sync files.
- **The budget tier read 2 from 2026-10-20T00:00Z.** Internal AI and reader narratives are paused, and the critics' model layer and the calibration dead-man delivery wait on it. It was never forced.
- **The claude.ai Life-Platform connector needed re-auth.** The local `mcp_bridge` tools worked.

## Behaviour change for the owner
- Every surface now grades against the charter's prescribed calorie target instead of the old genesis constant (panel default R1). Day grades, the character Food pillar and the digest hit rates shift accordingly.
- The public gear/catalogue rows no longer list the paused food-delivery source (#5108, pending his confirmation).

## Owner acts (the morning list)
1. **Merge #5218, then `bash deploy/cdk_deploy.sh LifePlatformServe` in the same sitting.** That applies the evening check-in rule, its Lambda permission and the write grant. If the apply lands after 2026-10-27, move `EVENING_CHECKIN_ARMED_ON` first.
2. **From BZ:** merge #5181, then `bash deploy/cdk_deploy.sh LifePlatformMcp` (grant plus the `fitness-battery-missed` alarm; the CI warning names it), and test the SSM flip.
3. **Rulings:**
   - R1–R8 on #5091; W0–W2 stand on the R1/R2 defaults.
   - #5212: rest-day carbohydrate below the carb floor.
   - #5203: dead-man delivery under the budget tier.
   - #5205: the tripwire's "+150–250" against the 150 step cap.
   - #5216: the critics' cost row.
   - #5108: confirm the food-delivery pause.
   - #5008 C2.
   - From BZ: #5162, #5167.
4. **Exports and data:**
   - One MacroFactor daily-summary export (#5097).
   - Write the private charter twin (also quiets #5220).
   - Grade 5 food plans for the panel calibration (#5110).
   - Optionally, the lab follow-up date and priorities row (#5111).

## Residual / next picks
- **W3 (gated):**
  - #5104 (travel kit, due mid-December) needs R3.
  - #5103, #5105, #5107, #5112 and #5113 wait on R3–R8.
- **Proofs pending (event-bound):**
  - #5095 (the brief grid, emails, character sheet, coach) and #5096 (the first Friday record).
  - #5097 (needs the export).
  - #5098 (the nudge, after #5187).
  - #5101 (#5191), #5102 (a floor-miss verdict) and #5106 (needs #5218 applied).
  - #5109 (the next coach refresh passes qa-smoke `coach_vs_engine`).
  - #5110 (the weekly panel grade) and #5111 (the first reminder).
  - #5114 (a tier-0 run) and #5108 (the owner's confirmation).
- **Training-charter proofs:**
  - #5052, #5057, #5058, #5061, #5071, #5073, #5076, #5080 and #5085.
  - The BZ later list: #5055, #5056, #5072, #5078, #5079, #5083, #5084, #5086, #5090.
- **Follow-ups filed this session:**
  - #5198–#5205.
  - #5207 (carried by the #5212 ruling) and #5211.
  - #5213–#5216.
  - #5220 (the swallowed-denial alarm) and #5221 (the PR-time IAM gate tracker).
- **Lane-filed, brought to the issue contract:** #5187 and #5191.
- **Deferred:** #5075 waits on Fable.
- **Owner-attended:** #5218 + the LifePlatformServe apply, and #5181 + the LifePlatformMcp apply — not-work — owner-attended IAM/CDK acts, listed under owner acts.

## Marker lines
**Build beat:** none — engine and owner-only nutrition work; the only public change is the paused source leaving the catalogue rows, pending the owner's confirmation
**Docs:** the lanes updated SCHEMA, ARCHITECTURE, DATA_GOVERNANCE, PROPORTIONALITY, engines/SCORING, the coaching docs and qa/SURFACE_DRIFT_EXEMPTIONS. The wrap adds the CONVENTIONS §4d(2) pre-merge IAM-gate reflex, the INCIDENT_LOG row, the alarm citation and the operating-knowledge row.
**Decisions:** none needed — nutrition extends the ADR-164 charter-as-data decision into the same file; no new governance choice
**Main:** green (4a39ffc5)
**Incidents:** 1 row added — the W2 merge stranded main's Plan ~70 min on an implicit Lambda::Permission (class tracker #5221; procedure edits: CONVENTIONS §4d(2) and the wave-kit review step)
**Stash/hooks:** clean
**Closures:** #5000 #5001 #5100 #5003 commented (and #5048 folded) · DoD: scanned 4, hits 0
**Backlog:** Now live at 35 actionable in the opus lane (no promotion needed); Later sweep — OK, 158 open satisfy the contract
**Alarms:** `swallowed-permission-denial` re-cited to #5220 (the charter loader's missing-twin 403 on cold starts); `qa-smoke-failures` stays on #5183, whose cause #5208 fixed (pending the next coach refresh); all cited
**CI warnings:** 11. Ten are the `SKIPPED in CI — no playwright/chromium` annotations, the standing #3640 class: no action. One is `LifePlatformMcp has non-IAM CDK changes` (the fitness-battery alarm): owner act 2 (#5181 + LifePlatformMcp apply).
**Ledger:** two rows added by the lanes — the nutrition critics' model layer (#5114) and the evening check-in family (#5106). The titration leg and its dead-man ride the existing nightly pre-draft host.

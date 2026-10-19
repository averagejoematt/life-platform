---
name: training-review
description: "Run Matthew's training block retro: at the end of every training block, re-grade the fixed thirteen-row training scorecard from the block's evidence, compare it with the last retro and name what moved, grade the dated charter predictions that have come due, and turn every grade below B into a named fix. Use when he says \"training review\", \"block retro\", \"re-grade the scorecard\", \"how did the block go\", or when a training block has just ended."
allowed-tools: Read, Glob, Grep, Bash, mcp__life-platform__*, mcp__claude_ai_Claude_Docs__*
---

# Training review: the block retro

The 2026-10-18 elite-panel review graded Matthew's training on thirteen rows with nothing earlier to
compare against. This skill re-grades the SAME thirteen rows once per block, from the platform's own
evidence, and says what moved. It is an owner-only ritual. Every grade, every number and the retro
itself stay private: the stored row is owner-only and the human-readable retro goes into his PRIVATE
review doc, never a public page.

**No hand-copied numbers.** Every training target (the step floor and target, the loss-rate band,
the lifting days, the cardio dose, the calibration cadence, the target date) belongs to the training
charter, `config/training_charter.json`, read through `lambdas/training/training_charter.py`. The
thirteen rows, their inputs and the grade scale belong to `config/training_scorecard.json`. Quote
them from those files or from the tool output. Never restate one from memory or from this file.

**Grading is reproducible.** `lambdas/training/block_retro.py` assembles the evidence and scores
every row it can by code; `scripts/training_block_retro.py` reads the stored rows and runs it. You
read, explain, question and record. You do not count by hand, and you do not change a letter
without a recorded reason.

## When

A block is the charter's `rotation.anchors_fixed_weeks` weeks (`block_model.block_weeks()`); the
retro cadence is the charter's `calibration.block_retro`. The block ends on the Sunday of the
block's last program week: `plan_next_session` (stage 1) shows `block` and `week_in_block`. If the
block end is not clear, ask him for the date; never guess one.

## 1. The baseline and the private doc

The rows are copied into `config/training_scorecard.json`; their 2026-10-18 baseline grades are NOT.
The repo is PUBLIC, so the letters live only in the owner-only baseline row
`training_constraints / RETRO#2026-10-18` (kind `baseline`), which the first retro reads as its prior.
The review they come from is the owner's PRIVATE Claude Doc "Training Review — Day 43 Elite
Panel". Read it ONLY through the Claude Docs tools, and never web-fetch it:

- `mcp__claude_ai_Claude_Docs__read` with ref `{object: project, id: 97f07da3-857f-4e68-8125-69e4ae6b9081}`,
  then the tab body node (engine prose, container `{kind: project, id: 97f07da3-857f-4e68-8125-69e4ae6b9081}`)
  with payload `{projection: outline}` and a `{kind: view, parentId: <the scorecard table id>}`.
- Load the docs guide (`guide(items=["topic.index"])`) before the first docs call of the session.

If the doc's scorecard has rows the config does not, stop and say so. The config changes only as a
new scorecard version with a change_log line, on his word.

**Once, before the first retro: store the baseline.** If `grade` warns that there is no prior row,
read the letters from the doc's scorecard, write them as `{"<row id>": "<letter>"}` to a file in
your session scratchpad (never the repo, never a commit), and run
`python3 scripts/training_block_retro.py baseline --letters <file>` (a dry run that validates every
row and letter). `--apply` writes the row; it is an AWS write, so run it only on his word. It
refuses to overwrite a stored baseline.

## 2. Gather what the platform has not stored

`scripts/training_block_retro.py grade` reads the stored rows itself: the May tracker's `WEEK#`
rows, the weekly `PANEL#` grades (C5's panel rubric, `config/panel_rubric.json`, run on each
week's committed plan), the owner's `DELOAD#` and disruption-mode records, the last `RETRO#` and
the dated charter predictions. Check the latest tracker row with `get_may_tracker` first. If it is
`read_failed` or the block's weeks are missing, say which weeks; do not run the retro over a gap
you have not named.

The counts below come from MCP tools. Put them in a JSON file (`--supplied`). A count you could
not read is LEFT OUT, never written as 0; the retro then shows that input as absent.

```json
{
  "sessions": {"logged": "<Hevy lifting workouts in the block: get_workouts>",
               "distinct_movements": "<distinct movements logged: get_workouts / get_exercise_history>"},
  "sleep": {"nights": "<nights with a sleep record>", "mean_hours": "<mean sleep hours>",
            "consistency": "<0-1, from get_daily_metrics>"},
  "progression": {"steps_taken": "<load steps logged>", "step_due": "<step_due verdicts>",
                  "stalls": "<stall verdicts: get_exercise_history>"},
  "cardio": {"conditioning_sessions": "<menu conditioning blocks logged: get_training / get_workouts>"},
  "planning": {"custom_departures": "<draft_custom commits with a departure_reason>",
               "committed_plans": "<committed routines: manage_hevy_routine>"},
  "deload": {"recommendations": "<days deload_recommendation was active: plan_next_session>"},
  "fitness": {"battery": "<the fitness-test battery record, when one exists>"},
  "anchor_e1rm": {"<anchor>": {"baseline": "<best e1RM on or before the prediction baseline>",
                               "current": "<best e1RM after it, or null>"}},
  "accessory_stalls": {"<movement>": {"scored": "<true if 3+ sessions in the window>",
                                      "stall_runs": "<stall verdicts over 3 consecutive sessions>"}}
}
```

`anchor_e1rm` and `accessory_stalls` feed the dated predictions only. Supply EVERY anchor lift (the
families in the last May tracker row's `anchors`): a lift you leave out makes the anchor
prediction `inconclusive`, naming it, never `confirmed`. Read each prediction's own
`measurement` block (`get_predictions`, or `manage_diary_claims` action `list`) for its lifts,
window and threshold, and scope `get_exercise_history` by Hevy `template_id`.

## 3. Grade

```bash
python3 scripts/training_block_retro.py grade --block-end <YYYY-MM-DD> --supplied <file> --out <dir>
```

This runs the code scores and the panel re-grade. The re-grade is ONE call per panel seat (the
charter's concession-ledger schools), back-to-back, on route `charter.retro` (budget feature
`charter_retro`, band 1) with the owner-only charter block cached. From this laptop the dev-session
cap (`ai.dev_session_cap`) holds the spend as well; if it or the budget guard pauses the run, the
retro says `paused`. Then either wait, or run with `--no-panel` for the code half only and say
that the panel did not grade. Never fabricate a seat.

How a row is graded (`config/training_scorecard.json` `combine_rule`): the mean of the row's code
score and the panel's median seat score; one of them alone when only one exists; `carried` with
its last grade when neither exists. The reference row ("Response to the 10 Oct event") is graded
only in a block that had an interruption (a disruption-mode or deload record). Otherwise it is
carried and raises no fix. Keep its wording neutral everywhere.

Read `retro.md` back to him: each row's grade with its evidence (the inputs and the seats' reasons),
then the movers against the last retro (the stored baseline row on the first run). If he, or you
with a stated reason, departs from a computed letter, record it in an `--overrides` JSON
(`{"<row>": {"letter": "B", "reason": "..."}}`) and re-run `grade`. `block_retro.apply_overrides`
refuses an override without a reason.

## 4. The dated predictions

Every #5089 charter prediction whose `grade_by` has passed is graded by its own `measurement`
block (`block_retro.grade_predictions`): `confirmed`, `refuted`, or `inconclusive` when the window
is missing data. A missing week or day is missing, never a miss. The MCP tool `evaluate_prediction`
CANNOT grade these rows (it only edits coach-thread arrays; see
`scripts/register_charter_predictions.py`), so the verdicts are written by `store` below. Never
hand-edit a prediction row.

## 5. Store, write the doc tab, land the fixes

1. **Show him the dry run**: `python3 scripts/training_block_retro.py store --retro <dir>/retro.json`.
   It writes nothing. The write, `--apply`, puts `USER#matthew#SOURCE#training_constraints / RETRO#<block_end>`
   (owner-only, see `docs/SCHEMA.md`) and flips each graded prediction from `observation` to its verdict.
   It is an AWS write, so run it only on his word in this session.
2. **The doc tab**: add a new tab to his PRIVATE review doc (the doc above), titled
   `Block retro <start> to <end>`, holding `retro.md`. Never a public page, never a repo file.
3. **The fixes**: every graded row below the scorecard's `grade_scale.fix_below` is a named fix,
   routed by the row's `fix_route`:
   - `issue`: file one GitHub issue per row (`type:story`, under the training epic). The repo is
     PUBLIC: name the row and the change, and leave out the grade, every number from the owner-only
     rows, the target date, the review doc's content and anything medical. Never name the gym.
   - `charter`: write the proposed charter change for him (the path, the old and new value, why).
     A charter change is his ruling and a new charter version, never an edit you make.
4. Say what you stored, the tab you added, the issues filed and the charter proposals awaiting
   his word, and stamp the charter version the retro was graded against (`charter_version`).

## Guardrails

- Owner-only from end to end: the RETRO# row, the PANEL# rows, the May tracker and the review doc
  are never quoted into a public issue, a PR, a commit or the site. There is no May countdown on any
  published surface.
- Health history is background context only, never a reason to grade intensity down. Nothing
  medical in anything public.
- A tool that fails is named with the field it leaves unknown. `absent` and `read_failed` are not 0.

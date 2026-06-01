# HANDOVER — 2026-05-31 (Saturday late evening — Per-exercise notes + final reset)

**Previous handover:** `handovers/HANDOVER_2026-05-31_HevyTitles.md` (title convention).
**This session covers:** Two coupled commits — (A) final experiment reset to 2026-06-01 + ADR-067 amendment flipping N to all-time-since-experiment, (B) ADR-068 per-exercise notes with anti-hallucination guard.
**HEAD on push:** `094e8c6` (Commit A) → `<sha>` (Commit B). **Layer SOURCE v70; AWS still v68.** All deploys pending.

---

## State at handover

| Surface | Status |
|---|---|
| Hevy write-loop (chat path) | Code-current on v70. Live on v68 (ADR-067 first version). |
| Hevy write-loop (cron) | DISABLED — EventBridge rule + SSM `/life-platform/hevy/cron_enabled=false`. Unchanged. |
| Add-load autoreg | OFF: SSM `/life-platform/hevy/autoreg_add_load_enabled=false`. Unchanged. |
| Shared layer | **AWS: v68. Source: v70.** Two ADRs since the AWS state — title convention (v69 source) + amendment/per-exercise notes (v70 source). |
| EXPERIMENT_START_DATE | Source: **2026-06-01** (Sunday). DDB / Lambda live env: still 2026-05-30 — flipped by `restart_pipeline`. |
| Phase config | `current=Foundation`, `current_started=2026-06-01`. Phase is now decorative only — does NOT bound N. |
| Per-exercise notes mode | `training_week.json:exercise_notes_mode="one_best_line"` (default). `show_both` / `off` available. |

---

## What ADR-068 actually does

**Per-exercise note** (default mode `one_best_line`): one short factual line per exercise, set at generation time, attached to the `notes` field of each Hevy `exercises[]` entry.

Format: `Last: 60kg 8/8/7 (24 May)`
- Top-set weight from the last performed session (kg, rounded to nearest 0.5)
- Per-set reps preserved as `8/8/7` so drop-off is visible
- Friendly short date (`24 May`)

**Cutoffs:**
- 0 prior sessions of this movement → empty note (no fluff)
- 1+ prior sessions → factual cue
- Progression cues out-of-scope here

**Anti-hallucination guard (acceptance gate):**
1. **Structural:** no LLM in the rendering path. Pure Python from facts dict computed from DDB `SOURCE#hevy` records. No model = no invented numbers.
2. **Test:** `test_anti_hallucination_render_quotes_only_source_numbers` extracts every numeric token from a rendered cue and asserts each one traces back to source facts (weight, reps, date day). `test_anti_hallucination_pick_note_does_not_inject_numbers` enforces the same on the combiner output.

**Cue sources** (`pick_note` picks between):
- `history_cue` — always computed from real records
- `ai_comment` — wired in, currently always `None`. Reserved for a future coach-layer output. When that exists, `one_best_line` prefers AI; `show_both` shows both; the same anti-hallucination test will run against AI output.

**Data + perf:** ONE batched DDB Query per generation (`SOURCE#hevy`, `sk >= DATE#<today-180>`, paginated). 8-exercise routine = 1 DDB call, not 8. Index keyed by Hevy template_id, per-exercise lookup is O(1) dict access.

**Strict separation from prescribed load:** notes are advisory text on a separate Hevy field. They never feed back into the generator's budget math. `autoreg_add_load_enabled=false` invariant is preserved end-to-end (the existing subtract-only test in `test_routine_generator` still passes).

---

## What ADR-067 amendment + reset actually does

**Reset:** `EXPERIMENT_START_DATE = "2026-06-01"` (Sunday). Source updated in:
- `config/user_goals.json` (timeline.start_date + end_date)
- `lambdas/constants.py` (EXPERIMENT_START_DATE + DOW)
- `config/training_phases.json` (current_started)

Withings baseline stays at 304.3 lbs (locked from the 2026-05-30 anchoring). The restart_pipeline will preserve it via `--override-weight-lbs 304.3`.

**N convention flipped:**
- Old: N counts pushed routines of this archetype within current phase + 1 (resets at phase boundary).
- New: N counts pushed routines of this archetype since `EXPERIMENT_START_DATE` + 1. Phase becomes a decorative narrative marker.

**Y also rebased:** counts performed Hevy workouts since `EXPERIMENT_START_DATE` + 1. Pre-experiment Hevy history stays in DDB but is excluded from these counters so the title reflects *this experiment's* journey, not lifetime.

---

## Commits this session

- `094e8c6` — ADR-067 amendment + final experiment reset → 2026-06-01.
- `<sha for Commit B>` — ADR-068 per-exercise notes (added in same session, separate commit per spec).

Both push together at handover end.

---

## Deploy steps (exact terminal commands for you to run)

Full step-by-step in:
- `docs/RUNBOOK.md` §"Final Experiment Reset → 2026-06-01"
- `docs/RUNBOOK.md` §"Per-Exercise Notes — Deploy Steps"

### One-shot (covers both ADRs)

```bash
# 1. Restart pipeline does most of the work (constants regen, layer publish,
#    cdk deploys, DDB phase-tag, intelligence wipe, character rebuild, site sync).
python3 deploy/restart_pipeline.py \
  --genesis 2026-06-01 \
  --override-weight-lbs 304.3 \
  --apply

# 2. Make sure the new configs are in S3 (restart-pipeline may not sync these new ones).
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2
aws s3 cp config/training_week.json s3://matthew-life-platform/config/ --region us-west-2

# 3. Verify all 36 layer-using Lambdas are on v70.
aws lambda list-functions --output json --region us-west-2 --no-paginate | \
  python3 -c "import json,sys; d=json.load(sys.stdin); vs={}; \
    [vs.setdefault(l['Arn'].rsplit(':',1)[-1], []).append(f['FunctionName']) \
     for f in d['Functions'] for l in (f.get('Layers') or []) if 'shared-utils' in l['Arn']]; \
    [print(f'v{v}: {len(fns)}') for v,fns in sorted(vs.items())]"
# Expect: v70: 36

# 4. Force MCP cold start (preserves env vars).
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.6'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text

# 5. Smoke from claude.ai:
#      manage_hevy_routine action=draft target_date=2026-06-01
#      manage_hevy_routine action=dry_run routine_id=<id>
#    Inspect wire_body.routine.exercises[*].notes — populated lifts get cues,
#    lifts with no SOURCE#hevy history get empty notes.
```

---

## Open items / follow-ups (not built)

1. **AI-trainer comment emitter.** The `pick_note` hook is wired but `ai_comment` is always `None`. To enable: have the coach layer produce one short coaching line per (movement_key, generation_context) at routine-generation time, pass it through `_build_exercise_note`. The anti-hallucination test will then enforce that the AI may only phrase numbers already in `history_facts`.
2. **Progression cues.** Currently absent. Should ship gated on `autoreg_add_load_enabled=true` AND the N≥30 readiness validation passing — until then they could mislead even as advisory text.
3. **Pre-experiment Hevy history bridge.** Legacy daily-aggregate records (no `source_workout_id`) are excluded from `load_recent_history`. This is intentional for ADR-068 ("this experiment's history") but means lifts not yet logged under the per-workout schema will render empty notes for a while. Cleans up naturally as new workouts roll in.
4. **Decide whether `exercise_notes_mode = "show_both"` ships when AI comments exist.** Currently the default is `one_best_line`. The flag is easy to flip.
5. **First post-reset workout will set the baseline for Y.** Until then Y=1 for every drafted routine.

---

## Files touched

```
lambdas/exercise_history.py                            (new — history loader + renderer + picker)
lambdas/routine_generator.py                           (history index loaded + notes wired into ExerciseBlock)
lambdas/routine_title.py                               (ADR-067 amendment: counters since experiment start)
lambdas/constants.py                                   (EXPERIMENT_START_DATE -> 2026-06-01)
config/user_goals.json                                 (timeline.start_date)
config/training_phases.json                            (current_started)
config/training_week.json                              (exercise_notes_mode, lookback_days)
deploy/build_layer.sh                                  (added exercise_history.py)
ci/lambda_map.json                                     (added exercise_history.py to shared_layer.modules)
cdk/stacks/constants.py                                (SHARED_LAYER_VERSION 69 -> 70)
tests/test_exercise_history.py                         (new — 14 tests incl. anti-hallucination guard)
tests/test_routine_title.py                            (rewrites for new semantics)
tests/test_routine_generator.py                        (2 new — notes-from-history end-to-end, off-mode)
docs/DECISIONS.md                                      (ADR-067 amendment + ADR-068)
docs/CHANGELOG.md                                      (entries for both)
docs/MCP_TOOL_CATALOG.md                               (manage_hevy_routine description)
docs/RUNBOOK.md                                        (Final Reset + Per-Exercise Notes deploy sections)
handovers/HANDOVER_2026-05-31_PerExerciseNotes.md      (this doc)
handovers/HANDOVER_LATEST.md                           (re-pointed)
```

**1,400 offline tests passing** (1384 pre-session + 16 net new from this session).

# HANDOVER — 2026-05-31 (Saturday evening — Hevy routine title convention)

**Previous handover:** `handovers/HANDOVER_LATEST.md` (Saturday morning — site v2 consolidation).
**This session covers:** Hevy routine write-loop title convention (ADR-067) + WHY-note + phases + re-entry kindness. Code only — no deploy.
**HEAD on push:** see "Commits this session" below; the last commit ships on `main`. **Layer v69 not yet published.**

---

## State at handover

| Surface | Status |
|---|---|
| Hevy write-loop (chat path) | Live since 7439b94 + fixes. `manage_hevy_routine` action=commit pushed routine `75e4268c-...` to your Hevy account during smoke. |
| Hevy write-loop (cron) | Deployed but **DISABLED** at two layers: EventBridge rule `hevy-routine-cron-weekly` State=DISABLED + SSM `/life-platform/hevy/cron_enabled=false`. |
| Add-load autoreg | OFF: SSM `/life-platform/hevy/autoreg_add_load_enabled=false`. Subtract-only by default. |
| Shared layer | **AWS: v68. Source: v69.** Layer rebuild + cdk deploy chain pending — run the steps in RUNBOOK §"Hevy Routine Title Convention — Deploy Steps". |
| Hevy duplicates | Two `Upper — 2026-06-01` routines exist (`025c262c-...` orphan from a 4xx that Hevy created anyway, `75e4268c-...` is the tracked one). Orphan-recovery shipped in 7a91fb4 prevents repeats. Delete the orphan from the Hevy app when convenient. |
| Phase config | `Foundation` starting 2026-05-31. Phases: Foundation → Build → Forge → Sustain. |

---

## What ADR-067 actually does

**Title becomes:** `<Phase> - <Type> - <N> - <Y>` — e.g. `Foundation - Upper - 3 - 47`.

- **Phase** from `config/training_phases.json`. Manually advanced (no auto transitions).
- **Type** = `ir.archetype` title-cased (Upper / Lower / Full / Aerobic / Mobility).
- **N** = pushed routines of this archetype in current phase + 1. Resets at phase boundary.
- **Y** = total *performed* Hevy workouts to date + 1. Honest, self-correcting per spec.

**Re-entry variant:** `Welcome back · <Type>`. No counters surface in the title. Y/N still flow through the IR; they're suppressed here to honor Coach Maya / Dr. Reeves's no-guilt-debt principle.

**WHY-note** (one short line) replaces the multi-line rationale dump in Hevy's notes:
- re_entry → "Easing back in after a gap. Take it gently today."
- floor → "Floor session — minimum effective dose for a low-energy day."
- red recovery → "Recovery red. Deloading today; protect joints."
- portfolio guard active → "Aerobic base low. Holding strength flat to protect Zone 2."
- yellow → "Readiness yellow. Holding steady."
- green → "Readiness green. Programmed against weekly volume targets."

---

## **Decision you need to make: N per-phase vs all-time-per-type**

The spec defaulted to **per-phase N** (resets when phase advances). The alternative is **all-time-per-type** (Push #47 forever).

| Option | Title example | Pros | Cons |
|---|---|---|---|
| **Per-phase (shipped)** | `Foundation - Push - 3 - 47` | Clear "where in the phase" signal; phase boundary is a natural reset. | Same-named Push routines repeat across phases (Foundation-Push-3, Build-Push-3, ...). |
| All-time-per-type | `Foundation - Push - 124 - 47` | Big-arc tally is visible in the title; never repeats. | Y already does the big-arc tally; N becomes redundant. Phase context less prominent. |

To flip to all-time-per-type: drop the `phase_start` filter in `routine_title.count_phase_archetype_routines` (single line — query the whole ROUTINE_INDEX partition by archetype). One-line ADR-067 amendment to capture the decision.

**My recommendation:** keep per-phase. The whole point of phases is to demarcate program eras; N=3 in Foundation and N=3 in Build are different programmatic moments. Y already does the big arc.

---

## Commits this session

- `<sha-from-final-commit>` — ADR-067 title convention + WHY-note + phase counters + re-entry naming. Layer v68→v69 (source only; not published).

---

## Deploy steps (exact commands for you to run)

Full step-by-step in `docs/RUNBOOK.md` §"Hevy Routine Title Convention — Deploy Steps". Summary:

```bash
# 1. Sync new phase config to S3
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2

# 2. Build layer locally
bash deploy/build_layer.sh

# 3. Publish v69 + propagate
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy LifePlatformMcp LifePlatformOperational LifePlatformIngestion \
               LifePlatformEmail LifePlatformCompute \
               --require-approval never --concurrency 3
cd ..

# 4. Force MCP cold start (so the warm container reloads training_phases.json from S3)
#    See RUNBOOK for the env-var-preserving update-function-configuration snippet.

# 5. From claude.ai: re-commit an existing routine to see the new title in Hevy.
#    manage_hevy_routine action=list -> pick a routine_id -> action=commit
```

---

## Open items for the next session

1. **Decide N convention** (per-phase vs all-time-per-type) — see above.
2. **Delete the duplicate `Upper — 2026-06-01` (`025c262c-...`)** from the Hevy app. Hevy has no DELETE API. (Don't worry about repeats — orphan-recovery in 7a91fb4 catches the create-then-validate quirk.)
3. **First real Hevy workout in the Foundation phase** will set Y baseline. Y is computed at commit time from the live DDB count; right now `count_total_performed_workouts()` will return however many Hevy workouts you have in the `SOURCE#hevy` partition.
4. **Phase advancement workflow** is documented but untested live. First time you flip Foundation→Build, double-check the title formats.

---

## Out of scope this session (explicitly not built)

Spec was crystal clear: do NOT build Character-Sheet training pillar, PR-celebration logic, streak art, chronicle/Elena chapter hooks, cron changes, autoreg changes. None of these were touched.

### Worth considering for a future session (no work done)

- **PR celebration in the WHY-note** — e.g. "First Push since Build started. Tag this one." Would require querying recent performed workouts of the same archetype and detecting a top-set delta. Out of scope; tagged here so it's captured.
- **Chronicle pulling phase markers** — Elena could thread the Foundation→Build transition into a Wednesday chapter. Out of scope; flagged.

---

## Files touched

```
config/training_phases.json                            (new)
lambdas/routine_title.py                               (new)
lambdas/hevy_compiler.py                               (title_context + why_note kwargs)
lambdas/operational/hevy_routine_cron_lambda.py        (build + pass title_context, why_note)
mcp/tools_hevy_routine.py                              (build + pass title_context, why_note in commit)
deploy/build_layer.sh                                  (added routine_title.py to MODULES)
ci/lambda_map.json                                     (added routine_title.py to shared_layer.modules)
cdk/stacks/constants.py                                (SHARED_LAYER_VERSION 68 -> 69)
tests/test_routine_title.py                            (new — 11 tests)
tests/test_hevy_compiler.py                            (3 new tests for title_context path)
tests/test_adherence_calc.py                           (fix stale catalog IDs unrelated to this work)
docs/DECISIONS.md                                      (ADR-067)
docs/CHANGELOG.md                                      (entry)
docs/MCP_TOOL_CATALOG.md                               (manage_hevy_routine description)
docs/RUNBOOK.md                                        (deploy steps section)
handovers/HANDOVER_2026-05-31_HevyTitles.md            (this doc)
handovers/HANDOVER_LATEST.md                           (re-pointed)
```

**1,384 offline tests passing** (1 pre-existing failure in test_adherence_calc fixed as a drive-by; was using old catalog IDs replaced in 989cbdf).

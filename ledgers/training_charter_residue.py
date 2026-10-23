"""ledgers/training_charter_residue.py — the dated, SHRINK-ONLY ledger behind the training
charter derivation guard (#5068, ADR-164; charter primitive 3).

Every site that still carried a hand copy of a charter-owned value when the charter landed,
measured 2026-10-18 by `tests/test_training_charter_derivation_5068.py::census()` on the
#5068 lane (code lines only — comments and docstrings stripped; `redline_changelog.py`
skipped as a dated history of past values). Key = `<path>::<pattern id>`, value = the
number of matching lines.

Ratchet semantics:
  * a key's count may only go DOWN — a new copy reds the guard with the lines named;
  * a row whose live count fell is STALE and reds too, naming the replacement line, so the
    ledger is always the truth, never a ceiling;
  * the row COUNT may only fall from `SEEDED_ROW_COUNT` (pinned a second time in the test):
    no row is ever added to legalise a new copy — the only green path is reading the value
    through `training.training_charter.charter_value()`.

The seed moved ONCE, inside the PR that created it (review of PR #5118, 2026-10-18): the
first census ran 8 patterns over 7 files and seeded 10 rows; review found the sweep blind
to three value classes the #5068 Set names (the movement gates, the volume bands, the effort
ceilings) and to four Set files (mcp/tools_benchmark.py, lambdas/web/site_api_nutrition.py,
config/user_goals.json, docs/coaching/COACH_SESSION.md). Widening after merge would have
meant RAISING the seed against this ledger's own rule, so it was re-seeded here: 11 patterns,
11 files beyond the two directory sweeps, 21 rows (20 after #5074 deleted the site_api_nutrition row). The original 10 rows are unchanged.

What W1 (#5050) is expected to retire, by row:
  * owner_redlines.py session_minutes / sequence_names — the engine's lifting budget and split
    read from the charter (`split.session_minutes.lifting`, `split.sequence`);
  * owner_redlines.py rate_band — RETIRED #5074 down to 2 rows' worth of lines: the schedule's
    above-landing target/cap now read `governing_goal.rate_band_lb_per_wk` (`training/rate_band.py`);
    the 2 left are the overshoot trigger's own 3.0 lb/wk threshold (a different quantity that shares
    the number) — NOT band copies, and not retireable by a charter read;
  * owner_redlines.py scheduled_deload_week — the scheduled deload is retired outright
    (charter `deload.scheduled: false`, owner ruling 2026-10-18);
  * owner_redlines.py movement_gate_lb (the taper table's `above_lb` steps at the three
    gated weights, `trap_bar_until_lb`, the `run_gate_lb` record, `deceleration_begins_lb`)
    and program_structure.py movement_gate_lb (`conventional_pull_gate_lb` + its prose) —
    the gates read `gated_movements.*`; the #5090 running lane carries the 240 gate;
  * mcp/tools_benchmark.py movement_gate_lb — `RUN_GATE_LB` and its two prose lines read
    `gated_movements.running.gate_lb`;
  * docs/coaching/COACH_SESSION.md movement_gate_lb — the prompt names the charter, not
    the number;
  * owner_redlines.py / program_structure.py / routine_title.py effort_ceiling_rpe — the
    `top_rpe` band and the `RPE 7–8` top-set prose read `effort_ceilings.by_movement_class` (renamed from by_experience_tier by #5058)
    (the charter's compounds band is 8–9; the pre-charter 7–8 is the stale value);
  * owner_redlines.py / program_structure.py volume_band_sets — the `~10 sets/muscle/wk`
    target reads `volume_priorities.sets_per_wk`;
  * program_structure.py / program_v03.py anchor_block_weeks, sequence_names,
    session_minutes — the block cadence, labels and minute ceiling derive from
    `rotation.anchors_fixed_weeks` and `split.*`;
  * recent_aerobic.py sequence_names — the lower-session predicate reads `split.sequence`;
  * routine_generator.py session_minutes — the floor/empty-session caps derive from
    `split.session_minutes.lifting`;
  * lambdas/web/site_api_nutrition.py rate_band — RETIRED #5074 (the literal, `target_rate_lb_wk`,
    `required_deficit_kcal` and `gap_kcal` left the published payload; the row is deleted);
  * config/user_goals.json steps_floor — `daily_movement_target` (a 6–7k steps note that
    predates the 12,000 floor) is retired or re-pointed at `steps.floor` by the W1 lane
    that re-seeds the pre-registration from the charter.
Retired since the seed: program_structure.py anchor_block_weeks (3 lines: `ROTATION_RULE.block_weeks`,
`SESSION_SEQUENCE.weeks_per_block` and the "6-week block" rule prose) — #5077 reads the block length from
`rotation.anchors_fixed_weeks` through `block_model.block_weeks()`. #5058 retired effort_ceiling_rpe in
owner_redlines.py (1: the rep-scheme prose names the charter ceilings), program_structure.py (2: `EXPOSURES.heavy.top_rpe`
and the HEAVY cue — the cues read `effort_ceilings.by_movement_class` through `training.effort_ceilings`) and two of
routine_title.py's three (the v0.4/v1 heavy WHY lines); the one left is the superseded v0.3 full-body WHY line, history.
The guard's key moved with the charter rename (`by_experience_tier` -> `by_movement_class`).
Already retired at the seed: mcp/tools_health.py's 2.5 lb/wk line (3 rows on the first
census) — #5115 (charter-w0) replaced it with a bodyweight-relative flag carrying a
`# charter: governing_goal.rate_band` marker before this ledger was committed, so the row
was deleted on the merge: the first ratchet move, made by the guard itself.
The two coaching skills (daily-debrief, speak-to-coaches) carried no hit at the seed.
Retired since the seed: docs/coaching/COACH_SESSION.md::movement_gate_lb (#5086, 2026-10-19) — the prompt moved to
`.claude/skills/coach-session/SKILL.md`, rewritten to name the charter's run gate (`gated_movements`), never its weight;
COACH_SESSION.md is a pointer to it.
Retired since the seed: lambdas/training/recent_aerobic.py::sequence_names (#5076, 2026-10-18) — `is_lower`
reads the lower names from `split.sequence` through `training.cardio_menu.is_lower`.
Retired since the seed: mcp/tools_benchmark.py::movement_gate_lb (#5090, 2026-10-19, 3 lines) — `RUN_GATE_LB` and its two
prose lines read `gated_movements.running.gate_lb` (`_run_gate_lb()`); the whole gate is `training.run_onramp.gate_state`.
The owner_redlines.py `run_gate_lb` record stays (its row): the owner's stated text, which the charter now carries as
numbers (`gated_movements.running.walking_weeks` / `walking_hours_per_wk` / `onramp`), held equal to the record's
`tissue_clause` by tests/test_run_onramp_5090.py.

Registered in scripts/obligation_carriers.py::RESIDUE_LEDGERS (carrier #5050, expires
2027-01-15).
"""

MEASURED_AT = "2026-10-18 · lane issue-5068-training-charter at origin/charter-w0 03d34e4d5 (#5115 in), re-seeded on the PR #5118 review"

SEEDED_ROW_COUNT = 21

TRAINING_CHARTER_RESIDUE = {
    "config/user_goals.json::steps_floor": 1,
    "lambdas/training/owner_redlines.py::movement_gate_lb": 7,
    "lambdas/training/owner_redlines.py::rate_band": 2,
    "lambdas/training/owner_redlines.py::volume_band_sets": 1,
    "lambdas/training/program_structure.py::movement_gate_lb": 2,
    "lambdas/training/program_structure.py::volume_band_sets": 2,
    "lambdas/training/program_v03.py::anchor_block_weeks": 1,
    "lambdas/training/routine_generator.py::session_minutes": 2,
    "lambdas/training/routine_title.py::effort_ceiling_rpe": 1,
}

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
11 files beyond the two directory sweeps, 21 rows. The original 10 rows are unchanged.

What W1 (#5050) is expected to retire, by row:
  * owner_redlines.py rate_band / session_minutes / sequence_names — the engine's rate
    band, lifting budget and split read from the charter (`governing_goal.rate_band_lb_per_wk`,
    `split.session_minutes.lifting`, `split.sequence`);
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
    `top_rpe` band and the `RPE 7–8` top-set prose read `effort_ceilings.by_experience_tier`
    (the charter's compounds band is 8–9; the pre-charter 7–8 is the stale value);
  * owner_redlines.py / program_structure.py volume_band_sets — the `~10 sets/muscle/wk`
    target reads `volume_priorities.sets_per_wk`;
  * program_structure.py / program_v03.py anchor_block_weeks, sequence_names,
    session_minutes — the block cadence, labels and minute ceiling derive from
    `rotation.anchors_fixed_weeks` and `split.*`;
  * recent_aerobic.py sequence_names — the lower-session predicate reads `split.sequence`;
  * routine_generator.py session_minutes — the floor/empty-session caps derive from
    `split.session_minutes.lifting`;
  * lambdas/web/site_api_nutrition.py rate_band — `_TARGET_RATE_LB_WK` is retired by the
    #5087 Set's W1 reader lane (a published surface may not show the rate band at all:
    `public_view()` carries no `governing_goal.*`, so the row leaves with the literal, not
    by a charter read);
  * config/user_goals.json steps_floor — `daily_movement_target` (a 6–7k steps note that
    predates the 12,000 floor) is retired or re-pointed at `steps.floor` by the W1 lane
    that re-seeds the pre-registration from the charter.
Retired since the seed: program_structure.py anchor_block_weeks (3 lines: `ROTATION_RULE.block_weeks`,
`SESSION_SEQUENCE.weeks_per_block` and the "6-week block" rule prose) — #5077 reads the block length from
`rotation.anchors_fixed_weeks` through `block_model.block_weeks()`.
Already retired at the seed: mcp/tools_health.py's 2.5 lb/wk line (3 rows on the first
census) — #5115 (charter-w0) replaced it with a bodyweight-relative flag carrying a
`# charter: governing_goal.rate_band` marker before this ledger was committed, so the row
was deleted on the merge: the first ratchet move, made by the guard itself.
The two coaching skills (daily-debrief, speak-to-coaches) carried no hit at the seed.

Registered in scripts/obligation_carriers.py::RESIDUE_LEDGERS (carrier #5050, expires
2027-01-15).
"""

MEASURED_AT = "2026-10-18 · lane issue-5068-training-charter at origin/charter-w0 03d34e4d5 (#5115 in), re-seeded on the PR #5118 review"

SEEDED_ROW_COUNT = 21

TRAINING_CHARTER_RESIDUE = {
    "config/user_goals.json::steps_floor": 1,
    "docs/coaching/COACH_SESSION.md::movement_gate_lb": 1,
    "lambdas/training/owner_redlines.py::effort_ceiling_rpe": 1,
    "lambdas/training/owner_redlines.py::movement_gate_lb": 7,
    "lambdas/training/owner_redlines.py::rate_band": 6,
    "lambdas/training/owner_redlines.py::volume_band_sets": 1,
    "lambdas/training/program_structure.py::effort_ceiling_rpe": 2,
    "lambdas/training/program_structure.py::movement_gate_lb": 2,
    "lambdas/training/program_structure.py::volume_band_sets": 2,
    "lambdas/training/program_v03.py::anchor_block_weeks": 1,
    "lambdas/training/routine_generator.py::session_minutes": 2,
    "lambdas/training/routine_title.py::effort_ceiling_rpe": 3,
    "lambdas/web/site_api_nutrition.py::rate_band": 1,
    "mcp/tools_benchmark.py::movement_gate_lb": 3,
}

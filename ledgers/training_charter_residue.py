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

What W1 (#5050) is expected to retire, by row:
  * owner_redlines.py rate_band / session_minutes / sequence_names — the engine's rate
    band, lifting budget and split read from the charter (`governing_goal.rate_band_lb_per_wk`,
    `split.session_minutes.lifting`, `split.sequence`);
  * owner_redlines.py scheduled_deload_week — the scheduled deload is retired outright
    (charter `deload.scheduled: false`, owner ruling 2026-10-18);
  * program_structure.py / program_v03.py anchor_block_weeks, sequence_names,
    session_minutes — the block cadence, labels and minute ceiling derive from
    `rotation.anchors_fixed_weeks` and `split.*`;
  * recent_aerobic.py sequence_names — the lower-session predicate reads `split.sequence`;
  * routine_generator.py session_minutes — the floor/empty-session caps derive from
    `split.session_minutes.lifting`;
Already retired at the seed: mcp/tools_health.py's 2.5 lb/wk line (3 rows on the first
census) — #5115 (charter-w0) replaced it with a bodyweight-relative flag carrying a
`# charter: governing_goal.rate_band` marker before this ledger was committed, so the row
was deleted on the merge: the first ratchet move, made by the guard itself.
The two coaching skills (daily-debrief, speak-to-coaches) carried no hit at the seed.

Registered in scripts/obligation_carriers.py::RESIDUE_LEDGERS (carrier #5050, expires
2027-01-15).
"""

MEASURED_AT = "2026-10-18 · lane issue-5068-training-charter after merging origin/charter-w0 at 03d34e4d5 (#5115 in)"

SEEDED_ROW_COUNT = 10

TRAINING_CHARTER_RESIDUE = {
    "lambdas/training/owner_redlines.py::rate_band": 6,
    "lambdas/training/owner_redlines.py::scheduled_deload_week": 2,
    "lambdas/training/owner_redlines.py::sequence_names": 1,
    "lambdas/training/owner_redlines.py::session_minutes": 1,
    "lambdas/training/program_structure.py::anchor_block_weeks": 3,
    "lambdas/training/program_structure.py::sequence_names": 12,
    "lambdas/training/program_structure.py::session_minutes": 2,
    "lambdas/training/program_v03.py::anchor_block_weeks": 1,
    "lambdas/training/recent_aerobic.py::sequence_names": 1,
    "lambdas/training/routine_generator.py::session_minutes": 2,
}

"""program_v04.py — TRAINING_PROGRAM v0.4 (four-session upper/lower), SUPERSEDED 2026-10-18, kept readable.

Owner rulings 2026-10-18 (epic #5067, rulings 5 and 6): five lifting days in the charter's order
(`config/training_charter.json` `split.sequence`), and "the v0.4 lock to 2026-11-04 is lifted
now". The five-day program lives in `training.program_structure` (#5069); this module keeps
v0.4's structure as HISTORY, the way `training.program_v03` keeps v0.3's, so:

  * the session sequence can credit every session logged BEFORE the cut-over with the v0.4 role
    it was served as (`session_sequence` reads `SESSION_SEQUENCE` here for the days before
    `program_structure.SESSION_SEQUENCE['cutover']['on']`) — the live block is not re-anchored;
  * a routine, plan or adherence row written under v0.4 still reads against the program it was
    written for;
  * the owner's block lock (#4161) is a dated record of what was decided, not a guard. Nothing
    reads it to refuse anything.

The four v0.4 roles' TEMPLATES are not copied: the five-day program kept all four unchanged and
added the fifth, so `program_structure.SESSION_TEMPLATES` is still the definition of each of them.
"""

from __future__ import annotations

from typing import Any

SUPERSEDED: dict[str, Any] = {
    "program_version": "0.4",
    "split": "upper_lower",
    "superseded_on": "2026-10-18",
    "superseded_by": "1.0",
    "issue": "#5069",
    "ruling": "owner rulings 2026-10-18 (epic #5067): ruling 5 — five lifting days in the charter's order; ruling 6 — the v0.4 lock is lifted now",
    "approved": "2026-09-23 (#4147, DECISION#2026-09-24T03:10:59); ratified 2026-09-25 (#4161)",
    "prose_home": "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.4.md",
    "note": "v0.4 ran as a sequence from 2026-09-24; its credited sessions keep their v0.4 roles (session_sequence's cut-over).",
}

SESSION_SEQUENCE: dict[str, Any] = {
    "program_version": "0.4",
    "block_start": "2026-09-24",
    "session_roles": ["upper_heavy", "lower_heavy", "upper_volume", "lower_volume"],
    "first_role": "lower_heavy",
    "first_session": {
        "role": "lower_heavy",
        "routine_id": "b1b9960468f374e30dcdeca8630dd18f",
        "hevy_routine_id": "4b743f67",
        "target_date": "2026-09-25",
        "committed": "from chat, 2026-09-23",
    },
    "sessions_per_week": 4,
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": "DECISION#2026-09-24T03:10:59",
    "issue": "#4147 (order: #4110)",
}
"""v0.4's order, exactly as it was served (#4147). The block start is shared with the live program."""

NOMINAL_WEEK: dict[str, str] = {"0": "upper_heavy", "1": "lower_heavy", "3": "upper_volume", "4": "lower_volume"}
"""v0.4's nominal weekday placement (lifting days only; every other day was a walk)."""

BLOCK_LOCK: dict[str, Any] = {
    "weeks": 6,
    "block_start": "2026-09-24",
    "locked_until": "2026-11-04",
    "rule": "no STRUCTURAL edits to v0.4 (split, order, templates, accessories) before this date; loads and deloads run as written",
    "structure_fingerprint": "000ffceefa732c6e",
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": "DECISION#2026-09-24T03:10:59",
    "lifted": {
        "on": "2026-10-18",
        "by": "owner ruling 6, 2026-10-18 (epic #5067): 'the v0.4 lock to 2026-11-04 is lifted now'",
        "issue": "#5069",
    },
}
"""HISTORY. The owner's 6-week lock on v0.4 (#4161 enforced it as a guard); lifted by his ruling of 2026-10-18.
The fingerprint is the value recorded at the lock; `session_sequence.structure_fingerprint()` still measures the
live structure, and nothing compares the two to refuse an edit."""

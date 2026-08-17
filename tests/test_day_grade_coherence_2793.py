"""
tests/test_day_grade_coherence_2793.py — the day-grade letter must equal what its
OWN stored score derives through the engine's real mapping (#2793).

The incident: the 2026-08-16 18:45Z sentinel run alarmed
    day_grade_letter_vs_score: stored 68 vs derived 70 (tol 0.0)
which read as a 2-point score disagreement. It wasn't — 68 and 70 were ord('D')
and ord('F'). The stored row (DATE#2026-08-15, total_score 51, letter_grade "D")
was perfectly coherent with its own formula (scoring_engine.letter_grade: D for
45-54). The sentinel adapter had hand-typed a "collegiate" 90/80/70/60 band table
(#2737, born 2026-08-15) whose first letters disagree with the engine for every
score in 45-89 except 80-84 — the drifted copy was inside the instrument.

The fix removes the second copy: the adapter derives the expected letter by
calling scoring_engine.letter_grade itself (the same single-source pattern the
character-tier check uses with get_tier — charter standing rule 1). These tests
drive the REAL adapter (`_gather_computed_checks`), not a reimplementation, so a
re-typed table that drifts anywhere in 0-100 reds this file.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import coherence_sentinel_lambda as sentinel  # noqa: E402
from health.scoring_engine import letter_grade  # noqa: E402

# The wire: the exact row that tripped the 2026-08-16 18:45Z run, copied field-for-
# field from the live table (cycle-13 archive, ADR-077 phase-stamped `pilot`). Not an
# invented dict — a rename or reshape of the stored record must break this fixture.
ARCHIVED_2026_08_15 = {
    "pk": "USER#matthew#SOURCE#day_grade",
    "sk": "DATE#2026-08-15",
    "date": "2026-08-15",
    "algorithm_version": "1.1",
    "component_habits_mvp": 0,
    "component_movement": 74,
    "component_recovery": 57,
    "component_sleep_quality": 66,
    "computed_at": "2026-08-16T16:40:18.922003+00:00",
    "letter_grade": "D",
    "total_score": 51,
    "phase": "pilot",
    "run_id": "9adf2e7e-5313-4be7-90f4-4f2801bbea56",
    "weights_snapshot": {
        "nutrition": 0.2,
        "glucose": 0.05,
        "journal": 0.05,
        "sleep_quality": 0.2,
        "hydration": 0.05,
        "recovery": 0.15,
        "movement": 0.15,
        "habits_mvp": 0.15,
    },
}


def _checks_for(monkeypatch, row):
    monkeypatch.setattr(sentinel, "_latest", lambda source: row if source == "day_grade" else {})
    checks = [c for c in sentinel._gather_computed_checks() if c["name"].startswith("day_grade_letter_vs_score")]
    assert checks, "adapter produced no day-grade check for a live-shaped row"
    return checks


def test_the_incident_row_is_coherent_and_no_longer_alarms(monkeypatch):
    """The #2793 regression: 51/'D' is what the engine itself stores (D = 45-54).
    The old hand-typed bands derived 'F' and alarmed at tol 0; the adapter must
    judge the row by the engine's own mapping and pass it."""
    checks = _checks_for(monkeypatch, dict(ARCHIVED_2026_08_15))
    f = sentinel.ci.check_computed_coherence(checks)
    assert f.status == sentinel.ci.OK, f.detail


def test_every_letter_the_compute_path_can_store_derives_coherent(monkeypatch):
    """Guard the SET, not the instance: for every score the store path can write,
    the letter it writes (letter_grade(score)) must pass the sentinel's tol-0
    re-derivation. The old table failed this at first-letter level for every
    score in 45-89 except 80-84 — including 51, the incident. A future re-typed
    band table that drifts anywhere in the domain reds this test."""
    bad = []
    for score in [s / 2 for s in range(0, 201)]:  # 0, 0.5, ..., 100 — crosses every band edge
        row = dict(ARCHIVED_2026_08_15, total_score=score, letter_grade=letter_grade(score))
        f = sentinel.ci.check_computed_coherence(_checks_for(monkeypatch, row))
        if f.status != sentinel.ci.OK:
            bad.append((score, letter_grade(score), f.detail))
    assert not bad, f"engine-stored letters the sentinel re-derivation rejects: {bad[:8]}"


def test_a_genuinely_incoherent_letter_still_alarms(monkeypatch):
    """The tol-0 instrument keeps its meaning: a letter the formula cannot produce
    from the stored score must alarm. 'F' at 51 is the letter the OLD hand-typed
    table would have silently blessed — the drift hid true incoherence too."""
    for wrong in ("C", "F", "A+"):
        row = dict(ARCHIVED_2026_08_15, letter_grade=wrong)
        f = sentinel.ci.check_computed_coherence(_checks_for(monkeypatch, row))
        assert f.status == sentinel.ci.ALARM, f"letter {wrong!r} at score 51 must alarm"
        assert "day_grade_letter_vs_score" in (f.detail or "")


def test_modifier_drift_is_now_caught(monkeypatch):
    """The stored letter comes from letter_grade at store time, so the comparison
    is the FULL letter: 'B+' at 76 (engine says 'B') is a desync even though the
    first letters agree — the old first-letter-only check passed it."""
    row = dict(ARCHIVED_2026_08_15, total_score=76, letter_grade="B+")
    f = sentinel.ci.check_computed_coherence(_checks_for(monkeypatch, row))
    assert f.status == sentinel.ci.ALARM


def test_alarm_text_reads_as_letters_not_ord_values(monkeypatch):
    """'stored 68 vs derived 70' sent #2793 hunting a score bug that never existed;
    the check name now carries the letters themselves."""
    row = dict(ARCHIVED_2026_08_15, letter_grade="C")
    f = sentinel.ci.check_computed_coherence(_checks_for(monkeypatch, row))
    assert "[C vs D]" in (f.detail or "")

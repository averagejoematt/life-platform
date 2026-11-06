"""tests/test_debrief_journal_invariance.py — the daily debrief's inputs never move with journal activity.

Owner rulings 2026-11-03 and 2026-11-06 ("Audit the daily-debrief MP3s ... before authorizing publication"). The
audit found two journal-moving inputs to the public episode: the tier-1 ("stretch") habit count, whose stored
totals include the two journal habits, and the presence block, rendered from the FULL engagement record whose
quiet channels include the journal. Both are fixed at the input; this file holds the facts and the presence
signal invariant across journal-only variations, with mutation controls that show the check can fail.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import emails.daily_debrief_lambda as dd  # noqa: E402


class _Table:
    def __init__(self, items):
        self.items = items

    def get_item(self, Key, **_):
        it = self.items.get(Key["sk"] if Key["sk"] == "STATE#current" else Key["pk"].rsplit("#", 1)[-1])
        return {"Item": it} if it is not None else {}


def _cm():
    return {"day_grade_letter": "B", "day_grade_score": Decimal("81"), "recovery_pct": Decimal("62"), "tier0_streak": Decimal("4")}


def _hs(wrote: bool):
    # the stored tier-1 counts include the journal habits: a written day moves them
    return {"tier0_done": 5, "tier0_total": 6, "tier1_done": 4 if wrote else 2, "tier1_total": 4}


def _facts(wrote: bool, monkeypatch):
    monkeypatch.setattr(dd, "table", _Table({"computed_metrics": _cm(), "habit_scores": _hs(wrote)}))
    return dd.gather_facts("2026-11-04")


def test_the_spoken_facts_do_not_move_with_journal_completion(monkeypatch):
    assert _facts(True, monkeypatch) == _facts(False, monkeypatch)
    facts = _facts(True, monkeypatch)
    assert "stretch_habits_done" not in facts and "stretch_habits_total" not in facts
    assert facts["core_habits_done"] == 5 and facts["core_habits_total"] == 6  # the public tier still airs


def test_mutation_control_the_stored_counts_really_differ():
    assert _hs(True) != _hs(False)


def _sig(record, monkeypatch):
    monkeypatch.setattr(dd, "table", _Table({"STATE#current": record}))
    return dd._presence_signal()


def test_the_presence_signal_is_the_public_projection(monkeypatch):
    public = {"presence_class": "present", "gap_days": Decimal("0")}
    quiet_private = {"presence_class": "quiet", "quiet_channels": ["journal"], "gap_days": Decimal("9"), "public": dict(public)}
    all_present = {"presence_class": "present", "quiet_channels": [], "gap_days": Decimal("0"), "public": dict(public)}
    assert _sig(quiet_private, monkeypatch) == _sig(all_present, monkeypatch) == public
    assert quiet_private != all_present  # control: the full records differ, the signal does not
    assert _sig({"presence_class": "quiet"}, monkeypatch) == {}  # no projection → steers nothing

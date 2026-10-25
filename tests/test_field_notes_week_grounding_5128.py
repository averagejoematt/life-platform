"""tests/test_field_notes_week_grounding_5128.py — the field note's contradiction check
grounds against the NOTE'S OWN WEEK of computed_metrics, not the newest single row.

Live proof 2026-10-25: `field-notes-generate {"manual_week":"2026-W42"}` held on a Whoop
recovery percentage because the check read `computed_metrics` with `Limit=1` (the latest
day, outside W42 entirely). A figure present in any day of the week is grounded; a figure
absent from the whole week still holds (the mutation control).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import field_notes_lambda as fnl  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

_PK = "USER#matthew#SOURCE#computed_metrics"
# 2026-W42 = 2026-10-12 .. 2026-10-18. Recovery swings across the week; Thursday is 72.
_WEEK = [
    {"pk": _PK, "sk": f"DATE#2026-10-{d}", "date": f"2026-10-{d}", "recovery_pct": r, "rhr_bpm": 62, "hrv_ms": 40.0}
    for d, r in (("12", 35), ("13", 38), ("14", 40), ("15", 72), ("16", 41), ("17", 36), ("18", 33))
]
_LATEST_OUTSIDE = {"pk": _PK, "sk": "DATE#2026-10-25", "date": "2026-10-25", "recovery_pct": 30, "rhr_bpm": 62, "hrv_ms": 40.0}
_W42 = ("2026-10-12", "2026-10-18")
_PROMPT = "this week: recovery 72 percent on Thursday, recovery 93 claimed, resting heart rate 62 bpm"


def _week_table(rows):
    """A query double that honours the sk BETWEEN of the week read, and returns the newest
    row for a Limit=1 read — so a regression to the latest-row read is observable."""

    def hook(t, **kw):
        if kw.get("Limit") == 1:
            return {"Items": [_LATEST_OUTSIDE]}
        return {"Items": [r for r in rows if _W42[0] <= r["date"] <= _W42[1]]}

    return FakeDdbTable(rows=[], seed_store=False, query_hook=hook)


def _contradictions(monkeypatch, text, rows=_WEEK):
    monkeypatch.setattr(fnl, "table", _week_table(rows + [_LATEST_OUTSIDE]))
    findings = fnl._note_grounding_findings({"ai_present": text}, _PROMPT, week=_W42)
    return [f for f in findings if f["type"] == "contradiction"]


def test_mid_week_value_is_grounded_by_its_own_week(monkeypatch):
    """Thursday's 72% is in the week's data; the newest row (30%, outside W42) must not hold it."""
    assert _contradictions(monkeypatch, "Recovery peaked at 72% on Thursday.") == []


def test_number_absent_from_the_whole_week_still_holds(monkeypatch):
    """Mutation control: 93% is within 10 points of no day in the week and not near the mean."""
    hits = _contradictions(monkeypatch, "Recovery peaked at 93% on Thursday.")
    assert [h["metric"] for h in hits] == ["Whoop recovery"]
    assert hits[0]["canonical"] == 33, "reported against the week's newest day, not a row outside the week"


def test_week_mean_grounds_an_average_claim():
    mean = sum(r["recovery_pct"] for r in _WEEK) / len(_WEEK)  # ~42.1
    assert fnl.week_contradiction_hits({"ai_present": f"Recovery averaged {mean:.0f}% across the week."}, _WEEK) == []


def test_the_week_read_is_bounded_by_the_iso_week(monkeypatch):
    t = _week_table(_WEEK)
    monkeypatch.setattr(fnl, "table", t)
    rows = fnl._week_metrics_rows(_W42)
    assert {r["date"] for r in rows} == {r["date"] for r in _WEEK}
    assert all("Limit" not in c for c in t.query_calls), "the week read must not be the newest-row Limit=1 query"


def test_no_week_rows_degrades_to_allow_list_only():
    assert fnl.week_contradiction_hits({"ai_present": "Recovery peaked at 93%."}, []) == []

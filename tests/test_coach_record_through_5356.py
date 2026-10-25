"""tests/test_coach_record_through_5356.py — what a coach record's "through <day>" claims.

The live specimen (qa-smoke, 2026-10-25 ~05:30Z, reader-truth finding e8f2c1, high): on
Day 49 /api/coaches served Lisa Park "19 of 47 checked calls right (40%) through October 18"
beside four coaches "through October 23". Grading was not behind — her next open calls fell
due October 26 and November 2 — but ``through`` was the outcome_date of her latest decided
call, which reads as a record that stopped a week ago. ``through`` is now the day the record
is COMPLETE through (``coach_record.complete_through``). Every date here is fixed; the one
clock read (``coach_record.today_pt``) is frozen where the default path is exercised.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_record as cr  # noqa: E402

GENESIS = "2026-09-06"


def _decided(pid, status, outcome_date):
    return {"prediction_id": pid, "sk": f"PREDICTION#{pid}", "status": status, "outcome_date": outcome_date}


def _open(pid, created_date, window_days=7, subdomain="sleep", status="pending", **extra):
    """An open directional call; sleep's domain minimum is 7 days, so due = created + 7."""
    return {
        "prediction_id": pid,
        "sk": f"PREDICTION#{pid}",
        "status": status,
        "created_date": created_date,
        "subdomain": subdomain,
        "evaluation": {"type": "directional", "evaluation_window_days": window_days},
        **extra,
    }


def _park_rows(*open_rows):
    """Park's shape on 2026-10-24: latest grades on 10-17 and 10-18, then nothing due."""
    return [
        _decided("a", "confirmed", "2026-10-16"),
        _decided("b", "refuted", "2026-10-17"),
        _decided("c", "refuted", "2026-10-18"),
        *open_rows,
    ]


def test_the_live_specimen_reads_through_the_as_of_day_when_nothing_is_owed():
    # Her two open calls fall due 10-26 and 11-02 — after the as-of day — so every call of
    # hers that came due has been checked: the record is complete through 10-23.
    rows = _park_rows(_open("d", "2026-10-19"), _open("e", "2026-10-26"))
    record = cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")
    assert record == {"confirmed": 1, "refuted": 2, "n": 3, "through": "2026-10-23"}
    assert cr.headline(record) == "1 of 3 checked calls right through October 23"


def test_a_stalled_grader_stops_the_record_the_day_before_the_first_unchecked_call():
    # A call due 10-21 is still pending on 10-23: the grader owes it, so the record is only
    # complete through 10-20 — it stops advancing instead of claiming to be current.
    rows = _park_rows(_open("d", "2026-10-14"), _open("e", "2026-10-26"))
    assert cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-20"
    # `confirming` is a status the grader still owes a verdict on, too.
    rows = _park_rows(_open("d", "2026-10-14", status="confirming"))
    assert cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-20"


def test_a_call_due_today_before_the_morning_grade_holds_the_record_at_yesterday():
    # The grader runs at 16:00 UTC; at 08:00 PT a call due today is still pending.
    rows = _park_rows(_open("d", "2026-10-16"))
    assert cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-22"


def test_through_is_never_earlier_than_the_latest_counted_call():
    # An open call overdue since 10-10 cannot pull the day before a grade the record counts.
    rows = _park_rows(_open("d", "2026-10-03"))
    assert cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-18"


def test_open_rows_the_grader_does_not_owe_bound_nothing():
    rows = _park_rows(
        _open("tomb", "2026-10-10", phase="pilot", tombstone=True),  # an archived cycle's leftover
        {"prediction_id": "nodate", "sk": "PREDICTION#nodate", "status": "pending"},  # the grader skips it
        _open("bad", "2026-10-10", window_days="fortnight"),  # an undatable window
        _open("obs", "2026-10-10", status="observation"),  # never graded
    )
    assert cr.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-23"


def test_a_point_call_is_due_after_its_own_window_not_the_domain_minimum():
    point = _open("p", "2026-10-21", window_days=1)
    point["evaluation"]["type"] = "point"  # due 10-22, owed on 10-23
    assert cr.record_from_rows(_park_rows(point), genesis=GENESIS, as_of="2026-10-23")["through"] == "2026-10-21"


def test_the_default_as_of_is_the_one_clock_seam(monkeypatch):
    monkeypatch.setattr(cr, "today_pt", lambda: "2026-10-23")
    assert cr.record_from_rows(_park_rows(), genesis=GENESIS)["through"] == "2026-10-23"
    monkeypatch.setattr(cr, "today_pt", lambda: "2026-10-19")
    assert cr.record_from_rows(_park_rows(), genesis=GENESIS)["through"] == "2026-10-19"


def test_no_checked_call_has_no_through_and_career_keeps_the_latest_grade():
    assert cr.record_from_rows([_open("d", "2026-10-01")], genesis=GENESIS, as_of="2026-10-23")["through"] is None
    career = cr.record_from_rows(_park_rows(_open("d", "2026-10-01")), genesis=GENESIS, career=True, as_of="2026-10-23")
    assert career["through"] == "2026-10-18"


def test_the_partition_read_projects_the_fields_the_bound_reads():
    # for_coach reads a PROJECTED page: a due day needs created_date, subdomain and evaluation.
    projected = set(cr._PROJECTION_NAMES.values())
    assert {"created_date", "subdomain", "evaluation", "status"} <= projected

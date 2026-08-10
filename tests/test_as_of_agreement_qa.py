"""tests/test_as_of_agreement_qa.py — the #2414 runtime as_of sensor, offline.

Pure-assessor tests with FIXTURE dates only (no now-math — golden tests +
wall-clock is the midnight time-bomb class). The fetch/wrap half lives in
qa_smoke_lambda.check_as_of_agreement and is covered by the fault-isolation
harness like every other step.
"""

from operational.as_of_agreement_qa import (
    AS_OF_DATA_LAG_MAX_DAYS,
    assess_as_of,
    assess_as_of_data_correspondence,
    day_stamps,
    newest_data_day,
)

PT_TODAY = "2026-08-08"  # fixture: the PT-expected day


def test_ahead_stamp_is_a_violation():
    # #2392's measured live defect: observatory stamped the UTC (tomorrow) day.
    payload = {"as_of_date": "2026-08-09", "summary": {"x": 1}}
    verdict = assess_as_of(payload, PT_TODAY)
    assert verdict["stamps"] == 1
    assert len(verdict["violations"]) == 1
    assert "2026-08-09" in verdict["violations"][0] and PT_TODAY in verdict["violations"][0]


def test_today_and_behind_stamps_are_legal():
    payload = {
        "as_of_date": PT_TODAY,  # today: legal
        "habit_streaks": {"as_of_date": "2026-08-07"},  # behind (yesterday-keyed data): legal
    }
    verdict = assess_as_of(payload, PT_TODAY)
    assert verdict["stamps"] == 2
    assert verdict["violations"] == []


def test_nested_and_listed_stamps_are_found_with_paths():
    payload = {"cards": [{"as_of": "2026-08-10"}, {"as_of": "2026-08-08"}], "meta": {"deep": {"as_of_date": "2026-08-09"}}}
    stamps = dict(day_stamps(payload))
    assert stamps == {"$.cards[0].as_of": "2026-08-10", "$.cards[1].as_of": "2026-08-08", "$.meta.deep.as_of_date": "2026-08-09"}
    assert len(assess_as_of(payload, PT_TODAY)["violations"]) == 2


def test_instants_null_and_foreign_keys_are_skipped():
    payload = {
        "as_of": "2026-08-09T02:00:00+00:00",  # an instant is frame-free — not a day-stamp
        "as_of_date": None,  # honest empty state
        "last_updated": "2026-08-09",  # not an AS_OF key
        "date": "2026-08-09",  # data field, not a document stamp
    }
    verdict = assess_as_of(payload, PT_TODAY)
    assert verdict["stamps"] == 0
    assert verdict["violations"] == []


def test_zero_stamp_payload_is_ok_not_a_failure():
    assert assess_as_of({"anything": [1, 2, 3]}, PT_TODAY) == {"stamps": 0, "violations": []}


# ---------------------------------------------------------------------------
# #2379 — served-date correspondence (the complement: stamp vs the data served)
# ---------------------------------------------------------------------------
# The nightly emails the owner on a FAIL, so the negative cases below carry the
# same weight as the positive one: a legitimately-behind stamp must NOT fire.


# Shape lifted from the live /api/vitals payload (values redacted/synthetic):
# a document stamp plus the per-field data days it actually serves.
def _vitals_like(as_of, served_day):
    return {
        "_meta": {"generated_at": f"{as_of}T17:49:05.272288+00:00"},  # instant, not a day
        "vitals": {
            "as_of_date": as_of,
            "weight_as_of": served_day,
            "recovery_as_of": served_day,
            "night_of": served_day,
        },
    }


def test_stamp_far_ahead_of_served_data_is_a_violation():
    """#2379's class: stamped today while every dated field is last week's."""
    payload = _vitals_like("2026-08-08", "2026-07-29")  # 10d gap
    verdict = assess_as_of_data_correspondence(payload)
    assert verdict["newest_data_day"] == "2026-07-29"
    assert len(verdict["violations"]) == 1
    assert "as_of_date=2026-08-08" in verdict["violations"][0]
    assert "10d AHEAD" in verdict["violations"][0] and "2026-07-29" in verdict["violations"][0]
    # ...and it does NOT fire on the clock check, which is why #2414 misses it.
    assert assess_as_of(payload, "2026-08-08")["violations"] == []


def test_legitimately_behind_stamp_does_not_fire():
    """The healthy steady state + a quiet-source week: both must stay silent.

    A daily document stamped D over newest data D-1 is correct, and a stamp
    exactly AS_OF_DATA_LAG_MAX_DAYS ahead (a travel week / unworn strap) is a
    behavioural gap owned by the freshness tiers, not a lying stamp.
    """
    healthy = _vitals_like("2026-08-08", "2026-08-07")  # D-1: the normal build lag
    assert assess_as_of_data_correspondence(healthy)["violations"] == []

    day_late = _vitals_like("2026-08-08", "2026-08-06")  # D-2: a source landing a full day late
    assert assess_as_of_data_correspondence(day_late)["violations"] == []

    boundary = _vitals_like("2026-08-08", "2026-08-01")  # exactly the threshold — still legal
    assert (boundary["vitals"]["as_of_date"], boundary["vitals"]["night_of"]) == ("2026-08-08", "2026-08-01")
    assert assess_as_of_data_correspondence(boundary)["violations"] == []

    # Mutation proof that the boundary is the boundary, not a dead branch.
    over = _vitals_like("2026-08-08", "2026-07-31")  # one day past it
    assert len(assess_as_of_data_correspondence(over)["violations"]) == 1
    assert AS_OF_DATA_LAG_MAX_DAYS == 7


def test_stamp_behind_its_own_data_is_not_a_violation():
    """One-sided by design: a completed-day stamp may carry the day in progress."""
    payload = _vitals_like("2026-08-01", "2026-08-08")
    assert assess_as_of_data_correspondence(payload)["violations"] == []


def test_no_dated_data_or_no_stamp_is_a_zero_violation_ok():
    """Absence of data is not evidence of a lying stamp (empty states are honest)."""
    empty = {"vices": [], "total_held": 0, "as_of_date": "2026-08-08"}  # live /api/vice_streaks shape
    assert assess_as_of_data_correspondence(empty) == {"stamps": 1, "newest_data_day": None, "violations": []}
    unstamped = {"journey": {"last_weighin_date": "2026-07-01"}}  # live /api/journey shape: no as_of stamp
    assert assess_as_of_data_correspondence(unstamped)["violations"] == []


def test_newest_data_day_excludes_stamps_and_reads_lists():
    """The max is taken over data keys only — a stamp may never supply its own alibi."""
    assert newest_data_day({"as_of_date": "2026-08-09", "date": "2026-08-02"}) == "2026-08-02"
    assert newest_data_day({"as_of": ["2026-08-09"]}) is None  # list elements inherit the parent key
    assert newest_data_day({"days": ["2026-08-02", "2026-08-05"]}) == "2026-08-05"
    assert newest_data_day({"generated_at": "2026-08-09T02:00:00+00:00"}) is None  # instant, not a day

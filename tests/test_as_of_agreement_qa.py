"""tests/test_as_of_agreement_qa.py — the #2414 runtime as_of sensor, offline.

Pure-assessor tests with FIXTURE dates only (no now-math — golden tests +
wall-clock is the midnight time-bomb class). The fetch/wrap half lives in
qa_smoke_lambda.check_as_of_agreement and is covered by the fault-isolation
harness like every other step.
"""

from operational.as_of_agreement_qa import assess_as_of, day_stamps

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

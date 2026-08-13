"""tests/test_cross_surface_vitals_asof_2575.py — #2575: a frozen artifact vs a live
surface is not a comparison.

THE LIVE FAILURE, MEASURED 2026-08-12. #2583 had already removed the real defect (two
producers of "the current reading"), and `cross_surface:vitals` kept FAILing anyway —
this time with the numbers inverted, which is the tell:

    /api/coaching-dashboard  mind coach, created_at 2026-08-12T17:02:59Z:
        "your recovery came in at 54%, HRV at 41.1 ms, resting HR at 56 bpm"
    /api/vitals now:
        recovery_pct 30.0, hrv_ms 30.9, rhr_bpm 60.0, recovery_as_of 2026-08-12

    whoop DATE#2026-08-11   recovery 54, HRV 41.07, RHR 56
    whoop DATE#2026-08-12   recovery 30, HRV 30.9,  RHR 60

`vitals_resolver` serves the newest **FINALIZED** whoop morning — its own docstring
says the newest record can be unscored until the night's sleep syncs. At 17:02:59Z the
08-12 row was not scored, so the Spine correctly served 08-11; it finalized later, so
the cockpit correctly serves 08-12. Both surfaces were right at their own moment, and
the check could not pass on any day a recovery finalizes after the 17:00Z brief.

WHY "RE-RESOLVE AS OF created_at" CANNOT WORK. Nothing in DynamoDB records when a row
became scored. Replaying 17:02:59Z against the table today finds DATE#2026-08-12 both
scored and dated on-or-before that instant, so it returns 30 — the number the coach
provably did not have. The only way to know what the Spine served at publication is to
write it down then: `coach/published_vitals.stamp_published_vitals`.

WHAT THIS FILE PROVES — both directions, because the load-bearing half is the second:
  * a pure TIME GAP no longer fires (the real 2026-08-12 payloads, verbatim);
  * a real DISAGREEMENT still fires, under every shape the exemption could be abused
    in: prose that matches neither reading, no stamp at all, a stamp from a lagging
    producer two mornings back, a stamp for the same morning as the cockpit, a stamp
    that is malformed or claims to be newer than the cockpit.

Every fallback lands on the pre-#2575 behaviour (judge against the live cockpit), so a
stamp that is never written can only make the check stricter, never blind.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import published_vitals as pv  # noqa: E402
from operational import weight_truth_qa as wq  # noqa: E402

# ── The real payloads, at the values the two surfaces actually held on 2026-08-12 ──

# /api/vitals, fetched 2026-08-12 (verbatim field names, the numbers as served).
COCKPIT = {
    "recovery_pct": 30.0,
    "recovery_as_of": "2026-08-12",
    "hrv_ms": 30.9,
    "rhr_bpm": 60.0,
    "sleep_hours": 7.3,
    "sleep_as_of": "2026-08-12",
    "weight_lbs": 317.0,
}

# The mind coach's published card, and the stamp `_write_output_record` now freezes
# alongside it: the Spine's own answer at 17:02:59Z, which was DATE#2026-08-11.
_MIND_PROSE = "On the night of 2026-08-10, your recovery came in at 54%, HRV at 41.1 ms, resting HR at 56 bpm — but those are well below your baseline."
_PUBLISHED_08_11 = {
    "recovery_pct": 54.0,
    "hrv_ms": 41.07,
    "rhr_bpm": 56.0,
    "recovery_as_of": "2026-08-11",
    "sleep_hours": 6.8,
    "sleep_as_of": "2026-08-11",
}


def _coach(prose=_MIND_PROSE, stamp=_PUBLISHED_08_11, name="Dr. Nathan Reeves"):
    c = {"name": name, "position_summary": prose}
    if stamp is not None:
        c["published_vitals"] = stamp
    return c


# ══════════════════════════════════════════════════════════════════════════════
# DIRECTION 1 — a pure time gap must not fire
# ══════════════════════════════════════════════════════════════════════════════


def test_the_measured_2026_08_12_payload_no_longer_fires():
    """The exact live pair that reopened #2575. Both surfaces correct, one morning apart."""
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach()])
    assert ok, msg
    # And the old rule genuinely did fire on it — otherwise this test proves nothing.
    was_ok, was_msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=None)])
    assert not was_ok and "recovery 54" in was_msg, was_msg


def test_sleep_rides_its_own_as_of_not_recoverys():
    """Sleep finalizes separately (#1369), so it is exempted on `sleep_as_of` alone."""
    coach = _coach(prose="You slept 6.8 hours last night, which is short of the 8 you need.")
    assert wq.assess_cross_surface_vitals(COCKPIT, [coach])[0]
    # …and a sleep figure matching NEITHER reading still fails.
    bad = _coach(prose="You slept 4.1 hours last night.")
    assert not wq.assess_cross_surface_vitals(COCKPIT, [bad])[0]


# ══════════════════════════════════════════════════════════════════════════════
# DIRECTION 2 — the load-bearing half: a real disagreement must still fire
# ══════════════════════════════════════════════════════════════════════════════


def test_prose_that_matches_neither_reading_still_fails():
    """The whole point. A stamp exempts the TIME GAP, never the coach's arithmetic."""
    coach = _coach(prose="your recovery came in at 61%, HRV at 47.2 ms")
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [coach])
    assert not ok
    assert "recovery 61" in msg and "as published 2026-08-11" in msg, msg


def test_an_unstamped_coach_is_judged_against_the_live_cockpit():
    """A stamp that never gets written cannot make the check go dark."""
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=None)])
    assert not ok and "cockpit" in msg, msg


def test_a_stamp_two_mornings_behind_still_fails_the_original_2575_defect():
    """One morning is the whole finalization window. Two is a lagging producer."""
    stale = dict(_PUBLISHED_08_11, recovery_as_of="2026-08-10", sleep_as_of="2026-08-10")
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=stale)])
    assert not ok and "cockpit 30" in msg, msg
    assert wq.VITALS_ASOF_MAX_LAG_DAYS == 1


def test_same_morning_on_both_sides_keeps_the_old_strictness_exactly():
    """No gap to reconcile ⇒ the cockpit judges, byte-for-byte as before #2575."""
    same_day = dict(_PUBLISHED_08_11, recovery_as_of="2026-08-12", sleep_as_of="2026-08-12")
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=same_day)])
    assert not ok and "cockpit 30" in msg, msg
    # …and the same-morning coach that agrees passes, as it always did.
    agreeing = _coach(prose="your recovery came in at 30%, HRV at 30.9 ms", stamp=same_day)
    assert wq.assess_cross_surface_vitals(COCKPIT, [agreeing])[0]


def test_a_stamp_claiming_to_be_newer_than_the_cockpit_grants_nothing():
    """Forward-dated provenance is not a licence — the cockpit stays the judge."""
    future = dict(_PUBLISHED_08_11, recovery_as_of="2026-08-13", sleep_as_of="2026-08-13")
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=future)])
    assert not ok and "cockpit 30" in msg, msg


def test_malformed_stamps_fall_back_to_the_cockpit_never_to_a_pass():
    for broken in ("not-a-dict", [], {}, {"recovery_as_of": "yesterday", "recovery_pct": 54.0}, {"recovery_as_of": "2026-08-11"}):
        ok, msg = wq.assess_cross_surface_vitals(COCKPIT, [_coach(stamp=broken)])
        assert not ok, f"{broken!r} was let through: {msg}"


def test_absence_on_the_cockpit_side_is_still_a_clean_pass():
    """ADR-104 unchanged: a null cockpit column has nothing to contradict."""
    dark = {k: v for k, v in COCKPIT.items() if k not in ("recovery_pct", "hrv_ms", "rhr_bpm")}
    assert wq.assess_cross_surface_vitals(dark, [_coach()])[0]
    assert wq.assess_cross_surface_vitals({}, [_coach()])[0]


# ══════════════════════════════════════════════════════════════════════════════
# The writer half — the stamp must exist, and in the checker's vocabulary
# ══════════════════════════════════════════════════════════════════════════════


class _FakeSpine:
    def __init__(self, payload):
        self.payload = payload

    def resolve_vitals(self, table, user_prefix, now=None):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _with_spine(monkeypatch, payload):
    import web.vitals_resolver as real

    monkeypatch.setattr(real, "resolve_vitals", _FakeSpine(payload).resolve_vitals)


def test_the_writer_stamps_the_spines_answer_in_the_checkers_field_names(monkeypatch):
    _with_spine(
        monkeypatch,
        {
            "recovery_pct": 54.0,
            "hrv_ms": 41.07,
            "rhr_bpm": 56.0,
            "recovery_as_of": "2026-08-11",
            "sleep_hours": 6.8,
            "sleep_as_of": "2026-08-11",
            "steps": 2797,
        },
    )
    item = {"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-08-12#daily"}
    stamp = pv.stamp_published_vitals(item, None, "USER#matthew#SOURCE#")
    assert item["published_vitals"] == stamp
    # ONE seam: every field the checker reads must be a field the writer writes.
    for metric in wq._STAMP_VALUE_FIELD:
        assert wq._STAMP_VALUE_FIELD[metric] in stamp
        assert wq._STAMP_ASOF_FIELD[metric] in stamp
    assert "steps" not in stamp  # only what the check compares


def test_a_reading_with_no_provenance_date_is_never_stamped(monkeypatch):
    """A frozen number with no as-of would be compared as if it were current."""
    _with_spine(monkeypatch, {"recovery_pct": 54.0, "hrv_ms": 41.07, "recovery_as_of": None, "sleep_as_of": None})
    item = {}
    assert pv.stamp_published_vitals(item, None, "USER#matthew#SOURCE#") == {}
    assert "published_vitals" not in item


def test_a_resolver_blowup_stamps_nothing_and_never_breaks_the_write(monkeypatch):
    _with_spine(monkeypatch, RuntimeError("DDB throttled"))
    item = {"pk": "COACH#mind_coach"}
    assert pv.stamp_published_vitals(item, None, "USER#matthew#SOURCE#") == {}
    assert "published_vitals" not in item


def test_the_writer_actually_calls_the_stamp():
    """A stamp nothing writes is a check that silently reverts to the live comparison."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "lambdas", "coach", "coach_state_updater.py"), encoding="utf-8").read()
    assert "published_vitals.stamp_published_vitals(item" in src
    api = open(os.path.join(root, "lambdas", "web", "site_api_lambda.py"), encoding="utf-8").read()
    assert '"published_vitals"' in api, "the dashboard must serve the stamp or the check can never see it"

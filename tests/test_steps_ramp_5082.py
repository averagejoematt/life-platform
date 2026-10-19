"""tests/test_steps_ramp_5082.py — the ramp to the charter steps floor and the lower-leg hold (#5082).

The window is the WIRE: the six real days of tests/fixtures/steps_resolver_5081/days.json (Decimal, as boto3
returns them) read through `steps_resolver.steps_range`, so the ramp is exercised over the resolver's own output —
a no-source day, a fallback day, an open-cycle (`partial_day`) day — not over a hand-made list.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

for _k, _v in (("TABLE_NAME", "life-platform-test"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)

from training import deload_word, plan_engine, steps_ramp, steps_resolver, training_charter, training_context_registry  # noqa: E402

DAYS = json.loads((ROOT / "tests" / "fixtures" / "steps_resolver_5081" / "days.json").read_text(), parse_float=Decimal, parse_int=Decimal)[
    "days"
]


def _fetch(source: str, start: str, end: str):
    rows = []
    for d, by in DAYS.items():
        if start <= d <= end and by.get(source):
            v = by[source]
            rows += v if isinstance(v, list) else [v]
    return rows


def _real(date: str, **kw):
    return steps_ramp.steps_ramp_for(date, fetch=_fetch, **kw)


def _synthetic(date: str, counts: list):
    """A resolver-shaped window from [count|None, ...] (oldest first) ending the day before `date`."""
    from common.pacific_time import shift_day_key

    n = len(counts)
    days = []
    for i, c in enumerate(counts):
        d = shift_day_key(date, -(n - i))
        days.append(
            {"date": d, "steps": c, "winner": "whoop" if c is not None else None, "degraded": None if c is not None else "no_source"}
        )
    return {"days": days}


def _dismissal(site: str, on: str, flag_note: str, movement: str):
    rec = training_context_registry.build_dismissal_record(
        site=site, dismissed_on=on, words="it is gone", movements=[movement], flag_note_date=flag_note, recorded_at=on + "T12:00:00Z"
    )
    return rec


CALF = [
    {"movement": "Calf Raise", "note_dates": ["2026-10-10"], "notes": [{"date": "2026-10-10", "text": "left calf tight on the last set"}]}
]


def test_ramp_from_real_days_states_its_derivation():
    """Mutation: start from the floor, or average the days with no count in as zeros (3 real days of 14 would read ~2.2k)."""
    out = _real("2026-10-15")
    assert out["trailing_avg"] == 10072 and out["days_counted"] == 3  # (3420 + 9057 + 17739) / 3
    assert out["excluded_days"] == {"no_source": 11, "partial_day": 0}
    assert (out["step_per_week"], out["level"], out["today_target"], out["state"]) == (1100, 11100, 11100, "ramping")
    assert out["stretch_target"] is None and out["held_by"] == [] and out["floor"] == training_charter.charter_value("steps.floor")
    assert out["charter_version"] == training_charter.charter_version() and "step_per_week = max(10%" in out["derivation"]
    assert out["window_days"] == training_charter.charter_value("steps.ramp.ramp_window_days") == 14


def test_the_floor_is_reached_in_at_most_six_weeks_from_any_base():
    """Mutation: drop the cap term (a 3,000 average at +10 %/wk needs 16 weeks). One test, every base reported."""
    bad = []
    for base in (1500, 3000, 5000, 8000, 11000):
        out = steps_ramp.compute("2026-10-20", _synthetic("2026-10-20", [base] * 14))
        if out["weeks_to_floor"] > steps_ramp.RAMP_MAX_WEEKS or out["level"] <= base:
            bad.append((base, out["weeks_to_floor"], out["level"]))
    assert not bad, bad


def test_degraded_days_are_excluded_and_counted():
    """Mutation: count the open-cycle day (a floor, still accruing) or a no-source day as a measured one."""
    out = _real("2026-10-19")  # window 10-05..10-18: 10-18 is partial_day
    assert out["excluded_days"]["partial_day"] == 1 and out["days_counted"] == 3
    assert out["trailing_avg"] == round((9057 + 17739 + 17866) / 3)
    one = _real("2026-09-21")  # one measured day (a fallback source) in 14 -> no baseline: hold, invent no level
    assert one["days_counted"] == 1 and one["state"] == "holding" and "no_baseline" in one["held_by"] and one["today_target"] is None


def test_at_floor_then_target_once_the_floor_has_held_seven_days():
    """Mutation: unlock the 15,000 stretch on an average at the floor without seven consecutive floor days."""
    steady = steps_ramp.compute("2026-10-20", _synthetic("2026-10-20", [13000] * 14))
    assert (steady["state"], steady["today_target"], steady["stretch_target"]) == ("at_target", 12000, 15000)
    uneven = steps_ramp.compute("2026-10-20", _synthetic("2026-10-20", [16000] * 9 + [9000] + [14000] * 4))
    assert uneven["floor_held_days"] == 4 and (uneven["state"], uneven["stretch_target"]) == ("at_floor", None)


def test_a_lower_leg_flag_holds_the_ramp_at_its_current_step():
    """Mutation: let the level climb while a calf note is inside the quiet period."""
    base = _real("2026-10-15")
    held = _real("2026-10-15", pain_flag_instances=CALF, prior_level=10500)
    assert held["state"] == "holding" and held["held_by"] == ["strain_flag:Calf Raise"]
    assert held["level"] == held["today_target"] == 10500 < base["level"]
    assert held["released_on"] is None and held["step_per_week"] == base["step_per_week"]


def test_a_flag_on_another_site_holds_nothing():
    """Mutation: hold on any pain flag (a shoulder note is not a lower-leg load problem)."""
    shoulder = [
        {"movement": "Overhead Press", "note_dates": ["2026-10-10"], "notes": [{"date": "2026-10-10", "text": "right shoulder pinch"}]}
    ]
    assert _real("2026-10-15", pain_flag_instances=shoulder)["state"] == "ramping"


def test_release_by_owner_dismissal_and_by_the_quiet_period_and_rearm():
    """Mutation: never release; release on a dismissal a later note superseded; or ignore the 14-day quiet period."""
    dis = [_dismissal("left calf", "2026-10-12", "2026-10-10", "Calf Raise")]
    out = _real("2026-10-15", pain_flag_instances=CALF, pain_dismissals=dis)
    assert out["state"] == "ramping" and out["held_by"] == [] and out["released_on"] == "2026-10-12"
    again = CALF[0] | {
        "note_dates": ["2026-10-10", "2026-10-14"],
        "notes": CALF[0]["notes"] + [{"date": "2026-10-14", "text": "left calf again"}],
    }
    assert _real("2026-10-15", pain_flag_instances=[again], pain_dismissals=dis)["state"] == "holding"
    old = [CALF[0] | {"note_dates": ["2026-10-01"], "notes": [{"date": "2026-10-01", "text": "calf tight"}]}]
    assert _real("2026-10-14", pain_flag_instances=old)["state"] == "holding"  # note 10-01 + 14 days = 10-15, still inside
    quiet = _real("2026-10-15", pain_flag_instances=old)
    assert quiet["state"] == "ramping" and quiet["released_on"] == "2026-10-15"


def test_the_standing_calf_entry_is_read_and_honoured(monkeypatch):
    """Mutation: skip the registry. Today's entry is resolved (owner 2026-09-20) so it holds nothing but is NAMED; an
    active lower-leg entry holds."""
    out = _real("2026-10-15")
    assert {"id": "calf_lesion", "status": "resolved", "resolved_on": "2026-09-20"} in out["standing_constraints_read"] and not out[
        "held_by"
    ]
    active = [{**c, "status": "active", "resolved_on": None} for c in training_context_registry.RECORDED_CONSTRAINTS]
    monkeypatch.setattr(training_context_registry, "RECORDED_CONSTRAINTS", active)
    assert _real("2026-10-15")["held_by"] == ["standing_constraint:calf_lesion"]


def test_an_owner_deload_record_holds_the_ramp():
    """Mutation: climb the step target through a deload the owner recorded."""
    rec = [{"start_date": "2026-10-13", "days": 7}]
    assert deload_word.active_record(rec, "2026-10-15")
    out = _real("2026-10-15", deload_records=rec)
    assert out["state"] == "holding" and out["held_by"] == ["deload_record:2026-10-13"]


def test_constraint_block_carries_the_ramp_and_states_an_unread_window():
    """Mutation: build a target on an unread window, or drop the key from the block."""
    window = steps_resolver.steps_range("2026-10-01", "2026-10-14", fetch=_fetch, derived=False)
    block = plan_engine.constraint_block(date="2026-10-15", steps_window=window, pain_flag_instances=CALF)
    assert block["steps_ramp"]["state"] == "holding" and block["steps_ramp"]["trailing_avg"] == 10072
    assert block["inputs"]["steps_window"]["state"] == "not_supplied"
    unread = plan_engine.constraint_block(date="2026-10-15")["steps_ramp"]
    assert unread["state"] == "unknown" and unread["charter_version"] == training_charter.charter_version()
    failed = plan_engine.constraint_block(
        date="2026-10-15",
        steps_window=window,
        input_status={"pain_dismissals": plan_engine.input_status(plan_engine.READ_FAILED, error="X")},
    )["steps_ramp"]
    assert failed["state"] == "unknown" and "pain_dismissals read failed" in failed["reason"]

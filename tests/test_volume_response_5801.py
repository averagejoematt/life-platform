"""tests/test_volume_response_5801.py — the block-end volume-response report (#5801). Synthetic fixtures, no real loads.

The fixture has the wire shape: `extract_hevy_sessions` sessions (date, best_1rm, identity, template_id) and
`working_sets_by_muscle(...)["muscles"]` totals, built from raw-shaped Hevy items (the `type` set field).
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

from training import muscle_volume, plan_engine, volume_response as vr  # noqa: E402


def _sessions(e1rms, ident="TID1"):
    return [{"date": f"2026-10-{i + 1:02d}", "best_1rm": v, "identity": ident, "template_id": ident} for i, v in enumerate(e1rms)]


def _lift(name, e1rms, tid="TID1"):
    return {"name": name, "template_id": tid, "sessions": _sessions(e1rms, tid)}


RISING = [100, 100, 100, 100, 100, 100, 110, 112, 114]  # baseline median 100, recent 112
FALLING = [100, 100, 100, 100, 100, 100, 90, 88, 86]
NOISY = [100, 100, 100, 100, 100, 100, 101, 102, 101]
SHORT = [100, 101, 102]


def _totals(**kw):
    return {m: {"total_sets": float(v)} for m, v in kw.items()}


def test_response_uses_the_existing_trend_and_the_tripwire_noise_line():
    r = vr.lift_response(_sessions(RISING))
    t = plan_engine.anchor_e1rm_trend(RISING)
    assert (r["baseline_e1rm_lb"], r["recent_e1rm_lb"]) == (t["baseline_median_e1rm_lb"], t["recent_median_e1rm_lb"])
    assert r["label"] == vr.GAINING and r["change_pct"] == 12.0 and r["n_sessions"] == 9
    assert r["noise_pct"] == vr.noise_pct()
    assert vr.lift_response(_sessions(FALLING))["label"] == vr.LOSING


def test_inside_noise_is_flat_and_the_proposal_is_insufficient_evidence():
    rep = vr.build_report("2026-11-01", weeks=4, muscle_totals=_totals(Chest=40), lifts=[_lift("Bench Press (Barbell)", NOISY)])
    row = rep["muscles"][0]
    assert row["response"] == vr.FLAT and row["proposal"]["status"] == vr.INSUFFICIENT and "sets_per_wk" not in row["proposal"]


def test_too_few_sessions_is_unmeasured_not_flat():
    r = vr.lift_response(_sessions(SHORT))
    assert r["label"] == vr.UNMEASURED and "needs" in r["reason"]


def test_gaining_holds_and_losing_steps_down_inside_band_and_ceiling():
    lo, hi = vr.band_for("Chest")[0], vr.weekly_ceiling()
    up = vr.build_report("d", weeks=4, muscle_totals=_totals(Chest=40, Back=100), lifts=[_lift("Bench Press (Barbell)", RISING)])
    assert up["muscles"][0]["proposal"] == {**up["muscles"][0]["proposal"], "status": vr.HOLD, "sets_per_wk": 10}
    down = vr.build_report("d", weeks=4, muscle_totals=_totals(Chest=48), lifts=[_lift("Bench Press (Barbell)", FALLING)])
    assert down["muscles"][0]["proposal"]["sets_per_wk"] == 10  # 12 performed, 2 fewer
    low = vr.build_report("d", weeks=4, muscle_totals=_totals(Chest=32), lifts=[_lift("Bench Press (Barbell)", FALLING)])
    assert low["muscles"][0]["proposal"]["sets_per_wk"] == lo  # 8 - 2 floors at the band bottom
    over = vr.build_report("d", weeks=1, muscle_totals=_totals(Chest=30), lifts=[_lift("Bench Press (Barbell)", RISING)])
    assert over["muscles"][0]["proposal"]["sets_per_wk"] == hi  # held, but never above the ceiling


def test_disagreeing_lifts_and_bandless_muscles_are_insufficient():
    mixed = vr.build_report(
        "d",
        weeks=4,
        muscle_totals=_totals(Chest=40),
        lifts=[_lift("Bench Press (Barbell)", RISING, "A"), _lift("Incline Bench Press (Dumbbell)", FALLING, "B")],
    )
    assert mixed["muscles"][0]["response"] == vr.MIXED and mixed["muscles"][0]["proposal"]["status"] == vr.INSUFFICIENT
    calves = vr.build_report("d", weeks=4, muscle_totals=_totals(Calves=30), lifts=[_lift("Standing Calf Raise", RISING)])
    assert calves["muscles"][0]["band"] is None and calves["muscles"][0]["proposal"]["status"] == vr.INSUFFICIENT


def test_variant_switch_is_cut_to_the_latest_identity():
    sess = _sessions([200] * 9, "OLD") + [
        dict(s, identity="NEW", date=s["date"].replace("-10-", "-11-")) for s in _sessions([100, 100, 100], "NEW")
    ]
    assert vr.lift_response(sess)["label"] == vr.UNMEASURED  # 3 sessions of the new identity: no trend, never a "drop"


def test_wire_shaped_workouts_feed_the_report_and_it_is_advisory_and_stated():
    items = [
        {
            "date": f"2026-10-{d:02d}",
            "exercises": [
                {
                    "title": "Bench Press (Barbell)",
                    "exercise_template_id": "TID1",
                    "sets": [{"type": "normal", "weight_kg": 50, "reps": 8}] * 3,
                }
            ],
        }
        for d in (5, 12)
    ]
    wk = muscle_volume.normalize_hevy_items(
        [{"pk": "USER#matthew#SOURCE#hevy", "sk": f"DATE#{i['date']}#WORKOUT#w{n}", **i} for n, i in enumerate(items)]
    )
    counted = muscle_volume.working_sets_by_muscle(wk, "2026-10-05", "2026-10-18")
    rep = vr.build_report("2026-10-18", weeks=2, muscle_totals=counted["muscles"], lifts=[_lift("Bench Press (Barbell)", RISING, "TID1")])
    assert rep["applied"] is False and rep["muscles"][0]["muscle"] == "Chest"
    md = vr.render_markdown(rep)
    assert "never applied" in md and "n = 9 sessions" in md and "caused" in md and "cause" in rep["caveat"]

"""#5861 L3 — `training.fatigue_model`: fatigue and recovery as first-class inputs, every threshold labelled.

Synthetic profiles only (no personal data): template ids `T_SQ` (free-weight squat), `T_DL` (conventional deadlift),
`T_RDL` (RDL), `T_LR` (machine lateral raise). Every rule carries a must-fail control: flip the one input, the verdict flips.
Nothing reads the clock: every call names its own `as_of`.
"""

from __future__ import annotations

import copy
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    fatigue_model as fm,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

AS_OF = "2026-11-12"
LIB = {
    "status": "proposed",
    "movements": {
        "sq": {
            "template_id": "T_SQ",
            "title": "Squat (Barbell)",
            "target": {"primary": "quadriceps", "secondary": ["glutes", "adductors"]},
            "pattern": "squat",
            "job": "compound",
            "resistance_profile": "free_weight",
            "joint_stress": {"spinal_load": "high"},
        },
        "dl": {
            "template_id": "T_DL",
            "title": "Deadlift (Barbell)",
            "target": {"primary": "hamstrings", "secondary": ["glutes", "back"]},
            "pattern": "hinge",
            "job": "compound",
            "resistance_profile": "free_weight",
            "joint_stress": {"spinal_load": "high"},
        },
        "rdl": {
            "template_id": "T_RDL",
            "title": "Romanian Deadlift (Barbell)",
            "target": {"primary": "hamstrings", "secondary": ["glutes"]},
            "pattern": "hinge",
            "job": "compound",
            "resistance_profile": "free_weight",
            "joint_stress": {"spinal_load": "high"},
        },
        "lr": {
            "template_id": "T_LR",
            "title": "Lateral Raise (Machine)",
            "target": {"primary": "shoulders", "secondary": []},
            "pattern": "lateral_raise",
            "job": "isolation",
            "resistance_profile": "machine_selectorized",
            "joint_stress": {"spinal_load": "low"},
        },
    },
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _ex(tid: str, load: float, reps: int, rpe: float | None = 8.0, n: int = 3, notes: str = "") -> dict:
    return {"template_id": tid, "title": tid, "notes": notes, "sets": [{"type": "normal", "weight_kg": load, "reps": reps, "rpe": rpe}] * n}


def _w(day: str, *exercises: dict) -> dict:
    return {"date": day, "exercises": list(exercises)}


INDEX = fm.library_index(LIB)


# ── thresholds: every one labelled ───────────────────────────────────────────
def test_every_threshold_is_labelled_heuristic_or_validated_with_a_basis():
    for k, t in fm.THRESHOLDS.items():
        assert t["label"] in (fm.HEURISTIC, fm.VALIDATED), k
        assert str(t.get("basis") or "").strip(), k
    # nothing is validated today (no verified outcome citation behind any number)
    assert not [k for k, t in fm.THRESHOLDS.items() if t["label"] == fm.VALIDATED]


# ── weekly hard sets, fractional secondary credit ────────────────────────────
def test_hard_sets_credit_primary_one_and_secondary_half():
    sets = fm.hard_sets_by_muscle([_w("2026-11-10", _ex("T_SQ", 80, 5, n=3))], INDEX, as_of=AS_OF)
    assert sets == {"adductors": 1.5, "glutes": 1.5, "quadriceps": 3.0}


def test_an_easy_set_is_not_hard_and_an_unlogged_rpe_is():
    easy = fm.hard_sets_by_muscle([_w("2026-11-10", _ex("T_LR", 10, 12, rpe=5.0, n=2))], INDEX, as_of=AS_OF)
    unlogged = fm.hard_sets_by_muscle([_w("2026-11-10", _ex("T_LR", 10, 12, rpe=None, n=2))], INDEX, as_of=AS_OF)
    assert easy == {} and unlogged == {"shoulders": 2.0}  # control: the RPE alone flips it


def test_hard_sets_window_is_seven_days_and_an_unplaced_template_is_never_guessed():
    rows = [
        _w("2026-11-05", _ex("T_LR", 10, 12, n=2)),
        _w("2026-11-06", _ex("T_LR", 10, 12, n=2)),
        _w("2026-11-10", _ex("T_X", 5, 10, n=1)),
    ]
    assert fm.hard_sets_by_muscle(rows, INDEX, as_of=AS_OF) == {"shoulders": 2.0, "unplaced": 1.0}


# ── the performed trend per movement ─────────────────────────────────────────
def _series(loads, rpe=9.0, reps=5):
    days = ["2026-10-20", "2026-10-27", "2026-11-03", "2026-11-10"]
    return [_w(days[i], _ex("T_SQ", load, reps, rpe=rpe)) for i, load in enumerate(loads)]


@pytest.mark.parametrize(
    "loads, rpe, want",
    [
        ([60, 62, 64], 9.0, "progressing"),
        ([64, 62, 63], 9.0, "stalled"),
        ([70, 70, 60, 60], 9.0, "regressing"),
        ([60, 60, 60], 7.0, "step_due"),
        ([60], 9.0, "unknown"),
    ],
)
def test_trend(loads, rpe, want):
    assert fm.movement_signals(_series(loads, rpe), as_of=AS_OF)["T_SQ"]["trend"] == want


def test_step_due_is_not_a_stall_control():
    # the same flat series at a HARD effort is a stall; at an easy effort it is the prescription holding still (#5057)
    assert fm.movement_signals(_series([60, 60, 60], 9.0), as_of=AS_OF)["T_SQ"]["trend"] == "stalled"
    assert fm.movement_signals(_series([60, 60, 60], 7.0), as_of=AS_OF)["T_SQ"]["trend"] == "step_due"


def test_discomfort_counts_only_inside_its_window_and_pain_is_separate():
    rows = [
        _w("2026-10-20", _ex("T_LR", 10, 12, notes="left elbow achy today")),  # outside 14 days
        _w("2026-11-03", _ex("T_LR", 10, 12, notes="left elbow achy today")),
        _w("2026-11-10", _ex("T_LR", 10, 12, notes="sharp pain in shoulder")),
    ]
    sig = fm.movement_signals(rows, as_of=AS_OF)["T_LR"]
    assert sig["discomfort_sessions"] == 1 and sig["pain_sessions"] == 1


# ── stacking ─────────────────────────────────────────────────────────────────
def test_squat_deadlift_rdl_inside_72h_is_axial_stacking_and_two_hinges_in_48h_is_hinge_stacking():
    rows = [_w("2026-11-10", _ex("T_SQ", 80, 5)), _w("2026-11-11", _ex("T_DL", 100, 5)), _w("2026-11-12", _ex("T_RDL", 70, 8))]
    found = {f["finding"] for f in fm.axial_stacking(rows, INDEX, as_of=AS_OF)}
    assert found == {"axial_stacking", "hinge_stacking"}
    # control: the same three spread over a week is no stack
    spread = [_w("2026-11-04", _ex("T_SQ", 80, 5)), _w("2026-11-07", _ex("T_DL", 100, 5)), _w("2026-11-12", _ex("T_RDL", 70, 8))]
    assert fm.axial_stacking(spread, INDEX, as_of=AS_OF) == []


def test_a_machine_isolation_never_stacks():
    rows = [_w("2026-11-10", _ex("T_LR", 10, 12)), _w("2026-11-11", _ex("T_LR", 10, 12)), _w("2026-11-12", _ex("T_LR", 10, 12))]
    assert fm.axial_stacking(rows, INDEX, as_of=AS_OF) == []


# ── the decision ─────────────────────────────────────────────────────────────
def _assess(**kw):
    base = {"workouts": [_w("2026-11-10", _ex("T_LR", 10, 12))], "lib": LIB, "as_of": AS_OF, "readiness": "green", "sleep_hours": 7.5}
    return fm.assess(**(base | kw))


def test_a_recovered_week_maintains_and_never_adds():
    a = _assess()
    assert a["action"] == "maintain" and a["reduce_sets"] == 0 and a["never_adds"] is True and not a["deload"]["recommended"]


def test_one_strain_signal_is_noise_two_reduce_three_recommend_a_deload():
    assert _assess(readiness="red")["action"] == "maintain"  # one signal
    two = _assess(readiness="red", sleep_hours=5.0)
    assert two["action"] == "reduce" and two["reduce_sets"] == 2 and two["state"] == "strained"
    three = _assess(readiness="red", sleep_hours=5.0, cardio_load={"state": "high", "source": "synthetic"})
    assert three["action"] == "deload_recommended" and three["deload"]["recommended"] and three["reduce_sets"] == 4
    assert "owner-confirmed" in three["deload"]["applies"]


def test_regressing_compound_on_a_red_day_recommends_a_deload_control_green_day():
    rows = _series([70, 70, 60, 60])
    assert _assess(workouts=rows, readiness="red")["deload"]["recommended"]
    assert not _assess(workouts=rows, readiness="green")["deload"]["recommended"]


def test_reduce_sets_is_never_positive_volume():
    for kw in ({}, {"readiness": "red", "sleep_hours": 4.0}, {"cardio_load": {"state": "high"}, "readiness": "red", "sleep_hours": 4.0}):
        assert _assess(**kw)["reduce_sets"] >= 0  # a count of sets TAKEN OFF; the model has no add path


def test_rebaselining_readiness_is_unknown_not_strain():
    a = _assess(readiness="re-baselining", sleep_hours=5.0)
    assert {s["signal"]: s["state"] for s in a["signals"]}["readiness"] == "unknown" and a["action"] == "maintain"


def test_repeated_discomfort_names_a_swap_control_one_note():
    two = [
        _w("2026-11-03", _ex("T_LR", 10, 12, notes="left elbow achy today")),
        _w("2026-11-10", _ex("T_LR", 10, 12, notes="left elbow achy")),
    ]
    assert [s["movement_id"] for s in _assess(workouts=two)["swaps"]] == ["lr"]
    assert _assess(workouts=two[1:])["swaps"] == []


def test_weekly_sets_over_the_mrv_landmark_is_strain_and_no_landmark_is_unknown():
    rows = [_w("2026-11-10", _ex("T_LR", 10, 12, n=8)), _w("2026-11-11", _ex("T_LR", 10, 12, n=8))]
    over = {s["signal"]: s for s in _assess(workouts=rows, landmarks={"shoulders": {"MRV": 12}})["signals"]}["weekly_sets"]
    under = {s["signal"]: s for s in _assess(workouts=rows, landmarks={"shoulders": {"MRV": 22}})["signals"]}["weekly_sets"]
    unread = {s["signal"]: s for s in _assess(workouts=rows)["signals"]}["weekly_sets"]
    assert (over["state"], under["state"], unread["state"]) == ("strain", "ok", "unknown")


def test_session_minutes_over_the_ceiling_is_reported():
    assert _assess(session_minutes=80, minutes_ceiling=75)["session_minutes"]["over"] is True
    assert _assess(session_minutes=70, minutes_ceiling=75)["session_minutes"]["over"] is False


def test_adherence_low_is_reported_and_never_adds():
    a = _assess(workouts=[_w("2026-11-10", _ex("T_LR", 10, 12))], planned_per_week=5)
    assert a["adherence"]["state"] == "low" and a["reduce_sets"] == 0 and a["action"] == "maintain"


# ── the live draft hook ──────────────────────────────────────────────────────
def _rx() -> dict:
    return {
        "exposures": [
            {"kind": "anchor", "intensity": "heavy", "sets": [{"kind": "top"}, {"kind": "back_off"}, {"kind": "back_off"}]},
            {"kind": "accessory", "intensity": "accessory", "sets": [{"kind": "working"}, {"kind": "working"}, {"kind": "working"}]},
            {"kind": "accessory", "intensity": "accessory", "sets": [{"kind": "working"}, {"kind": "working"}]},
        ],
        "total_sets": 8,
        "session_minutes": {"lifting_minutes": 40.0},
    }


def test_shadow_returns_the_prescription_itself():
    rx = _rx()
    strained = _assess(readiness="red", sleep_hours=4.0)
    for mode in ("shadow", "no_library", None):
        assert fm.apply_to_session(rx, {"selection": {"mode": mode}}, strained) is rx
    assert fm.for_live_draft(rx, {"selection": {"mode": "shadow"}}, object(), None) is rx


def test_live_reduction_takes_accessory_sets_only_and_holds_every_anchor_set():
    rx = _rx()
    out = fm.apply_to_session(rx, {"selection": {"mode": "live"}}, _assess(readiness="red", sleep_hours=4.0))
    assert out is not rx and rx["total_sets"] == 8  # a copy: the input is untouched
    assert [len(e["sets"]) for e in out["exposures"]] == [3, 2, 1] and out["total_sets"] == 6
    assert out["fatigue"]["sets_removed"] == 2 and out["fatigue"]["action"] == "reduce"


def test_trim_never_drops_an_accessory_below_one_set_or_touches_a_top_set():
    rx = _rx()
    removed = fm.trim_accessory_sets(rx["exposures"], 50)
    assert removed == 3 and [len(e["sets"]) for e in rx["exposures"]] == [3, 1, 1]
    assert rx["exposures"][0]["sets"][0]["kind"] == "top"


def test_live_maintain_changes_no_set():
    rx = _rx()
    out = fm.apply_to_session(rx, {"selection": {"mode": "live"}}, _assess())
    assert [len(e["sets"]) for e in out["exposures"]] == [3, 3, 2] and out["fatigue"]["sets_removed"] == 0


def test_for_live_draft_never_raises(monkeypatch):
    rx = copy.deepcopy(_rx())
    monkeypatch.setattr(fm, "assess", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    class _In:
        target_date = AS_OF
        recovery_tier = "red"

    assert fm.for_live_draft(rx, {"selection": {"mode": "live"}}, _In(), []) is rx


def test_the_cardio_seam_reads_the_cardio_models_own_output():
    from training import cardio_model

    hard = cardio_model.cardio_load([{"modality": m, "minutes": 40, "rpe": 9} for m in ("rower", "rower")])
    easy = cardio_model.cardio_load([{"modality": "rower", "minutes": 40, "rpe": 3}])
    assert fm.cardio_state(hard) == "high" and fm.cardio_state(easy) == "moderate"  # control: the same minutes, easy
    assert fm.cardio_state(None) is None and fm.cardio_state({"state": "low"}) == "low"
    sig = {s["signal"]: s["state"] for s in _assess(cardio_load=hard)["signals"]}
    assert sig["cardio_load"] == "strain"

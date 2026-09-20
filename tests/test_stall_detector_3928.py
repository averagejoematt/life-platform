"""tests/test_stall_detector_3928.py — a stall may not be called from performed data alone.

THE SPECIMEN IS LIVE (#3928)
----------------------------
The fixtures below are the 2026-09-08 pull session, whose routine note in DynamoDB
(`USER#matthew#ROUTINE#f2d24cf6a1a94159315095025ad7091f`, sk `VERSION#current`) reads
verbatim:

    "RPE 8 hard cap, nothing to failure."  /  lat_pulldown: "120 lb anchored on 3 Sept
    (120x12,12,10)."

— transcribed into this repo by #3714 (`tests/test_adherence_calc.py`, whose header
records the S3 objects and DDB keys it came off). That is a FIXED load × FIXED reps
prescription, and 120 lb × 12 performed against it produces a byte-identical estimated
1RM every session forever. Calling that a "stall" is the platform re-reading the number
it prescribed. The Hevy wire shape (`type` / `weight_kg` / `reps` / `rpe`, warm-ups
carrying no RPE) and the template ids (`6A6C31A5` lat_pulldown, `37FCC2BB` db_curl,
`79D0BB3A` barbell bench) are transcribed from those same live records.

The multi-session SERIES is constructed — the platform does not store four identical
sessions of one lift as a single artifact to copy — but every session in it has the live
wire's shape, and the two series differ from each other only in the PRESCRIPTION, which
is exactly the property under test.
"""

from __future__ import annotations

import os

import pytest
from training.routine_ir import ExerciseBlock, RoutineSpec, Set
from training.stall_detector import (
    BASIS_MEASURED,
    BASIS_SELF_REPORTED_RPE,
    MATCH_AS_PRESCRIBED,
    MATCH_DEVIATED,
    MATCH_UNREADABLE,
    VERDICT_PROGRESSING,
    VERDICT_REGRESSING,
    VERDICT_STALL,
    VERDICT_UNKNOWN,
    SessionPoint,
    assess_stall,
    diff_prescribed_vs_performed,
    top_working_set,
)

LAT_PULLDOWN_TID = "6A6C31A5"
DB_CURL_TID = "37FCC2BB"
BENCH_TID = "79D0BB3A"

# 120 lb, the anchored load in the live routine note, in Hevy's native kg.
LB120_KG = 54.43
DATES = ("2026-08-25", "2026-08-28", "2026-09-01", "2026-09-03")


def _points(loads, reps, prescribed_loads, prescribed_reps, rpes=None):
    rpes = rpes or [None] * len(loads)
    return [
        SessionPoint(
            date=d,
            load_kg=lo,
            reps=r,
            rpe=rpe,
            prescribed_load_kg=plo,
            prescribed_reps=pr,
        )
        for d, lo, r, plo, pr, rpe in zip(DATES, loads, reps, prescribed_loads, prescribed_reps, rpes)
    ]


def _matched_fixed(rpes=None):
    """Four sessions at the anchored 120 lb x 12, each performed exactly as prescribed."""
    return _points([LB120_KG] * 4, [12] * 4, [LB120_KG] * 4, [12] * 4, rpes)


# ─────────────────────────────────────────────────────────────────────────────
# Acceptance 1 + 3: fixed load x fixed reps, matching the prescription -> no stall.
# ─────────────────────────────────────────────────────────────────────────────


def test_fixed_load_fixed_reps_as_prescribed_is_unknown_never_stall():
    result = assess_stall(_matched_fixed(), movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_UNKNOWN
    assert result["verdict"] != VERDICT_STALL
    assert "constant by construction" in result["reason"]
    # The diff is reported, not merely consulted — a reader can audit the refusal.
    assert result["prescribed_vs_performed"]["as_prescribed"] == 4
    assert result["prescribed_vs_performed"]["deviated"] == 0
    assert result["prescribed_vs_performed"]["prescription_varied"] is False


def test_same_performed_series_under_a_CLIMBING_prescription_is_a_stall():
    """THE MUTATION CONTROL. Identical performed data, identical e1RM series — only the
    prescription differs. If the detector ignored its prescribed-vs-performed input (the
    pre-#3928 behaviour), both windows would have to return the SAME verdict. They must
    not: this one is a real stall, the one above is not callable at all."""
    climbing = _points(
        [LB120_KG] * 4,
        [12] * 4,
        [LB120_KG, LB120_KG + 2.27, LB120_KG + 4.54, LB120_KG + 6.81],  # +5 lb per session
        [12] * 4,
    )
    result = assess_stall(climbing, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_STALL
    assert "prescription climbed" in result["reason"]
    assert result["prescribed_vs_performed"]["prescription_varied"] is True
    assert result["prescribed_vs_performed"]["deviated"] == 3

    # And the performed halves really are identical between the two windows.
    unknown = assess_stall(_matched_fixed(), movement_key="lat_pulldown")
    assert [s["e1rm_lb"] for s in result["e1rm_lb_series"]] == [s["e1rm_lb"] for s in unknown["e1rm_lb_series"]]
    assert unknown["verdict"] == VERDICT_UNKNOWN


def test_e1rm_really_is_constant_across_the_matched_window():
    """The premise, asserted rather than assumed: at fixed load x fixed reps the series
    has exactly one distinct value, so no trend test on it can carry information."""
    result = assess_stall(_matched_fixed(), movement_key="lat_pulldown")
    values = {s["e1rm_lb"] for s in result["e1rm_lb_series"]}
    assert len(values) == 1
    assert None not in values


# ─────────────────────────────────────────────────────────────────────────────
# Acceptance 2: any output that leaned on RPE says the input was self-reported.
# ─────────────────────────────────────────────────────────────────────────────


def test_rising_rpe_at_a_matched_fixed_prescription_still_refuses_the_stall_and_labels_rpe():
    result = assess_stall(_matched_fixed(rpes=[8.0, 8.5, 9.0, 9.5]), movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_UNKNOWN  # RPE never licenses a stall on a matched window
    assert result["basis"] == BASIS_SELF_REPORTED_RPE
    assert "rpe" in result["signals_used"]
    assert result["rpe"]["basis"] == BASIS_SELF_REPORTED_RPE
    assert result["rpe"]["direction"] == "rising"
    assert result["rpe"]["n_sessions_with_rpe"] == 4
    assert "self-reported" in result["reason"]


def test_a_stall_corroborated_by_rpe_carries_the_self_reported_basis():
    climbing = _points(
        [LB120_KG] * 4,
        [12] * 4,
        [LB120_KG, LB120_KG + 2.27, LB120_KG + 4.54, LB120_KG + 6.81],
        [12] * 4,
        rpes=[7.5, 8.0, 9.0, 9.5],
    )
    result = assess_stall(climbing, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_STALL
    assert result["basis"] == BASIS_SELF_REPORTED_RPE
    assert "his own rating, not a measurement" in result["reason"]


def test_a_stall_with_no_rpe_logged_does_not_claim_an_rpe_basis():
    """The control on the label: a verdict that never saw an RPE must not wear the tag."""
    climbing = _points(
        [LB120_KG] * 4,
        [12] * 4,
        [LB120_KG, LB120_KG + 2.27, LB120_KG + 4.54, LB120_KG + 6.81],
        [12] * 4,
    )
    result = assess_stall(climbing, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_STALL
    assert result["basis"] == BASIS_MEASURED
    assert "rpe" not in result["signals_used"]
    assert "rpe" not in result


# ─────────────────────────────────────────────────────────────────────────────
# The other refusals — every one of them an "unknown", never a stall.
# ─────────────────────────────────────────────────────────────────────────────


def test_no_prescription_on_file_cannot_call_a_stall():
    performed_only = _points([LB120_KG] * 4, [12] * 4, [None] * 4, [None] * 4)
    result = assess_stall(performed_only, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_UNKNOWN
    assert "cannot be called from performed data alone" in result["reason"]
    assert result["prescribed_vs_performed"]["unreadable"] == 4


def test_below_the_session_floor_is_unknown():
    result = assess_stall(_matched_fixed()[:2], movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_UNKNOWN
    assert "below the 3-session floor" in result["reason"]


def test_flat_under_a_prescription_that_never_climbed_is_not_a_stall():
    """He came in UNDER a fixed prescription every session. That is a compliance gap —
    and reporting it as a stall would blame the lift for a missed plan."""
    under = _points([50.0, 50.0, 50.0, 50.0], [12] * 4, [LB120_KG] * 4, [12] * 4)
    result = assess_stall(under, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_UNKNOWN
    assert result["prescribed_vs_performed"]["deviated"] == 4
    assert "not a stall" in result["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# The detector still reads a real trend when there IS one.
# ─────────────────────────────────────────────────────────────────────────────


def test_a_climbing_performed_series_reads_as_progressing():
    climbing = _points(
        [LB120_KG, LB120_KG + 4.54, LB120_KG + 9.07, LB120_KG + 13.6],
        [12] * 4,
        [LB120_KG, LB120_KG + 4.54, LB120_KG + 9.07, LB120_KG + 13.6],
        [12] * 4,
    )
    result = assess_stall(climbing, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_PROGRESSING


def test_a_falling_performed_series_reads_as_regressing():
    falling = _points(
        [LB120_KG + 13.6, LB120_KG + 9.07, LB120_KG + 4.54, LB120_KG],
        [12] * 4,
        [LB120_KG + 13.6, LB120_KG + 13.6, LB120_KG + 13.6, LB120_KG + 13.6],
        [12] * 4,
    )
    result = assess_stall(falling, movement_key="lat_pulldown")
    assert result["verdict"] == VERDICT_REGRESSING


# ─────────────────────────────────────────────────────────────────────────────
# The diff itself, against the live wire shape.
# ─────────────────────────────────────────────────────────────────────────────


def _pull_ir() -> RoutineSpec:
    """The 2026-09-08 pull routine, with the anchored load made explicit in the IR."""
    return RoutineSpec(
        routine_id="f2d24cf6a1a94159315095025ad7091f",
        target_date="2026-09-08",
        archetype="pull",
        notes="Pull, RPE 8 hard cap, nothing to failure.",
        exercises=[
            ExerciseBlock(
                movement_key="lat_pulldown",
                sets=[Set(weight_kg=LB120_KG, reps=12) for _ in range(3)],
                notes="RPE 8 cap. 120 lb anchored on 3 Sept (120x12,12,10).",
            ),
            ExerciseBlock(movement_key="db_curl", sets=[Set(weight_kg=15.0, reps=10) for _ in range(3)]),
        ],
    )


def _pull_performed(lat_kg=LB120_KG, lat_reps=12) -> dict:
    return {
        "routine_id": "7da4dd70-546b-4522-bb48-11a9e4a8f1df",
        "start_time": "2026-09-08T17:30:00+00:00",
        "exercises": [
            {
                "exercise_template_id": LAT_PULLDOWN_TID,
                "sets": [
                    {"type": "warmup", "weight_kg": 30.0, "reps": 10, "rpe": None},
                    {"type": "normal", "weight_kg": lat_kg, "reps": lat_reps, "rpe": 8.0},
                    {"type": "normal", "weight_kg": lat_kg, "reps": lat_reps, "rpe": 8.0},
                ],
            },
            {"exercise_template_id": DB_CURL_TID, "sets": [{"type": "normal", "weight_kg": 15.0, "reps": 10, "rpe": 8.5}]},
        ],
    }


_TMAP = {"lat_pulldown": LAT_PULLDOWN_TID, "db_curl": DB_CURL_TID}


def _diff(ir, performed):
    """The wire payload is grouped by template id at the call site (the one module the
    compiler-isolation ledger names); the detector never sees the raw shape."""
    from mcp.hevy_readback_report import sets_by_template

    return diff_prescribed_vs_performed(ir, sets_by_template(performed), _TMAP)


def test_diff_reports_as_prescribed_when_the_top_set_matches():
    diff = _diff(_pull_ir(), _pull_performed())
    lat = diff["lat_pulldown"]
    assert lat["match"] == MATCH_AS_PRESCRIBED
    assert lat["prescribed_load_kg"] == pytest.approx(LB120_KG)
    assert lat["performed_load_kg"] == pytest.approx(LB120_KG)
    assert lat["performed_rpe"] == 8.0
    # The 30 kg warm-up is never the top working set.
    assert lat["performed_reps"] == 12


def test_diff_reports_deviated_when_he_went_heavier_than_the_plan():
    diff = _diff(_pull_ir(), _pull_performed(lat_kg=LB120_KG + 4.54))
    assert diff["lat_pulldown"]["match"] == MATCH_DEVIATED


def test_a_prescribed_movement_he_never_performed_is_unreadable_not_compliant():
    performed = _pull_performed()
    performed["exercises"] = [e for e in performed["exercises"] if e["exercise_template_id"] != LAT_PULLDOWN_TID]
    diff = _diff(_pull_ir(), performed)
    assert diff["lat_pulldown"]["match"] == MATCH_UNREADABLE
    assert diff["lat_pulldown"]["performed_load_kg"] is None


def test_top_working_set_reads_both_wire_spellings_and_skips_warmups():
    raw = [{"type": "warmup", "weight_kg": 60.0, "reps": 5}, {"type": "normal", "weight_kg": 40.0, "reps": 8, "rpe": 7.0}]
    normalized = [{"set_type": "warmup", "weight_kg": 60.0, "reps": 5}, {"set_type": "normal", "weight_kg": 40.0, "reps": 8}]
    assert top_working_set(raw)["weight_kg"] == 40.0
    assert top_working_set(raw)["rpe"] == 7.0
    assert top_working_set(normalized)["weight_kg"] == 40.0
    assert top_working_set([])["weight_kg"] is None


# ─────────────────────────────────────────────────────────────────────────────
# The wiring: manage_hevy_routine action=stall_check (#3928).
# ─────────────────────────────────────────────────────────────────────────────


def test_action_is_registered_and_dispatched():
    # mcp.config reads these at import; mcp.registry pulls the full table.
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    os.environ.setdefault("USER_ID", "matthew")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    from mcp import registry, tools_hevy_routine

    assert "stall_check" in tools_hevy_routine._VALID_ACTIONS
    assert tools_hevy_routine._DISPATCH["stall_check"] is not None
    schema = registry.TOOLS["manage_hevy_routine"]["schema"]["inputSchema"]["properties"]
    assert "stall_check" in schema["action"]["description"]
    assert "movement_key" in schema


def test_stall_check_pairs_each_session_with_the_plan_that_was_pushed(monkeypatch):
    from mcp import hevy_readback_report

    ir = _pull_ir()
    monkeypatch.setattr(hevy_readback_report, "_prescription_for", lambda w: (ir, "hevy_routine_id"))
    monkeypatch.setattr(hevy_readback_report, "_template_map_for", lambda _ir: _TMAP)

    def _fake_get_workouts(page=1, page_size=10):
        if page > 1:
            return {"workouts": []}
        return {
            "workouts": [
                {**_pull_performed(), "start_time": f"2026-09-0{d}T17:30:00+00:00"} for d in (8, 6, 4, 2)  # newest first, as Hevy pages
            ]
        }

    out = hevy_readback_report.stall_check({"movement_key": "lat_pulldown", "sessions": 4}, get_workouts=_fake_get_workouts)
    assert out["status"] == "ok"
    assert out["template_id"] == LAT_PULLDOWN_TID
    assert out["sessions_examined"] == 4
    # Oldest first when it reaches the detector — a reversed series would invert
    # progressing/regressing without failing any other assertion here.
    assert [p["date"] for p in out["stall"]["e1rm_lb_series"]] == ["2026-09-02", "2026-09-04", "2026-09-06", "2026-09-08"]
    assert out["stall"]["verdict"] == VERDICT_UNKNOWN
    assert "constant by construction" in out["stall"]["reason"]
    assert all(row["prescription"] == "hevy_routine_id" for row in out["prescription_provenance"])


def test_stall_check_says_no_prescription_rather_than_reading_performed_alone(monkeypatch):
    from mcp import hevy_readback_report

    monkeypatch.setattr(hevy_readback_report, "_prescription_for", lambda w: (None, None))

    def _fake_get_workouts(page=1, page_size=10):
        if page > 1:
            return {"workouts": []}
        return {"workouts": [{**_pull_performed(), "start_time": f"2026-09-0{d}T17:30:00+00:00"} for d in (8, 6, 4)]}

    out = hevy_readback_report.stall_check({"template_id": LAT_PULLDOWN_TID}, get_workouts=_fake_get_workouts)
    assert out["stall"]["verdict"] == VERDICT_UNKNOWN
    assert "cannot be called from performed data alone" in out["stall"]["reason"]
    assert all(row["prescription"] == "none" for row in out["prescription_provenance"])


def test_stall_check_requires_a_movement():
    from mcp import hevy_readback_report

    out = hevy_readback_report.stall_check({})
    assert out.get("error") or out.get("isError") or out.get("error_code")


def test_peek_template_id_never_writes_the_cache(monkeypatch):
    """The read path must not promote a hint back into S3 (that is `resolve_movement`'s
    job on the authoring path). A report that mutates config to answer a question is the
    class of bug that makes a read surface unsafe to call."""
    from training import hevy_template_cache as cache

    monkeypatch.setattr(cache, "_load_cache", lambda: {"movements": {}})
    monkeypatch.setattr(cache, "_load_catalog", lambda: {"movements": {"lat_pulldown": {"hevy_template_id_hint": LAT_PULLDOWN_TID}}})

    def _boom(*a, **k):
        raise AssertionError("peek_template_id wrote to S3")

    monkeypatch.setattr(cache, "_write_s3_json", _boom)
    assert cache.peek_template_id("lat_pulldown") == LAT_PULLDOWN_TID
    assert cache.peek_template_id("tmpl:" + BENCH_TID) == BENCH_TID
    assert cache.peek_template_id("no_such_movement") is None

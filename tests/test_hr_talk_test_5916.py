"""tests/test_hr_talk_test_5916.py — no live training surface prints a heart-rate target or cap (#5916).

WHY THIS EXISTS

The standing constraint (`training.standing_constraints`, active from 2026-10-10, no end date) says no heart-rate
prescriptions: the cue is the talk test. Several surfaces never read it. The day-shape line and the walking redline
carried a fixed walking heart-rate cap and target; the recent-aerobic block and the session packet graded walks against
that cap; the training recommendation printed percent-of-max targets again once the time-boxed re-baselining window
lapsed; three descriptions stated a population formula without saying so.

Owner ruling 2026-11-13: the fixed walking cap and target are replaced by the talk test plus RPE. Heart rate stays
recorded as a MEASUREMENT and is never graded against a fixed ceiling.

THE SET, NOT THE SPECIMEN. `SURFACES` enumerates every surface the issue names, each built the way it is served for a
day the constraint is active, from synthetic rows whose walk average sits far above any cap the platform ever carried.
One sweep (`_problems`) walks each payload and names every heart-rate target, cap, grade or percent-of-max phrase it
finds. The recommendation is enumerated from SOURCE: every `rec = {...}` literal in `_get_training_recommendation` is
evaluated and put through the gate, so a branch added later is covered the day it is written.

Every heart-rate number in this file is synthetic.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from training import (  # noqa: E402
    owner_redlines,
    program_structure,
    recent_aerobic,
    redline_changelog,
    standing_constraints as sc,
    training_load,
)

DAY = "2026-11-13"  # the standing constraint is active; the time-boxed re-baselining window (health.hr_regime) has lapsed
PRIOR = "2026-11-12"
BEFORE = "2026-10-05"  # no constraint is active yet — the path that used to print the cap
SYNTHETIC_WALK_AVG = 151.0  # far above any cap the platform carried: every retired grade would have fired on it
SYNTHETIC_BLOCK_AVG = 149.0
SYNTHETIC_MAX_HR = 200

# ── what may not be printed ──────────────────────────────────────────────────────────────
# A cap or a target in words, and a percent-of-max phrase. Each pattern is one of the retired sentences' shapes.
FORBIDDEN_PHRASES: dict[str, re.Pattern[str]] = {
    "a cap in bpm": re.compile(r"[≤<]=?\s*\d{2,3}(?:\.\d)?\s*[- ]?bpm", re.I),
    "a heart-rate cap": re.compile(r"(?:\bHR|heart[ -]rate)\s+(?:avg|average)?\s*[≤<]=?\s*\d{2,3}\b", re.I),
    "a heart-rate target": re.compile(r"\b\d{2,3}\s*(?:bpm\s+)?the target\b|\btarget\s+(?:of\s+)?\d{2,3}\s*(?:bpm)?\s*[).]", re.I),
    "a percent-of-max phrase": re.compile(r"\d\s*%\s*(?:of\s+)?max", re.I),
    "a percent-of-max zone": re.compile(r"percentage of max HR", re.I),
    "a grade against a ceiling": re.compile(r"over the (?:HR|heart[ -]rate) (?:ceiling|cap)", re.I),
}
# On a PRESCRIPTION line no bpm figure belongs at all. (The redline's `note` keeps one sentence of 2024–25 history in
# bpm — what he walked at, never a target — so the redline record is swept for caps and targets only.)
ANY_BPM = re.compile(r"\b\d{2,3}(?:\.\d)?\s*[- ]?bpm\b", re.I)
# A key that IS a heart-rate target, cap or grade: allowed only when its value is None (not graded) or empty.
GRADE_KEYS = frozenset(
    {"hr_ceiling_bpm", "hr_target_bpm", "hr_ceiling", "hr_floor", "over_by_bpm", "hr_ceiling_flags", "avg_hr_over_ceiling", "over_ceiling"}
)


def _problems(payload: Any, *, any_bpm: bool = True, where: str = "") -> list[str]:
    """Every heart-rate target, cap, grade or percent-of-max phrase in `payload`, named with its path."""
    out: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            path = f"{where}.{k}" if where else str(k)
            if k in GRADE_KEYS and v not in (None, [], {}):
                out.append(f"{path} = {v!r} (a heart-rate target, cap or grade)")
            out += _problems(v, any_bpm=any_bpm, where=path)
    elif isinstance(payload, (list, tuple)):
        for i, v in enumerate(payload):
            out += _problems(v, any_bpm=any_bpm, where=f"{where}[{i}]")
    elif isinstance(payload, str):
        for name, pat in FORBIDDEN_PHRASES.items():
            m = pat.search(payload)
            if m:
                out.append(f"{where}: {name} — {m.group(0)!r}")
        m = ANY_BPM.search(payload) if any_bpm else None
        if m:
            out.append(f"{where}: a bpm figure on a prescription line — {m.group(0)!r}")
    return out


# ── synthetic rows ───────────────────────────────────────────────────────────────────────
def _strava() -> list[dict]:
    return [
        {
            "date": PRIOR,
            "activities": [
                {
                    "strava_id": "synthetic-walk",
                    "name": "Synthetic walk",
                    "type": "Walk",
                    "sport_type": "Walk",
                    "start_date": f"{PRIOR}T16:00:00Z",
                    "moving_time_seconds": 3600,
                    "elapsed_time_seconds": 3600,
                    "average_heartrate": SYNTHETIC_WALK_AVG,
                    "max_heartrate": 163.0,
                    "device_name": "Synthetic Watch",
                    "distance_meters": 5000.0,
                },
                {  # a strap's record over the gym session — the wearable the treadmill block's HR joins to (#4412)
                    "strava_id": "synthetic-gym",
                    "name": "Synthetic gym",
                    "type": "Workout",
                    "sport_type": "Workout",
                    "start_date": f"{PRIOR}T20:00:00Z",
                    "moving_time_seconds": 3600,
                    "elapsed_time_seconds": 3600,
                    "average_heartrate": SYNTHETIC_BLOCK_AVG,
                    "max_heartrate": 171.0,
                    "device_name": "Synthetic Strap",
                },
            ],
        }
    ]


def _hevy() -> list[dict]:
    return [
        {
            "date": PRIOR,
            "workout_uid": "synthetic-session",
            "title": "Synthetic session",
            "start_time": f"{PRIOR}T20:00:00Z",
            "end_time": f"{PRIOR}T21:00:00Z",
            "exercises": [
                {"name": "Bench Press (Barbell)", "sets": [{"reps": 8, "weight_kg": 60.0}]},
                {"name": "Treadmill", "sets": [{"duration_sec": 1800, "distance_m": 2500.0}]},
            ],
        }
    ]


def _block() -> dict:
    return recent_aerobic.build(target_date=DAY, today=DAY, strava_items=_strava(), hevy_workouts=_hevy())


def _today_view() -> dict:
    from mcp import coach_packet_today

    value, status = coach_packet_today.today_view(
        DAY,
        today=DAY,
        read_hevy=lambda d: [w for w in _hevy() if w["date"] == d],
        read_strava=lambda d: [r for r in _strava() if r["date"] == d],
    )
    assert value is not None, status
    return value


class _TimedBlock:
    """A drafted timed block, the shape `draft_cardio_warnings` reads (`movement_key`, `sets[].duration_seconds`)."""

    def __init__(self, movement_key: str, minutes: int):
        self.movement_key = movement_key
        self.sets = [type("S", (), {"duration_seconds": minutes * 60})()]


def _cardio_warnings(day: str) -> list[str]:
    """`draft_custom`'s cardio warning for a treadmill drafted onto a lower session — the pick is cycling, so the
    warning prints the pick's intensity. `day` chooses the constrained path or the one before the constraint."""
    from unittest.mock import patch

    from mcp import plan_cardio_pick, shared_quantities

    with patch.object(shared_quantities, "recent_aerobic_layer", return_value=_block()):
        lines = plan_cardio_pick.draft_cardio_warnings([_TimedBlock("treadmill", 30)], "lower", day)
    cardio = [w for w in lines if w.startswith("cardio:")]
    assert cardio, f"no cardio warning was produced for {day} — the surface was not exercised: {lines}"
    return cardio


# ── the recommendation, enumerated from source ───────────────────────────────────────────
def _recommendation_literals() -> list[dict]:
    """Every `rec = {...}` literal in `_get_training_recommendation`, evaluated with synthetic names — one per branch."""
    src = (REPO / "mcp" / "tools_training.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_get_training_recommendation")
    env = {"max_hr": SYNTHETIC_MAX_HR, "round": round, "target": "Lower Body", "muscles": ["Quads"]}
    recs = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and node.value.keys):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "rec" for t in node.targets):
            continue
        recs.append(eval(compile(ast.Expression(node.value), "<rec>", "eval"), {"__builtins__": {}}, env))  # noqa: S307 — repo source
    return recs


def _served(rec: dict, day: str = DAY, tier: str = "GREEN") -> dict:
    return {"date": day, "readiness_tier": tier, "recommendation": dict(rec), "board_of_directors": [], "training_context": {}}


def _gated_recommendations() -> list[dict]:
    from mcp import tools_training as tt

    return [tt._apply_hr_regime(_served(rec))["recommendation"] for rec in _recommendation_literals()]


def _periodization_methodology(monkeypatch) -> str:
    from mcp import tools_training as tt

    monkeypatch.setattr(tt, "query_source", lambda *a, **k: [])
    monkeypatch.setattr(tt, "get_profile", lambda: {"max_heart_rate": SYNTHETIC_MAX_HR})
    out = tt._get_training_periodization({"start_date": "2026-11-01", "end_date": DAY})
    if "methodology" in out:
        return out["methodology"]
    # no rows -> an error answer with no methodology: read the one literal from source instead
    fn = next(
        n
        for n in ast.walk(ast.parse((REPO / "mcp" / "tools_training.py").read_text()))
        if isinstance(n, ast.FunctionDef) and n.name == "_get_training_periodization"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "methodology":
                    return ast.literal_eval(v)
    raise AssertionError("the periodization methodology line was not found")


def _load_basis() -> dict:
    from datetime import date

    _load, basis = training_load.daily_training_load(_strava(), [], date.fromisoformat(DAY))
    return basis


# name -> (builder, any_bpm): the payload as it is served on DAY, and whether a bare bpm figure is also refused there
def _surfaces(monkeypatch) -> dict[str, tuple[Callable[[], Any], bool]]:
    from mcp import tools_coach_packet, tools_descriptions

    block = _block()
    walking = {k: v for k, v in owner_redlines.REDLINES["walking_floor_hr_wk"].items() if k != "retired"}
    return {
        "program_structure.DAY_SHAPE (the day-shape line)": (lambda: program_structure.DAY_SHAPE, True),
        "program_structure.summary().day_shape (what plan_next_session serves)": (lambda: program_structure.summary()["day_shape"], True),
        # `retired` is the redline's own pre-existing record of values retired on 2026-09-30, labelled as such
        "owner_redlines.walking_floor_hr_wk (the redline record)": (lambda: walking, False),
        "recent_aerobic.build (rows, totals, redlines)": (lambda: block, True),
        "recent_aerobic.last_cardio_block_hr": (lambda: recent_aerobic.last_cardio_block_hr(block), True),
        "recent_aerobic.cardio_pick, dated (constraint active)": (lambda: recent_aerobic.cardio_pick(block, "lower", DAY), True),
        "recent_aerobic.cardio_pick, undated": (lambda: recent_aerobic.cardio_pick(block, "lower"), True),
        "recent_aerobic.cardio_pick, before the constraint": (lambda: recent_aerobic.cardio_pick(block, "lower", BEFORE), True),
        "coach_packet_today.today_view (the session packet's today)": (_today_view, True),
        "tools_coach_packet.SOURCES['today']": (lambda: tools_coach_packet.SOURCES["today"], True),
        "tools_coach_packet.COACH_PACKET_DESCRIPTION": (lambda: tools_coach_packet.COACH_PACKET_DESCRIPTION, True),
        "plan_cardio_pick.draft_cardio_warnings (constraint active)": (lambda: _cardio_warnings(DAY), True),
        "plan_cardio_pick.draft_cardio_warnings (before the constraint)": (lambda: _cardio_warnings(BEFORE), True),
        "tools_training._apply_hr_regime over every recommendation branch": (_gated_recommendations, True),
        "tools_descriptions.GET_ZONE2_BREAKDOWN_DESCRIPTION": (lambda: tools_descriptions.GET_ZONE2_BREAKDOWN_DESCRIPTION, True),
        "tools_training periodization methodology": (lambda: _periodization_methodology(monkeypatch), True),
        "training_load basis (z1_ceiling_bpm and its provenance)": (_load_basis, True),
    }


# ── 1. the sweep ─────────────────────────────────────────────────────────────────────────
def test_no_training_surface_prints_a_heart_rate_target_a_cap_or_a_percent_of_max_phrase(monkeypatch):
    """Acceptance box 1. Every surface in the set, built for a day the standing constraint is active, swept in one
    pass; every offender is reported, not only the first."""
    assert sc.active_constraint(DAY) is not None and sc.active_constraint(DAY)["hr_prescriptions_allowed"] is False
    surfaces = _surfaces(monkeypatch)
    offenders: dict[str, list[str]] = {}
    for name, (build, any_bpm) in surfaces.items():
        payload = build()
        assert payload, f"{name} produced nothing — the surface was not exercised"
        found = _problems(payload, any_bpm=any_bpm)
        if found:
            offenders[name] = found
    assert not offenders, "a heart-rate target, cap or percent-of-max phrase is printed:\n" + json.dumps(
        offenders, indent=1, ensure_ascii=False
    )
    assert len(surfaces) >= 17  # the issue's set; a surface dropped from the enumeration is a hole in the sweep


def test_the_sweep_itself_catches_each_retired_sentence():
    """The sweep is only worth its name if it reds on what it guards against: the retired sentences' own shapes, on
    synthetic numbers, each caught — and the ruling's own lines pass."""
    retired = {
        "day shape": "easy walking EVERY day (HR avg ≤ 140 with the talk test, 125 the target; 2–3 walks)",
        "redline note": "HR average ≤ 140 with the talk test, 125 the target; one long-walk slot a week",
        "cardio warning": "the pick from the last 3 days is cycling (recumbent) (HR avg ≤ 140 bpm, target 125) — a lower session",
        "easy recommendation": "Light walk, mobility work, or gentle yoga. Keep HR below 60% max.",
        "interval recommendation": "VO2max work: 4-6 intervals of 3-4 minutes at 85-90% max HR with equal rest.",
        "zone description": "Classifies activities into 5 HR zones based on average heartrate as a percentage of max HR (from profile).",
        "a bare bpm on a prescription line": "hold 132 bpm for the block",
        "packet description": "plus walking hours so far and a flag on any walk over the HR ceiling;",
    }
    for name, text in retired.items():
        assert _problems({"line": text}), f"the sweep missed the retired {name} sentence: {text!r}"
    for key in sorted(GRADE_KEYS - {"hr_ceiling_flags"}):
        assert _problems({key: 140}) and not _problems({key: None}), key
    assert _problems({"hr_ceiling_flags": [{"id": "x", "over_by_bpm": 11.0}]}) and not _problems({"hr_ceiling_flags": []})
    for fine in (recent_aerobic.EASY_EFFORT_CUE, sc.TALK_TEST_CUE, sc.HARD_EFFORT_CUE, program_structure.DAY_SHAPE["pm"]):
        assert not _problems({"line": fine}), fine
    # a measured average is a number in a field, never a prescription line — the sweep leaves it alone
    assert not _problems({"avg_hr": SYNTHETIC_WALK_AVG, "max_hr": 163.0})


# ── 2. the day shape and the redline ─────────────────────────────────────────────────────
def test_the_day_shape_line_and_the_walking_redline_say_talk_test_and_rpe():
    """Items 1 + 2: the day-shape line reuses the constraint's own talk-test cue and reads the redline's easy-effort
    RPE; the redline carries the dated ruling and no bpm field; its hours, walk count and walk length are untouched."""
    pm = program_structure.DAY_SHAPE["pm"]
    walking = owner_redlines.REDLINES["walking_floor_hr_wk"]
    assert sc.TALK_TEST_CUE in pm and f"RPE {walking['easy_rpe_max']} or below" in pm and walking["easy_rpe_max"] == 4
    assert (
        pm
        == f"easy walking EVERY day: {recent_aerobic.EASY_EFFORT_CUE} 2–3 walks, weekday none over 75 min, one long-walk slot a week; never intervals"
    )
    assert recent_aerobic.EASY_EFFORT_CUE == sc.easy_effort_cue(walking["easy_rpe_max"])
    # the number has ONE home: change the redline's value and the composed cue follows it
    assert "RPE 3 or below" in sc.easy_effort_cue(3) and sc.easy_effort_cue(3).startswith(sc.TALK_TEST_CUE)

    assert "hr_ceiling_bpm" not in walking and "hr_target_bpm" not in walking
    assert (
        walking["intensity_by"].startswith("talk test + RPE") and "2026-11-13" in walking["intensity_by"] and walking["talk_test"] is True
    )
    assert "Owner ruling 2026-11-13 (#5916)" in walking["note"] and "never graded against a fixed ceiling" in walking["note"]
    # untouched: the hours floor and target, the ramp, the walk count, the walk length, the long-walk slot
    assert (walking["value"], walking["target_hr_wk"], walking["ramp_hr_per_wk_max"], walking["maintenance_floor_hr_wk"]) == (
        8.5,
        12,
        1.0,
        10,
    )
    assert walking["standalone_walks"]["min_per_wk"] == 3 and walking["standalone_walks"]["min_minutes"] == 20
    assert "none over 75 min" in walking["walks"] and walking["long_walk_slots_per_wk"] == 1 and walking["permanent"] is True
    # the retired numbers are history: named in the changelog by date, held in one record outside `summary()`
    assert any(line.startswith("2026-11-13 (#5916") and "RETIRED" in line for line in redline_changelog.CHANGELOG_V2_TO_V3)
    assert redline_changelog.RETIRED_WALKING_HR_LINE["retired"] == "2026-11-13"
    assert "RETIRED_WALKING_HR_LINE" not in json.dumps(owner_redlines.summary(), default=str)
    assert not _problems(
        {k: v for k, v in owner_redlines.summary()["redlines"]["walking_floor_hr_wk"].items() if k != "retired"}, any_bpm=False
    )


# ── 3. measured, never graded ────────────────────────────────────────────────────────────
def test_a_measured_walking_average_is_still_reported_labelled_as_a_measurement():
    """Acceptance box 2 + item 3. A walk and a treadmill block whose averages sit far above any cap the platform
    carried: both averages are still on the row, each labelled as a measurement with its basis, and nothing grades
    them — no flag on the row, no cap on the block, no flag on the packet."""
    block = _block()
    walk = next(r for r in block["rows"] if r["source"] == "strava" and r["modality"] == "walk")
    tread = next(r for r in block["rows"] if r["source"] == "hevy")
    assert (walk["avg_hr"], tread["avg_hr"], tread["hr_state"]) == (SYNTHETIC_WALK_AVG, SYNTHETIC_BLOCK_AVG, "joined")
    for row in (walk, tread):
        assert row["avg_hr_basis"].startswith("measured") and "never graded against a fixed ceiling" in row["avg_hr_basis"]
        assert set(row["flags"]) == {"over_75_min"}  # walk length is the only flag left
    assert walk["avg_hr_basis"] == recent_aerobic.AVG_HR_BASIS_DEVICE and "inferred minutes" in tread["avg_hr_basis"]
    # the walk-length flag still works (the duration half of the redline is untouched)
    long_walk = _strava()
    long_walk[0]["activities"][0]["moving_time_seconds"] = long_walk[0]["activities"][0]["elapsed_time_seconds"] = 80 * 60
    rows = recent_aerobic.build(target_date=DAY, today=DAY, strava_items=long_walk, hevy_workouts=[])["rows"]
    assert [r["flags"] for r in rows if r["modality"] == "walk"] == [{"over_75_min": True}]

    assert block["redlines"]["intensity"] == recent_aerobic.EASY_EFFORT_CUE and "measurement" in block["redlines"]["heart_rate"]
    assert block["redlines"]["walk_max_min"] == recent_aerobic.WALK_MAX_MIN and block["version"] == "recent-aerobic@1.4.0"

    last = recent_aerobic.last_cardio_block_hr(block)
    assert last["avg_hr"] == SYNTHETIC_BLOCK_AVG and last["avg_hr_basis"] == tread["avg_hr_basis"]
    assert "over_ceiling" in last and last["over_ceiling"] is None  # the key stays for coach.critics_aerobic; never a grade

    today = _today_view()
    assert "hr_ceiling_flags" not in today and today["version"] == "coach-packet-today@1.2.0"
    assert [(m["avg_hr"], m["basis"]) for m in today["walk_hr_measured"]] == [(SYNTHETIC_WALK_AVG, recent_aerobic.AVG_HR_BASIS_DEVICE)]
    assert today["walking_floor_hr_wk"]["intensity"] == recent_aerobic.EASY_EFFORT_CUE
    assert any(a.get("avg_hr") == SYNTHETIC_WALK_AVG for a in today["activities"])  # the activity row keeps its number too


def test_a_row_with_no_heart_rate_carries_no_basis_and_no_invented_number():
    """Unknown stays unknown (ADR-104): a walk with no average has no `avg_hr_basis`, and no block to report."""
    rows = _strava()
    del rows[0]["activities"][0]["average_heartrate"]
    block = recent_aerobic.build(target_date=DAY, today=DAY, strava_items=rows, hevy_workouts=[])
    (walk,) = [r for r in block["rows"] if r["modality"] == "walk"]
    assert walk["avg_hr"] is None and "avg_hr_basis" not in walk
    assert recent_aerobic.last_cardio_block_hr(block) is None


def test_the_cardio_pick_and_the_chat_warning_carry_the_talk_test_on_every_path():
    """Item 3 + the chat-draft warning: no heart-rate field on the pick whether or not a constraint is active, and the
    warning's parenthesis is the redline's talk-test + RPE line — the old numbers have no path left to print on."""
    block = _block()
    picks = {
        "dated": recent_aerobic.cardio_pick(block, "lower", DAY),
        "undated": recent_aerobic.cardio_pick(block, "lower"),
        "before": recent_aerobic.cardio_pick(block, "lower", BEFORE),
    }
    for name, pick in picks.items():
        assert not set(sc.HR_PICK_FIELDS) & set(pick), name
        assert pick["intensity"] == recent_aerobic.EASY_EFFORT_CUE and pick["movement_key"] == "cycling", name
    # only the dated pick under the constraint names the constraint
    assert picks["dated"]["hr_fields_dropped_by"] == sc.active_constraint(DAY)["id"]
    assert "hr_fields_dropped_by" not in picks["undated"] and "hr_fields_dropped_by" not in picks["before"]
    # #5000's own behaviour is unchanged for a pick that does NOT lead with the talk test
    legacy = sc.talk_test_pick({"movement_key": "cycling", "hr_ceiling_bpm": 140, "hr_target_bpm": 125}, sc.active_constraint(DAY))
    assert legacy["intensity"] == sc.TALK_TEST_CUE and not set(sc.HR_PICK_FIELDS) & set(legacy)
    for day in (DAY, BEFORE):
        (warning,) = _cardio_warnings(day)
        assert f"cycling (recumbent) ({recent_aerobic.EASY_EFFORT_CUE})" in warning and "bpm" not in warning, warning
    # the two retired names (`recent_aerobic.HR_CEILING_BPM` / `HR_TARGET_BPM`) are read by none of the surfaces this
    # issue owns — the one reader left is `coach.critics_aerobic`, another lane's file
    for rel in (
        "lambdas/training/cardio_cues.py",
        "lambdas/training/program_structure.py",
        "mcp/plan_cardio_pick.py",
        "mcp/coach_packet_today.py",
        "mcp/tools_training.py",
    ):
        src = (REPO / rel).read_text()
        assert "HR_CEILING_BPM" not in src and "HR_TARGET_BPM" not in src, f"{rel} reads a retired heart-rate number"


# ── 4. the training recommendation ───────────────────────────────────────────────────────
def test_the_recommendation_keeps_tier_and_type_and_drops_every_heart_rate_prescription():
    """Item 4. Every branch `_get_training_recommendation` can serve, through `_apply_hr_regime` on a day the standing
    constraint is active and the re-baselining window has lapsed: the tier and the session type stand, `hr_floor` /
    `hr_ceiling` are None, and a percent-of-max phrase is replaced by the talk-test cue or an RPE phrase."""
    from health import hr_regime

    from mcp import tools_training as tt

    assert hr_regime.regime_status(DAY) is None, "the time-boxed window is expected to have lapsed on DAY"
    recs = _recommendation_literals()
    with_hr = [r for r in recs if any(isinstance(r.get(k), (int, float)) for k in sc.HR_RECOMMENDATION_FIELDS)]
    with_pct = [r for r in recs if re.search(r"% max", str(r.get("description")))]
    assert len(recs) >= 8 and len(with_hr) >= 4 and len(with_pct) >= 2, "the source enumeration came back thin — check the AST walk"

    for rec in recs:
        out = tt._apply_hr_regime(_served(rec, tier="YELLOW"))
        new = out["recommendation"]
        assert out["readiness_tier"] == "YELLOW" and new["type"] == rec["type"] and new.get("intensity") == rec.get("intensity")
        assert new.get("duration_min") == rec.get("duration_min")
        assert all(new.get(k) is None for k in sc.HR_RECOMMENDATION_FIELDS), new
        assert not _problems(new), (rec["type"], _problems(new))
        touched = rec in with_hr or rec in with_pct
        assert ("hr_fields_dropped_by" in new) is touched and ("effort_cue" in new) is touched, rec["type"]
        if not touched:
            assert new == rec  # strength, rest and the no-signal answer are served exactly as written

    easy = tt._apply_hr_regime(_served(next(r for r in with_pct if "hard" not in str(r["intensity"]).lower())))["recommendation"]
    assert easy["description"].endswith("Talk test — full sentences throughout. No HR target.") and easy["effort_cue"] == sc.TALK_TEST_CUE
    hard = tt._apply_hr_regime(_served(next(r for r in with_pct if "hard" in str(r["intensity"]).lower())))["recommendation"]
    assert "4-6 intervals of 3-4 minutes at a hard effort by RPE" in hard["description"] and "with equal rest" in hard["description"]
    assert hard["effort_cue"] == sc.HARD_EFFORT_CUE and hard["hr_fields_dropped_by"] == "hr_regime_change_2026_10_10"

    # mutation control: before the constraint took effect the answer passes through untouched
    zone2 = next(r for r in with_hr if r["type"] == "Zone 2 Cardio")
    assert tt._apply_hr_regime(_served(zone2, day=BEFORE))["recommendation"] == zone2
    # …and inside the time-boxed window the #4999 replacement still wins (no tier, no HR prescription)
    inside = tt._apply_hr_regime(_served(zone2, day="2026-10-18"))
    assert inside["readiness_tier"] == "RE-BASELINING" and inside["recommendation"]["hr_ceiling"] is None


def test_the_served_recommendation_view_carries_no_heart_rate_prescription(monkeypatch):
    """The same gate through the view the tool dispatches (`view=recommendation`), on synthetic readiness rows that
    land an aerobic recommendation — the branch that printed a floor and a ceiling once the window lapsed."""
    from mcp import tools_training as tt

    rows = {"whoop": [{"date": DAY, "recovery_score": 82, "hrv": 60, "resting_heart_rate": 50, "strain": 8}]}

    def reader(source, start_date, end_date, lean=False, include_pilot=None):
        return [dict(r) for r in rows.get(source, []) if start_date <= r["date"] <= end_date]

    monkeypatch.setattr(tt, "query_source", reader)
    monkeypatch.setattr(tt, "get_profile", lambda: {"max_heart_rate": SYNTHETIC_MAX_HR})
    monkeypatch.setattr(tt, "tool_get_zone2_breakdown", lambda args: {"error": "no sessions"})
    raw = tt._get_training_recommendation({"date": DAY})["recommendation"]
    assert isinstance(raw.get("hr_ceiling"), int), f"the fixture no longer lands an HR-carrying branch: {raw}"
    out = tt._gated_training_recommendation({"date": DAY})
    rec = out["recommendation"]
    assert out["readiness_tier"] in ("GREEN", "YELLOW") and rec["type"] == raw["type"]
    assert rec["hr_ceiling"] is None and rec.get("hr_floor") is None and rec["effort_cue"] == sc.TALK_TEST_CUE
    assert not _problems(rec)


# ── 5. the three descriptions ────────────────────────────────────────────────────────────
def test_the_three_descriptions_state_their_real_basis(monkeypatch):
    """Item 5. The Zone 2 tool reads each device's own band, and says so; the periodization split and the load
    model's Z1 ceiling are population fractions of the profile max, and say so beside the number."""
    from mcp import tools_descriptions

    zone2 = tools_descriptions.GET_ZONE2_BREAKDOWN_DESCRIPTION
    assert "device's OWN Zone 2 band" in zone2 and "not a percent of the profile max HR" in zone2 and "never a heart-rate target" in zone2
    assert "150 min/week" in zone2  # the description still does its selection job

    methodology = _periodization_methodology(monkeypatch)
    assert "60/70/80%" in methodology and "population formula" in methodology and "never a prescription" in methodology
    assert "not thresholds measured for him" in methodology and "2026-10-10 HR regime change" in methodology

    basis = _load_basis()
    assert basis["z1_ceiling_bpm"] == training_load.Z1_CEILING_HR  # the computation is untouched
    assert basis["z1_ceiling_provenance"] == training_load.Z1_CEILING_PROVENANCE
    assert basis["z1_ceiling_provenance"].startswith("population-derived") and "never a target or cap" in basis["z1_ceiling_provenance"]
    assert training_load.Z1_CEILING_HR == round(training_load.MAX_HR * training_load.Z1_CEILING_FRACTION_OF_MAX, 1)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

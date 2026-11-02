"""tests/test_web_day_layers_5586.py — the Day's layers 2–3 (#5586, epic #5577).

The exporter side (scripts/publish_snapshot_day.py): the session set by set from /api/workouts, the night by
both devices from /api/sleep_detail, the food as logged from /api/nutrition_overview with the PLATFORM's
logging-gap flag (the behavioral series' `gap`, never a threshold here), the engine's score only when the
served sheet IS the day's, the coaches' lines exactly as /api/coach_moves serves them, the calls graded
that day and open as of it. Every block carries a state so the page can say why in place. The windowed
endpoints are read in ≤ 92-day windows, one call per endpoint per window; the fixture days carry every state.
The payloads below are trimmed captures of the live API on 2026-11-01/02.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import publish_snapshot as ps  # noqa: E402
import publish_snapshot_day as pd  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


def _set(t, r, w, rpe=None, **kw):
    return {"type": t, "reps": r, "weight_kg": w, "rpe": rpe, **kw}


# /api/workouts?from=…&to=… row for 29 October 2026 (trimmed to three of its nine exercises)
WORKOUT_1029 = {
    "date": "2026-10-29",
    "title": "Foundation - Upper - 13 - 41",
    "duration_min": 143,
    "total_volume_kg": 7932.2,
    "exercise_count": 9.0,
    "set_count": 30.0,
    "exercises": [
        {
            "name": "Bench Press (Barbell)",
            "notes": "a note the page never shows",
            "sets": [_set("warmup", 8.0, 52.2), _set("normal", 4.0, 102.1, 9.0), _set("normal", 5.0, 93.0, 8.0)],
        },
        {"name": "Suitcase Carry", "sets": [_set("normal", None, 20.0, distance_m=40.0)]},
        {"name": "Treadmill", "sets": [_set("normal", None, None)]},
    ],
}
# /api/sleep_detail sleep_trend row dated 29 October (the night of the 28th)
NIGHT_1029 = {
    "date": "2026-10-29",
    "sleep_score": 91.0,
    "efficiency": 78.5,
    "hours": 7.5,
    "deep_pct": 14.4,
    "rem_pct": 28.7,
    "light_pct": 56.9,
    "recovery_score": 74.0,
    "sleep_start": "2026-10-29T06:56:44.190Z",
    "eightsleep": {
        "night_of": "2026-10-28",
        "sleep_score": 91.0,
        "total_sleep_hours": 7.6,
        "deep_hours": 1.1,
        "rem_hours": 2.19,
        "light_hours": 4.34,
        "vendor_incomplete": False,
    },
    "whoop": {
        "night_of": "2026-10-28",
        "quality_score": 92.0,
        "total_sleep_hours": 7.5,
        "deep_hours": 1.93,
        "rem_hours": 1.97,
        "light_hours": 3.62,
    },
}
FOOD_1029 = {"date": "2026-10-29", "calories": 80, "protein_g": 15.0, "carbs_g": 4.0, "fat_g": 0.0}
CHAR_1029 = {
    "character": {"level": 15.0, "as_of_date": "2026-10-29", "composite_score": 43.1, "composite_delta_1d": 0.6, "xp_total": 106.6},
    "pillars": [
        {"name": n, "raw_score": v, "not_instrumented": ni}
        for n, v, ni in [
            ("sleep", 81.4, False),
            ("movement", 71.5, False),
            ("nutrition", 8.3, False),
            ("metabolic", 59.4, False),
            ("mind", 8.3, False),
            ("relationships", 50.0, True),
            ("consistency", 29.5, False),
        ]
    ],
}
LINE = {
    "coach_id": "mind_coach",
    "coach": "Nathan Reeves",
    "move": "reaction",
    "move_label": "On a result",
    "text": "I was wrong — my read was that stronger protein numbers would pull Matthew back toward reflection.",
    "replies_to": None,
    "bet_settles": None,
}
MOVES_1029 = {"state": "ok", "date": "2026-10-29", "lines": [LINE], "absent": [{"coach": "sleep_coach", "state": "absent"}]}


def _pred(pid, status, logged, due, settled, coach="Lisa Park", visibility="public"):
    return {
        "id": pid,
        "status": status,
        "logged_date": logged,
        "due_date": due,
        "settled_date": settled,
        "coach_name": coach,
        "title": f"claim {pid}",
        "visibility": visibility,
    }


PREDS = [
    _pred("a-1", "confirmed", "2026-10-20", "2026-10-27", "2026-10-27"),
    _pred("a-2", "pending", "2026-10-22", "2026-11-02", None),
    _pred("a-3", "pending", "2026-10-29", "2026-11-05", None, coach="Henning Brandt"),
    _pred("a-4", "pending", "2026-10-30", "2026-11-09", None),  # logged after the day: not open on it
    _pred("a-5", "expired", "2026-10-01", "2026-10-15", "2026-10-29"),  # settled without a grade
    _pred("a-6", "pending", "2026-10-20", "2026-11-03", None, visibility="private"),
]
COVER = {"workouts": {"2026-10-28", "2026-10-29"}, "sleep": {"2026-10-29"}, "nutrition": {"2026-10-29"}}


def _detail(**kw):
    base = dict(
        workouts=[WORKOUT_1029],
        night_row=NIGHT_1029,
        food_row=FOOD_1029,
        covered=COVER,
        gap_days={"2026-10-29"},
        floor_g=170.0,
        tdee=2619,
        character=CHAR_1029,
        coach_moves=MOVES_1029,
        predictions=PREDS,
        coach_ids={"mind_coach"},
    )
    base.update(kw)
    return pd.day_detail("2026-10-29", **base)


def test_the_session_is_copied_set_by_set():
    w = _detail()["workout"]
    assert (w["title"], w["duration_min"], w["volume_kg"]) == ("Foundation - Upper - 13 - 41", 143, 7932.2)
    bench = w["exercises"][0]
    assert bench["name"] == "Bench Press (Barbell)" and bench["sets"][1] == {"type": "normal", "reps": 4.0, "weight_kg": 102.1, "rpe": 9.0}
    assert "notes" not in json.dumps(w), "the session's notes are not published"
    assert "distance_m" not in json.dumps(w)
    lighter = dict(WORKOUT_1029, title="Walk - 1 - 1", total_volume_kg=0.0)
    assert pd.workout_of([lighter, WORKOUT_1029])["title"] == WORKOUT_1029["title"], "two sessions: the one that moved the most"


def test_the_night_by_two_devices():
    n = _detail()["night"]
    assert (n["deep_pct"], n["rem_pct"], n["light_pct"], n["hours"]) == (14.4, 28.7, 56.9, 7.5)
    assert n["by_device"]["eightsleep"]["hours"] == 7.6 and n["by_device"]["whoop"]["hours"] == 7.5
    assert n["by_device"]["eightsleep"]["night_of"] == "2026-10-28" and n["sleep_start"] == "2026-10-29T06:56:44.190Z"
    assert pd.night_of(dict(NIGHT_1029, whoop=None))["by_device"]["whoop"] is None


def test_food_is_as_logged_with_the_platforms_gap_flag_and_a_missing_day_is_not_zero():
    d = _detail()
    assert d["food"] == {
        "calories": 80,
        "protein_g": 15.0,
        "carbs_g": 4.0,
        "fat_g": 0.0,
        "logging_gap": True,
        "floor_g": 170.0,
        "tdee": 2619,
    }
    assert _detail(gap_days=set())["food"]["logging_gap"] is False, "the flag is the series', not a threshold on 80 kcal"
    none = _detail(food_row=None)
    assert none["food"] is None and none["food_state"] == "not logged"
    assert pd.food_of({"date": "2026-10-29", "calories": None, "protein_g": None}, logging_gap=False) is None


def test_gap_days_come_from_the_behavioral_series():
    series = {
        "total_protein_g": {"days": [{"date": "2026-10-28", "gap": True}, {"date": "2026-10-27", "gap": False}]},
        "total_calories_kcal": {"days": [{"date": "2026-10-29", "gap": True}]},
        "weight_lbs": {"days": [{"date": "2026-10-26", "gap": True}]},
    }
    assert pd.gap_days_of(series) == {"2026-10-28", "2026-10-29"}


def test_the_engine_only_when_the_sheet_is_the_days_and_absent_is_never_fifty():
    e = _detail()["engine"]
    assert (e["level"], e["composite"], e["delta"]) == (15.0, 43.1, 0.6)
    rel = next(p for p in e["pillars"] if p["name"] == "relationships")
    assert rel == {"name": "relationships", "score": None, "not_instrumented": True}
    older = {**CHAR_1029, "character": {**CHAR_1029["character"], "as_of_date": "2026-10-28"}}
    assert _detail(character=older)["engine"] is None, "the endpoint's at-or-before fallback is another day's score"
    assert pd.engine_of({"character": {"level": 1, "as_of_date": "2026-10-29", "pre_experiment": True}}, "2026-10-29") is None


def test_coach_lines_exactly_as_served_and_an_edge_only_to_a_public_coach():
    d = _detail()
    assert d["coach_lines"] == [{k: LINE[k] for k in ("coach", "coach_id", "move", "move_label", "text")}]
    assert {"type": "coach", "id": "mind_coach", "rel": "spoke"} in d["_edges"]
    assert not any(e["type"] == "coach" for e in _detail(coach_ids=set())["_edges"])
    assert _detail(coach_moves={**MOVES_1029, "date": "2026-10-30"})["coach_lines"] == [], "another day's lines never stand in"


def test_calls_graded_that_day_and_open_as_of_it():
    settled, open_, n = pd.calls_for(PREDS, "2026-10-29")
    assert settled == [], "an expired call settled that day is not a grade"
    assert [c["prediction_id"] for c in open_] == ["a-2", "a-3"] and n == 2
    assert open_[0] == {"prediction_id": "a-2", "coach_name": "Lisa Park", "due_date": "2026-11-02", "text": "claim a-2"}
    s27, _, _ = pd.calls_for(PREDS, "2026-10-27")
    assert s27 == [{"prediction_id": "a-1", "coach_name": "Lisa Park", "verdict": "confirmed", "claim_short": "claim a-1"}]
    many = [_pred(f"m-{i}", "pending", "2026-10-01", f"2026-11-{10 + i}", None) for i in range(9)]
    _, capped, total = pd.calls_for(many, "2026-10-29")
    assert len(capped) == pd.OPEN_CAP and total == 9 and capped[0]["due_date"] == "2026-11-10"


def test_each_block_states_why_it_is_empty():
    d = pd.day_detail("2026-10-28", workouts=[], night_row=None, food_row=None, covered=COVER, gap_days=set())
    assert d["workout_state"] == "none logged", "inside the window with no row: none logged"
    assert d["night_state"] == "older than the served window" and d["food_state"] == "older than the served window"
    unserved = pd.day_detail("2026-10-28", workouts=[], night_row=None, food_row=None, covered={}, gap_days=set())
    assert (unserved["workout_state"], unserved["night_state"], unserved["food_state"]) == ("not served",) * 3
    assert d["engine"] is None and d["coach_lines"] == [] and d["_in_window"] == {"workouts": True, "sleep": False, "nutrition": False}


def test_windows_are_at_most_92_days_and_one_call_per_endpoint_per_window():
    chunks = pd.window_chunks("2026-09-06", "2027-01-31")
    assert chunks[0] == ("2026-09-06", "2026-12-06") and chunks[-1][1] == "2027-01-31"
    assert all(1 <= len(pd._days(a, b)) <= 92 for a, b in chunks)
    assert all(pd.window_chunks("2026-09-06", "2026-11-01")[i] == ("2026-09-06", "2026-11-01") for i in (0,))
    calls = []

    def get(path):
        calls.append(path)
        if path.startswith("/api/workouts"):
            return {"window": {"from": "2026-09-06", "to": "2026-11-01"}, "workouts": [WORKOUT_1029]}
        if path.startswith("/api/sleep_detail"):
            return {"sleep_trend": [NIGHT_1029]}  # the old shape: no window echoed
        raise OSError("down")

    fallback = {"sleep_detail": {"sleep_trend": [NIGHT_1029, dict(NIGHT_1029, date="2026-10-30")]}}
    rows, covered, food_ctx = pd.fetch_windowed(get, "2026-09-06", "2026-11-01", fallback)
    assert calls == [
        "/api/workouts?from=2026-09-06&to=2026-11-01",
        "/api/sleep_detail?from=2026-09-06&to=2026-11-01",
        "/api/nutrition_overview?from=2026-09-06&to=2026-11-01",
    ]
    assert len(covered["workouts"]) == 57 and "2026-09-26" in covered["workouts"]
    assert covered["sleep"] == {"2026-10-29", "2026-10-30"}, "an unwindowed answer covers only the dates its default payload served"
    assert covered["nutrition"] is None and food_ctx == {}


def test_live_days_with_a_getter_carries_the_layers_and_edges():
    rows = [{"date": "2026-10-28", "day_number": 53}, {"date": "2026-10-29", "day_number": 54}]

    def get(path):
        if path.startswith("/api/workouts"):
            return {"window": {"from": "2026-10-28", "to": "2026-10-29"}, "workouts": [WORKOUT_1029]}
        if path.startswith("/api/sleep_detail"):
            return {"window": {"from": "2026-10-28", "to": "2026-10-29"}, "sleep_trend": [NIGHT_1029]}
        if path.startswith("/api/nutrition_overview"):
            return {
                "window": {"from": "2026-10-28", "to": "2026-10-29"},
                "nutrition_trend": [FOOD_1029],
                "nutrition": {"protein_floor_g": 170.0, "tdee": 2619},
            }
        if path == "/api/character?date=2026-10-29":
            return CHAR_1029
        if path == "/api/coach_moves?date=2026-10-29":
            return MOVES_1029
        return {"date": path[-10:], "lines": []}

    class Ctx:
        as_of = "2026-11-01"
        fetched = {"pulse_history": {"pulse_history": rows}}
        series = {"total_calories_kcal": {"days": [{"date": "2026-10-29", "gap": True}]}}
        objs = {"chapter": [], "metric": [], "day": [], "coach": [{"id": "mind_coach"}], "prediction": [dict(p) for p in PREDS]}

    pd.live_days(Ctx, get)
    d28, d29 = Ctx.objs["day"]
    assert d29["workout_state"] == "served" and d29["food"]["logging_gap"] is True and d29["engine"]["composite"] == 43.1
    assert d28["workout_state"] == "none logged" and d28["food_state"] == "not logged" and d28["engine"] is None
    assert d29["in_window"] == {"workouts": True, "sleep": True, "nutrition": True}
    assert {"type": "coach", "id": "mind_coach", "rel": "spoke"} in d29["edges"]
    assert {"type": "prediction", "id": "a-3", "rel": "open"} in d29["edges"]
    assert "a-6" not in json.dumps(Ctx.objs["day"]), "a private call never reaches a day"
    for o in Ctx.objs["day"]:
        ps.validate(o, "day")


def test_a_malformed_layer_is_refused():
    o = pd.day_objects(
        [{"date": "2026-10-29", "day_number": 54}],
        as_of="2026-11-01",
        metric_ids=set(),
        chapter_of_week={},
        detail={"2026-10-29": _detail()},
    )[0]
    pd.check_day(o)
    bad_engine = json.loads(json.dumps(o))
    bad_engine["engine"]["pillars"][5]["score"] = 50.0
    with pytest.raises(ps.SchemaError):
        pd.check_day(bad_engine)
    with pytest.raises(ps.SchemaError):
        pd.check_day(dict(o, workout_state="none logged"))
    with pytest.raises(ps.SchemaError):
        pd.check_day(dict(o, food={**o["food"], "logging_gap": "yes"}))


def test_fixture_days_carry_every_state():
    raw = [o for o in json.load(open(os.path.join(FIXTURES, "days.json"), encoding="utf-8")) if o["visibility"] == "public"]
    for o in raw:
        pd.check_day(o)
    states = {k: {o[k] for o in raw} for k in ("workout_state", "night_state", "food_state")}
    assert {"served", "none logged", "older than the served window"} <= states["workout_state"]
    assert {"served", "none recorded"} <= states["night_state"]
    assert {"served", "not logged"} <= states["food_state"]
    assert any(o["food"] and o["food"]["logging_gap"] for o in raw) and any(o["food"] and not o["food"]["logging_gap"] for o in raw)
    assert any(o["engine"] for o in raw) and any(o["engine"] is None for o in raw)
    assert any(o["coach_lines"] for o in raw) and any(not o["coach_lines"] for o in raw)
    assert any(o["calls_settled"] for o in raw) and any(o["calls_open"] for o in raw)
    assert any(p["not_instrumented"] and p["score"] is None for o in raw if o["engine"] for p in o["engine"]["pillars"])

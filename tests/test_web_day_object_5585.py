"""tests/test_web_day_object_5585.py — the Day object (#5585, epic #5577): /data/day/<date>/.

Holds the exporter side (scripts/publish_snapshot_day.py): the readings are copied as /api/pulse_history
serves them, the normals are the trailing 7- and 30-day means INCLUDING the day with their n (computed at
export, never in the browser), the day's chapter is its program week's, the window flags come from the
dates the three window-bound endpoints serve, and the edges point only at public objects. And the fixture:
fourteen sample days consistent with the fixture series, one without a weigh-in, one before the first
chapter, one held (the visibility gate must keep it out).
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


def _row(date: str, n: int, **kw) -> dict:
    base = {k: None for k in pd.READINGS}
    base.update(kw)
    return {"date": date, "day_number": n, **base}


# /api/pulse_history as served on 2026-11-01 for 22–29 October (trimmed to the fields the mapper reads)
LIVE_ROWS = [
    _row("2026-10-22", 47, weight_lbs=300.8, recovery_pct=60, sleep_hours=7.0, hrv_ms=55.0, rhr_bpm=53, strain=11.0, steps=9000),
    _row("2026-10-23", 48, weight_lbs=300.1, recovery_pct=70, sleep_hours=7.4, hrv_ms=56.0, rhr_bpm=52),
    _row("2026-10-24", 49, recovery_pct=66, sleep_hours=8.0, hrv_ms=57.0, rhr_bpm=53),
    _row("2026-10-25", 50, weight_lbs=299.6, recovery_pct=80, sleep_hours=8.1, hrv_ms=60.0, rhr_bpm=51),
    _row("2026-10-26", 51, weight_lbs=299.0, recovery_pct=71, sleep_hours=7.2, hrv_ms=58.0, rhr_bpm=52),
    _row(
        "2026-10-27",
        52,
        weight_lbs=299.1,
        recovery_pct=55,
        sleep_hours=6.8,
        hrv_ms=52.2,
        rhr_bpm=54,
        strain=9.9,
        steps=12169,
        active_kcal=1377,
    ),
    _row(
        "2026-10-28",
        53,
        weight_lbs=297.9,
        recovery_pct=76,
        sleep_hours=7.5,
        hrv_ms=60.3,
        rhr_bpm=51,
        strain=14.0,
        steps=7958,
        active_kcal=940,
    ),
    _row(
        "2026-10-29",
        54,
        weight_lbs=295.7,
        recovery_pct=74,
        sleep_hours=7.5,
        hrv_ms=59.8,
        rhr_bpm=52,
        strain=10.7,
        steps=9099,
        active_kcal=1306,
    ),
]


def _objs():
    return pd.day_objects(
        LIVE_ROWS,
        as_of="2026-11-01",
        metric_ids={"weight_lbs", "recovery_score", "sleep_duration_hours", "hrv", "resting_hr", "steps"},
        chapter_of_week={7: "program-week-07", 8: "program-week-08"},
        week_spans=[(7, "2026-10-18", "2026-10-24"), (8, "2026-10-25", "2026-10-31")],
        windows={"workouts": ("2026-10-02", "2026-11-01"), "sleep": ("2026-10-25", "2026-11-01"), "nutrition": None},
    )


def test_readings_are_copied_as_served_and_the_normals_include_the_day():
    days = {o["id"]: o for o in _objs()}
    d = days["2026-10-29"]
    assert d["readings"] == {k: v for k, v in LIVE_ROWS[-1].items() if k in pd.READINGS}
    w = [r["weight_lbs"] for r in LIVE_ROWS[1:] if r["weight_lbs"] is not None]  # 23–29 October: seven days, one without
    assert d["normals"]["weight_lbs"]["n7"] == len(w) == 6
    assert d["normals"]["weight_lbs"]["mean7"] == round(sum(w) / len(w), 2)
    assert d["normals"]["hrv_ms"]["n30"] == 8, "the 30-day window holds every served day so far"
    assert d["normals"]["active_kcal"] == {
        "mean7": round((1377 + 940 + 1306) / 3, 2),
        "n7": 3,
        "mean30": round((1377 + 940 + 1306) / 3, 2),
        "n30": 3,
    }
    assert days["2026-10-24"]["has_weighin"] is False and days["2026-10-24"]["summary"].startswith("no weigh-in")
    assert d["title"] == "Thursday 29 October 2026" and d["weekday"] == "Thursday" and d["day_number"] == 54
    assert "%" not in json.dumps([o["summary"] for o in days.values()]), "no bare percentage"


def test_chapter_neighbours_windows_and_edges():
    days = {o["id"]: o for o in _objs()}
    assert days["2026-10-24"]["chapter_id"] == "program-week-07" and days["2026-10-25"]["chapter_id"] == "program-week-08"
    assert days["2026-10-22"]["prev_id"] is None and days["2026-10-29"]["next_id"] is None
    assert days["2026-10-28"]["prev_id"] == "2026-10-27" and days["2026-10-28"]["next_id"] == "2026-10-29"
    assert days["2026-10-24"]["in_window"] == {"workouts": True, "sleep": False, "nutrition": False}
    assert days["2026-10-29"]["in_window"] == {"workouts": True, "sleep": True, "nutrition": False}
    edges = days["2026-10-29"]["edges"]
    assert edges[0] == {"type": "chapter", "id": "program-week-08", "rel": "this_week"}
    assert {e["id"] for e in edges[1:]} == {"weight_lbs", "recovery_score", "sleep_duration_hours", "hrv", "resting_hr", "steps"}
    assert "weight_lbs" not in {e["id"] for e in days["2026-10-24"]["edges"]}, "no edge to a measure the day has no reading of"
    for o in days.values():
        ps.validate(o, "day")


def test_week_falls_back_to_the_platform_arithmetic_and_a_bad_row_is_dropped():
    assert pd.week_of(1, "2026-09-06") == 1 and pd.week_of(7, "2026-09-12") == 1 and pd.week_of(54, "2026-10-29") == 8
    out = pd.day_objects(
        [_row("not-a-day", 3), _row("2026-09-06", 0), _row("2026-09-06", 1, weight_lbs=327.3)],
        as_of="2026-11-01",
        metric_ids=set(),
        chapter_of_week={},
    )
    assert [o["id"] for o in out] == ["2026-09-06"] and out[0]["chapter_id"] is None and out[0]["edges"] == []


def test_a_malformed_day_is_refused():
    o = _objs()[0]
    bad = dict(o, in_window={"workouts": "yes", "sleep": False, "nutrition": False})
    with pytest.raises(ps.SchemaError):
        pd.check_day(bad)
    with pytest.raises(ps.SchemaError):
        pd.check_day(dict(o, readings={**o["readings"], "vo2max": 40}))


def test_served_windows_read_dates_only():
    fetched = {
        "workouts": {"workouts": [{"date": "2026-10-02", "title": "x"}, {"date": "2026-11-01"}]},
        "sleep_detail": {"sleep_trend": [{"date": "2026-10-03"}, {"date": "2026-11-01"}]},
        "nutrition_overview": None,
    }
    assert pd.served_windows(fetched) == {
        "workouts": ("2026-10-02", "2026-11-01"),
        "sleep": ("2026-10-03", "2026-11-01"),
        "nutrition": None,
    }


def test_the_day_endpoints_are_optional_live_endpoints():
    for key, path in pd.DAY_ENDPOINTS.items():
        assert ps.LIVE_ENDPOINTS[key] == path and key in ps.OPTIONAL_ENDPOINTS
    assert ps.LIVE_ENDPOINTS["pulse_history"] == "/api/pulse_history"


def test_live_days_maps_chapters_by_week_and_skips_when_unserved():
    class Ctx:
        as_of = "2026-11-01"
        fetched = {
            "pulse_history": {"pulse_history": LIVE_ROWS},
            "chapters": {"weeks": [{"week": 8, "start": "2026-10-25", "end": "2026-10-31"}]},
        }
        objs = {
            "chapter": [{"id": "program-week-08", "week": 8, "visibility": "public"}, {"id": "week-03", "week": 0, "visibility": "public"}],
            "metric": [{"id": "weight_lbs"}],
            "day": [],
        }

    pd.live_days(Ctx)
    assert len(Ctx.objs["day"]) == 8 and Ctx.objs["day"][-1]["chapter_id"] == "program-week-08"
    assert Ctx.objs["day"][0]["chapter_id"] is None, "week 7 has no chapter object in this capture"
    Ctx.fetched = {"pulse_history": None}
    Ctx.objs["day"] = []
    pd.live_days(Ctx)
    assert Ctx.objs["day"] == []


def test_fixture_days_are_samples_consistent_with_the_fixture_series(tmp_path):
    raw = json.load(open(os.path.join(FIXTURES, "days.json"), encoding="utf-8"))
    public = [o for o in raw if o["visibility"] == "public"]
    assert len(public) == 14 and all(o["sample"] for o in raw)
    assert any(o["visibility"] == "held" for o in raw), "a held day the visibility gate must keep out"
    series = {d["date"]: d["value"] for d in json.load(open(os.path.join(FIXTURES, "series", "weight_lbs.json")))["days"]}
    assert all(o["readings"]["weight_lbs"] == series.get(o["date"]) for o in public)
    assert any(not o["has_weighin"] for o in public), "one day without a weigh-in"
    chapters = json.load(open(os.path.join(FIXTURES, "chapters.json"), encoding="utf-8"))
    first = min(c["date"] for c in chapters if c["visibility"] == "public")
    assert any(o["chapter_id"] is None and o["date"] < first for o in public), "one day before the first chapter"
    manifest = ps.run("fixture", str(tmp_path / "s"), FIXTURES, ps.DEFAULT_BASE_URL, 5.0)
    assert manifest["files"]["days.json"]["count"] == 14
    written = open(tmp_path / "s" / "days.json", encoding="utf-8").read()
    assert "SENTINEL" not in written and "POISON" not in written

"""tests/test_coach_weekday_contract_5274.py — every coach-facing date carries a Pacific `weekday` (#5274).

On 2026-10-23 a coach labelled 16, 18, 19 and 21 October as Thu/Sat/Sun/Tue. They were Fri/Sun/Mon/Wed.
The coach-facing MCP tools returned ISO dates only, so the model derived the weekday itself. Each response
path below now carries `"weekday"` beside its date, from ONE helper (`common.pacific_time.pacific_weekday`).

`CONTRACT` enumerates the response paths the issue names; `test_every_contract_path_carries_the_pacific_weekday`
walks each one and reds on a date with no `weekday` sibling, or a wrong one. Every fixture date is fixed (no
clock read decides an asserted value), and the fixture includes a 21:30 PT Friday session and walk whose UTC
instant is SATURDAY — a weekday derived from the UTC timestamp would say "Sat" and red.

The expected weekdays are a hand-written calendar (`CALENDAR`), not the helper under test.

Mutations run while writing this (each reds the named test, restored after):
  * drop `"weekday"` from `recent_aerobic._public_row`  -> the contract test (recent_aerobic.rows[]) and the
                                                          no-own-weekday test (the module no longer calls the helper)
  * `pacific_weekday` taking an instant's UTC date      -> the contract test (today.activities[].start), the late-
                                                          Friday test and the helper test
  * `WEEKDAY_ABBR` rotated by one                       -> the contract, late-Friday and helper tests
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.pacific_time import pacific_weekday  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The calendar, written out by hand — the independent truth the helper is checked against.
CALENDAR = {
    "2026-10-13": "Tue",
    "2026-10-14": "Wed",
    "2026-10-15": "Thu",
    "2026-10-16": "Fri",
    "2026-10-17": "Sat",
    "2026-10-18": "Sun",
    "2026-10-19": "Mon",
    "2026-10-20": "Tue",
    "2026-10-21": "Wed",
    "2026-10-22": "Thu",
    "2026-10-23": "Fri",
}

# 21:30 PDT on Friday 2026-10-16 is 04:30Z on SATURDAY 2026-10-17. Hevy and Strava both key the row by the
# LOCAL day of its start, so the row's `date` is the Friday.
LATE_FRI_START = "2026-10-17T04:30:00Z"
LATE_FRI_END = "2026-10-17T05:20:00Z"


def _hevy(day: str, wid: str, title: str, start: str, end: str) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "date": day,
        "workout_uid": f"hevy:{wid}",
        "source": "hevy",
        "source_workout_id": wid,
        "title": title,
        "start_time": start,
        "end_time": end,
        "duration_sec": 3000,
        "exercise_count": 1,
        "set_count": 3,
        "total_volume_kg": 1000.0,
        "exercises": [{"name": "Squat (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 8}] * 3}],
    }


HEVY_ROWS = [
    _hevy("2026-10-16", "w-fri", "Lower A", LATE_FRI_START, LATE_FRI_END),  # the late-evening Friday
    _hevy("2026-10-18", "w-sun", "Upper A", "2026-10-18T15:00:00Z", "2026-10-18T16:00:00Z"),
    _hevy("2026-10-19", "w-mon", "Lower B", "2026-10-19T15:00:00Z", "2026-10-19T16:00:00Z"),
    _hevy("2026-10-21", "w-wed", "Upper B", "2026-10-21T15:00:00Z", "2026-10-21T16:00:00Z"),
]


def _walk(sid: str, start: str, minutes: int) -> dict:
    return {
        "strava_id": sid,
        "name": "Evening Walk",
        "sport_type": "Walk",
        "type": "Walk",
        "device_name": "Garmin",
        "start_date": start,
        "moving_time_seconds": minutes * 60,
        "elapsed_time_seconds": minutes * 60,
        "distance_miles": 2.0,
        "average_heartrate": 105.0,
        "max_heartrate": 120.0,
    }


STRAVA_ROWS = [
    # 22:30 PDT Friday = 05:30Z Saturday, after the Hevy session — not a duplicate of it.
    {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2026-10-16",
        "date": "2026-10-16",
        "activities": [_walk("s-fri", "2026-10-17T05:30:00Z", 40)],
    },
    {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2026-10-15",
        "date": "2026-10-15",
        "activities": [_walk("s-thu", "2026-10-15T16:00:00Z", 30)],
    },
]


# ── the response paths, one reader each ───────────────────────────────────────────────────
def _get_workouts(monkeypatch):
    from mcp import tools_hevy

    monkeypatch.setattr(tools_hevy, "query_source_range", lambda src, s, e, include_pilot=True: list(HEVY_ROWS) if src == "hevy" else [])
    out = tools_hevy.tool_get_workouts({"start_date": "2026-10-13", "end_date": "2026-10-22"})
    return [("get_workouts.workouts[]", out["workouts"], "date")]


def _last_session_by_type(monkeypatch):
    import training.routine_title as rt

    from mcp import tools_coach_packet as pkt, tools_strength

    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: (list(HEVY_ROWS), ["experiment"]))
    monkeypatch.setattr(rt, "_load_routine_index", lambda start: [])
    monkeypatch.setattr(rt, "resolve_archetype", lambda it, index: it.get("title", "").lower().replace(" ", "_"))
    positions = {
        "2026-10-16": {"session_role": "lower_a", "workout_id": None, "position_label": "W1 S1"},
        "2026-10-19": {"session_role": "lower_b", "workout_id": None, "position_label": "W1 S3"},
    }
    monkeypatch.setattr(pkt, "_sequence_positions", lambda t: (positions, {"state": "measured", "not_credited": []}))
    value = pkt._last_sessions("2026-10-22")
    assert value["by_session_role"], "the fixture no longer credits a role — the by_session_role path is unexercised"
    return [
        ("get_coach_session_packet.last_session_by_type.by_archetype{}", list(value["by_archetype"].values()), "date"),
        ("get_coach_session_packet.last_session_by_type.by_session_role{}", list(value["by_session_role"].values()), "date"),
    ]


def _today(monkeypatch):
    import training.routine_title as rt

    from mcp.coach_packet_today import today_view

    monkeypatch.setattr(rt, "_load_routine_index", lambda start: [])
    value, _status = today_view(
        "2026-10-17",
        today="2026-10-20",
        read_hevy=lambda d: [w for w in HEVY_ROWS if w["date"] == d],
        read_strava=lambda d: [r for r in STRAVA_ROWS if r["date"] == d],
    )
    starts = [{"date": a["start"]["utc"], **a["start"]} for a in value["activities"] if a.get("start")]
    assert len(starts) == 2, f"the fixture's Friday session and walk should both list: {value['activities']}"
    return [
        ("get_coach_session_packet.today", [value], "day"),
        # The instant's weekday is the PACIFIC day of the UTC stamp — checked against the row's Pacific day below.
        ("get_coach_session_packet.today.activities[].start", [{**s, "pacific_day": "2026-10-16"} for s in starts], "pacific_day"),
    ]


def _steps_7d(monkeypatch):
    from mcp import tools_coach_packet as pkt

    monkeypatch.setattr(pkt, "_steps_fetch", lambda source, s, e: [])
    value, _status = pkt._steps("2026-10-22")
    assert len(value["days"]) == 7
    return [("get_coach_session_packet.steps_7d.days[]", value["days"], "date")]


def _nutrition_daily(monkeypatch):
    from mcp import tools_coach_packet as pkt, tools_nutrition, tools_plan

    days = ["2026-10-16", "2026-10-18", "2026-10-19", "2026-10-21"]
    monkeypatch.setattr(
        tools_nutrition,
        "tool_get_nutrition",
        lambda a: {
            "period": {"days_with_data": len(days)},
            "daily_averages": {"calories_kcal": 2000.0, "protein_g": 190.0},
            "target_comparison": {},
            "daily_breakdown": [{"date": d, "calories_kcal": 2000.0, "protein_g": 190.0} for d in days],
        },
    )
    monkeypatch.setattr(tools_plan, "_protein_days_7d", lambda d: (0, 4))
    value, _status = pkt._nutrition("2026-10-22")
    return [("get_coach_session_packet.nutrition_7d.daily[]", value["daily"], "date")]


def _recent_aerobic(monkeypatch):
    from mcp import shared_quantities

    rows = {"strava": STRAVA_ROWS, "hevy": []}
    block = shared_quantities.recent_aerobic_layer("2026-10-17", today="2026-10-20", read=lambda src, s, e: list(rows.get(src) or []))
    assert {r["date"] for r in block["rows"]} == {"2026-10-15", "2026-10-16"}, block["rows"]
    return [("plan_next_session.constraint_block.recent_aerobic.rows[]", block["rows"], "date")]


CONTRACT = [_get_workouts, _last_session_by_type, _today, _steps_7d, _nutrition_daily, _recent_aerobic]


def test_every_contract_path_carries_the_pacific_weekday(monkeypatch):
    """Walk every enumerated response path; report EVERY offender (one gate, not one per path)."""
    offenders: list[str] = []
    covered: list[str] = []
    for reader in CONTRACT:
        for path, rows, key in reader(monkeypatch):
            assert rows, f"{path}: the fixture produced no rows — the path is unexercised"
            covered.append(path)
            for r in rows:
                day = str(r.get(key) or "")[:10]
                if day not in CALENDAR:
                    offenders.append(f"{path}: date {r.get(key)!r} is outside the fixture calendar")
                elif "weekday" not in r:
                    offenders.append(f"{path}: {day} has no `weekday` sibling")
                elif r["weekday"] != CALENDAR[day]:
                    offenders.append(f"{path}: {day} says {r['weekday']!r}, the calendar says {CALENDAR[day]!r}")
    assert not offenders, "\n".join(offenders)
    assert len(covered) == 8, covered


def test_the_late_evening_friday_is_friday_not_the_utc_saturday(monkeypatch):
    """The four dates the coach got wrong, plus the evening-PT instant whose UTC date is the next day."""
    workouts = {w["date"]: w["weekday"] for w in _get_workouts(monkeypatch)[0][1]}
    assert workouts == {"2026-10-16": "Fri", "2026-10-18": "Sun", "2026-10-19": "Mon", "2026-10-21": "Wed"}
    today = _today(monkeypatch)[0][1][0]
    assert today["day"] == "2026-10-16" and today["weekday"] == "Fri"
    fri_session = next(a for a in today["activities"] if a["source"] == "hevy")
    assert fri_session["start"]["utc"].startswith("2026-10-17") and fri_session["start"]["weekday"] == "Fri"


def test_the_helper_reads_day_keys_and_pacific_instants():
    assert [pacific_weekday(d) for d in ("2026-10-16", "2026-10-18", "2026-10-19", "2026-10-21")] == ["Fri", "Sun", "Mon", "Wed"]
    assert pacific_weekday(LATE_FRI_START) == "Fri"  # Saturday in UTC
    assert pacific_weekday("2026-10-17T04:30:00+00:00") == "Fri"
    assert pacific_weekday("2026-10-16T21:30:00-07:00") == "Fri"
    # PST side of the 2026-11-01 DST change: 23:30 PST Sunday = 07:30Z Monday.
    assert pacific_weekday("2026-11-02T07:30:00Z") == "Sun"
    for bad in (None, "", "not-a-date", "2026-13-40"):
        assert pacific_weekday(bad) is None


def test_no_producer_spells_its_own_weekday():
    """One helper (#5274): no producer on the contract paths formats a weekday itself."""
    files = [
        "mcp/tools_hevy.py",
        "mcp/tools_coach_packet.py",
        "mcp/coach_packet_today.py",
        "lambdas/training/steps_resolver.py",
        "lambdas/training/recent_aerobic.py",
    ]
    offenders = []
    for rel in files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for spell in ('strftime("%a")', 'strftime("%A")', "calendar.day_abbr", "calendar.day_name"):
            if spell in text:
                offenders.append(f"{rel}: {spell}")
        if "pacific_weekday(" not in text:
            offenders.append(f"{rel}: no pacific_weekday call — its dates are not on the shared helper")
    assert not offenders, offenders


def test_the_coach_prose_says_to_quote_the_returned_weekday():
    text = (ROOT / ".claude/skills/coach-session/SKILL.md").read_text(encoding="utf-8")
    assert "`weekday`" in text and "#5274" in text
    from mcp.tools_coach_packet import COACH_PACKET_DESCRIPTION

    assert "weekday" in COACH_PACKET_DESCRIPTION

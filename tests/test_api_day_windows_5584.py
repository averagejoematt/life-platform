"""tests/test_api_day_windows_5584.py — the optional day window on three read routes (#5584).

``/api/workouts``, ``/api/sleep_detail`` and ``/api/nutrition_overview`` take ``?date=`` or
``?from=&to=`` (contract: ``lambdas/web/day_window.py``) so the Day pages can serve any day
since genesis. Pinned here, per route: the no-parameter response is unchanged (same body,
same trailing reads, no ``window`` key), a bounded window serves only its days and echoes
itself, the clamp (genesis floor, today ceiling, 92-day span), and the 400s.

Fixtures are the wire: rows carry the stored ``pk``/``sk`` keys and field names of the real
partitions (Hevy WORKOUT# rows, Eight Sleep / Whoop / MacroFactor DATE# rows), the source
reader filters on the inclusive ``between`` the real one issues, and the fake DynamoDB table
evaluates the handler's own boto3 key condition and pages like DynamoDB does. Every clock
the handlers read is frozen (#4848).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from web import (
    day_window,  # noqa: E402
    site_api_common as sac,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
    site_api_nutrition as nut,  # noqa: E402
    site_api_observatory as obs,  # noqa: E402
    site_api_training as training,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
)

GENESIS = "2026-09-06"
TODAY = "2026-10-20"
FROZEN_NOW = datetime(2026, 10, 20, 19, 0, 0, tzinfo=timezone.utc)  # noon Pacific on TODAY
D30 = "2026-09-21"  # the inclusive start of the 30-day window ending TODAY (_experiment_date(30))


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.replace(tzinfo=None) if tz is None else FROZEN_NOW.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


def _days(start: str, end: str) -> list[str]:
    from datetime import date, timedelta

    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _date_of(row: dict) -> str:
    return row.get("date") or str(row.get("sk", "")).replace("DATE#", "")[:10]


class FakeSources:
    """site_api_common._query_source: the inclusive [start, end] DATE# window, fresh copies, calls recorded."""

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, source, start, end, include_pilot=None, projection=None):
        self.calls.append((source, start, end))
        if start > end:
            return []
        return [dict(r) for r in self.data.get(source, []) if start <= _date_of(r) <= end]

    def bounds(self, source: str) -> set[tuple[str, str]]:
        return {(s, e) for src, s, e in self.calls if src == source}


class FakeTable:
    """A DynamoDB table that evaluates the handler's own ``pk = :pk AND sk BETWEEN :a AND :b``
    condition, honours ScanIndexForward, and pages ``page_size`` items at a time."""

    def __init__(self, items, page_size=1000):
        self.items = list(items)
        self.page_size = page_size
        self.calls: list[dict] = []

    def query(self, **kw):
        self.calls.append(kw)
        eq, between = kw["KeyConditionExpression"].get_expression()["values"]
        pk = eq.get_expression()["values"][1]
        _, lo, hi = between.get_expression()["values"]
        rows = sorted((r for r in self.items if r["pk"] == pk and lo <= r["sk"] <= hi), key=lambda r: r["sk"])
        if not kw.get("ScanIndexForward", True):
            rows.reverse()
        start = int(kw.get("ExclusiveStartKey", {}).get("i", 0))
        page = rows[start : start + self.page_size]
        resp = {"Items": [dict(r) for r in page]}
        if start + self.page_size < len(rows):
            resp["LastEvaluatedKey"] = {"i": start + self.page_size}
        return resp


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    for mod in (sac, nut, training, vitals):
        monkeypatch.setattr(mod, "datetime", _FrozenDatetime)
    for mod in (sac, obs, vitals):
        monkeypatch.setattr(mod, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(day_window, "pacific_today", lambda: TODAY)
    monkeypatch.setattr(nut, "_get_profile", lambda: {"height_inches": 72})
    yield


def _body(resp: dict) -> dict:
    body = json.loads(resp["body"])
    body.pop("_meta", None)  # served_at / request_id — the request instant, not the data
    return body


def _hevy(day: str, n: int = 1) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#w{n}",
        "date": day,
        "title": f"Session {day}",
        "duration_sec": 3600,
        "total_volume_kg": 5000,
        "exercise_count": 1,
        "set_count": 1,
        "exercises": [{"name": "Deadlift (Barbell)", "sets": [{"type": "normal", "reps": 5, "weight_kg": 100}]}],
    }


def _eight(day: str) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#eightsleep",
        "sk": f"DATE#{day}",
        "sleep_score": 82,
        "sleep_efficiency_pct": 90.1,
        "sleep_duration_hours": 7.4,
    }


def _whoop(day: str) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": f"DATE#{day}",
        "sleep_duration_hours": 7.6,
        "sleep_quality_score": 85,
        "recovery_score": 70,
        "hrv": 55.0,
        "resting_heart_rate": 52,
        "sleep_start": f"{day}T05:30:00Z",
        "sleep_end": f"{day}T13:00:00Z",
    }


def _mf(day: str) -> dict:
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{day}", "date": day, "total_calories_kcal": 2100, "total_protein_g": 180}


ALL_DAYS = _days(GENESIS, TODAY)


@pytest.fixture
def wired(monkeypatch):
    """Every day since genesis populated on all three routes' partitions."""
    table = FakeTable([_hevy(d) for d in ALL_DAYS])
    sources = FakeSources(
        eightsleep=[_eight(d) for d in ALL_DAYS], whoop=[_whoop(d) for d in ALL_DAYS], macrofactor=[_mf(d) for d in ALL_DAYS]
    )
    monkeypatch.setattr(obs, "table", table)
    monkeypatch.setattr(obs, "_query_source", sources)
    monkeypatch.setattr(vitals, "_query_source", sources)
    return table, sources


ROUTES = {
    "/api/workouts": (obs.handle_workouts, "workouts", "date"),
    "/api/sleep_detail": (vitals.handle_sleep_detail, "sleep_trend", "date"),
    "/api/nutrition_overview": (obs.handle_nutrition_overview, "nutrition_trend", "date"),
}


# ── the parse (one contract for all three) ────────────────────────────────────


def test_parse_contract():
    p = lambda qs: day_window.parse(qs, today=TODAY, floor=GENESIS)  # noqa: E731
    assert p(None) == (None, None) and p({}) == (None, None) and p({"from": "", "utm": "x"}) == (None, None)
    assert p({"date": "2026-09-26"})[0] == ("2026-09-26", "2026-09-26")
    assert p({"from": "2026-09-20", "to": "2026-09-26"})[0] == ("2026-09-20", "2026-09-26")
    assert p({"from": "2026-10-01"})[0] == ("2026-10-01", TODAY)  # to defaults to today
    assert p({"to": "2026-09-30"})[0] == (GENESIS, "2026-09-30")  # from defaults to a 92-day reach, floored
    assert p({"from": "2026-01-01", "to": "2026-09-10"})[0] == (GENESIS, "2026-09-10")  # floor
    assert p({"from": "2026-10-10", "to": "2027-01-01"})[0] == ("2026-10-10", TODAY)  # ceiling
    long = day_window.parse({"from": "2026-09-06", "to": "2026-12-31"}, today="2026-12-31", floor=GENESIS)[0]
    assert long == ("2026-10-01", "2026-12-31")  # 117 days asked → the 92 ending at `to`
    for bad in ({"date": "2026-9-26"}, {"from": "2026-02-30"}, {"to": "yesterday"}, {"date": "2026-09-26", "from": "2026-09-20"}):
        window, err = p(bad)
        assert window is None and err["statusCode"] == 400, bad
    for outside in ({"from": "2026-09-26", "to": "2026-09-20"}, {"date": "2026-08-01"}, {"date": "2026-12-01"}):
        window, err = p(outside)
        assert window is None and err["statusCode"] == 400, outside


# ── default unchanged, per route ──────────────────────────────────────────────


def test_no_parameter_responses_are_unchanged(wired):
    """No ``from``/``to``/``date`` → the same body whether the query is absent, empty or unrelated,
    the trailing reads the route always issued, and no ``window`` key."""
    table, sources = wired
    for path, (handler, series, _) in ROUTES.items():
        bare = handler()
        assert bare["statusCode"] == 200, path
        for qs in (None, {}, {"utm_source": "x"}, {"from": "", "to": " "}):
            assert _body(handler(qs)) == _body(bare), (path, qs)
            assert bare["headers"]["Cache-Control"] == handler(qs)["headers"]["Cache-Control"]
        assert "window" not in _body(bare), path
    # workouts: the 30 most recent of a 31-day reach (today-30 .. today), newest first
    w = _body(obs.handle_workouts())["workouts"]
    assert len(w) == 30 and w[0]["date"] == TODAY and w[-1]["date"] == "2026-09-21"
    assert sources.bounds("eightsleep") == {(D30, TODAY)} and sources.bounds("macrofactor") == {(D30, TODAY)}
    assert [r["date"] for r in _body(vitals.handle_sleep_detail())["sleep_trend"]] == _days(D30, TODAY)


def test_the_router_falls_through_to_routes_without_a_window(wired):
    for path, (handler, _, _) in ROUTES.items():
        via = L._dispatch_route({"rawPath": path, "queryStringParameters": None}, path, "GET")
        assert _body(via) == _body(handler()), path
        assert "window" not in _body(via)


# ── a bounded window, per route ───────────────────────────────────────────────


def test_a_bounded_window_serves_only_its_days_and_echoes_itself(wired):
    for path, (_, series, key) in ROUTES.items():
        qs = {"from": "2026-09-20", "to": "2026-09-26"}
        resp = L._dispatch_route({"rawPath": path, "queryStringParameters": qs}, path, "GET")
        assert resp["statusCode"] == 200, path
        body = _body(resp)
        assert body["window"] == {"from": "2026-09-20", "to": "2026-09-26"}, path
        assert sorted(r[key] for r in body[series]) == _days("2026-09-20", "2026-09-26"), path


def test_one_date_is_that_day(wired):
    for path, (handler, series, key) in ROUTES.items():
        body = _body(handler({"date": "2026-09-26"}))
        assert body["window"] == {"from": "2026-09-26", "to": "2026-09-26"}
        assert [r[key] for r in body[series]] == ["2026-09-26"], path


def test_a_day_with_no_session_is_an_honest_empty_list(wired, monkeypatch):
    monkeypatch.setattr(obs, "table", FakeTable([_hevy(d) for d in ALL_DAYS if d != "2026-09-26"]))
    body = _body(obs.handle_workouts({"date": "2026-09-26"}))
    assert body["workouts"] == [] and body["count"] == 0 and body["window"]["from"] == "2026-09-26"


def test_the_window_moves_the_reads_not_the_partitions(wired):
    table, sources = wired
    obs.handle_nutrition_overview({"from": "2026-09-20", "to": "2026-09-26"})
    vitals.handle_sleep_detail({"from": "2026-09-20", "to": "2026-09-26"})
    assert sources.bounds("macrofactor") == {("2026-09-20", "2026-09-26")}
    assert sources.bounds("eightsleep") == {("2026-09-20", "2026-09-26")} and sources.bounds("whoop") >= {("2026-09-20", "2026-09-26")}
    assert {c[0] for c in sources.calls} <= {"macrofactor", "eightsleep", "whoop", "supplements", "habitify", "strava", "hevy", "withings"}
    obs.handle_workouts({"from": "2026-09-20", "to": "2026-09-26"})
    cond = table.calls[-1]["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"]
    assert cond[1:] == ("DATE#2026-09-20#WORKOUT#", "DATE#2026-09-26#WORKOUT#~")


def test_a_windowed_nutrition_response_keeps_the_default_shape_and_serves_no_forward_bet(wired):
    default, windowed = _body(obs.handle_nutrition_overview()), _body(
        obs.handle_nutrition_overview({"from": "2026-09-20", "to": "2026-09-26"})
    )
    assert set(windowed) - {"window"} == set(default)
    assert set(windowed["nutrition"]) == set(default["nutrition"])
    assert windowed["projection"] is None  # a weight-crossing bet is stated from today only
    sleep_default, sleep_windowed = _body(vitals.handle_sleep_detail()), _body(vitals.handle_sleep_detail({"date": "2026-09-26"}))
    assert set(sleep_windowed) - {"window"} == set(sleep_default)
    assert set(sleep_windowed["sleep_detail"]) == set(sleep_default["sleep_detail"])
    assert sleep_windowed["sleep_detail"]["as_of_date"] == "2026-09-26"


def test_a_30d_named_sleep_key_carries_a_value_only_over_a_true_30_days(wired):
    """#1917 under a window: a 92-day average never ships under a ``30d_`` name."""
    exact = _body(vitals.handle_sleep_detail({"from": D30, "to": TODAY}))["sleep_detail"]
    longer = _body(vitals.handle_sleep_detail({"from": GENESIS, "to": TODAY}))["sleep_detail"]
    assert exact["30d_avg_score"] is not None and exact["avg_window_days"] == 30
    assert longer["30d_avg_score"] is None and longer["avg_score_window"] is not None and longer["avg_window_days"] == 45


# ── the clamp, per route ──────────────────────────────────────────────────────


def test_the_clamp_floors_at_genesis_ceils_at_today_and_echoes_the_served_window(wired, monkeypatch):
    for path, (handler, series, key) in ROUTES.items():
        body = _body(handler({"from": "2026-01-01", "to": "2027-03-01"}))
        assert body["window"] == {"from": GENESIS, "to": TODAY}, path
        served = sorted(r[key] for r in body[series])
        assert served[0] >= GENESIS and served[-1] <= TODAY, path
    # every session in a long window — the default's 30-row cap does not apply — across DynamoDB pages
    table = FakeTable([_hevy(d) for d in ALL_DAYS], page_size=10)
    monkeypatch.setattr(obs, "table", table)
    body = _body(obs.handle_workouts({"from": GENESIS, "to": TODAY}))
    assert body["count"] == len(ALL_DAYS) == 45 and len(table.calls) == 5


# ── the 400s, per route ───────────────────────────────────────────────────────


def test_an_invalid_window_is_a_400_in_the_one_error_envelope(wired):
    for path in ROUTES:
        for qs in (
            {"date": "2026-13-01"},
            {"from": "2026-09-26", "to": "2026-09-20"},
            {"date": "2026-08-01"},
            {"date": "2026-09-26", "to": "x"},
        ):
            resp = L._dispatch_route({"rawPath": path, "queryStringParameters": qs}, path, "GET")
            assert resp["statusCode"] == 400, (path, qs)
            body = json.loads(resp["body"])
            assert isinstance(body["error"], str) and body["error"], (path, qs)
            assert resp["headers"]["Cache-Control"] == "no-cache, no-store"


def test_the_window_adds_no_route():
    assert set(L._DAY_WINDOW_ROUTES) <= set(L.ROUTES)
    assert all(L.ROUTES[p] is h for p, h in L._DAY_WINDOW_ROUTES.items())

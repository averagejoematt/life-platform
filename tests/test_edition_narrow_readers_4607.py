"""tests/test_edition_narrow_readers_4607.py — the edition's narrow nutrition and training reads are the routes' own (#4607).

Measured after #4669 deployed (2026-10-10, in-Lambda p50): ``/api/nutrition_overview`` 1,021 ms
and ``/api/training_overview`` 725 ms were two of the four slowest upstreams of ``/api/edition``,
and the edition reads five facts from one and one key from the other. Round 2 gives each a
narrow reader — one projected window instead of the whole route.

What this file holds, over one fake table that honours the key condition AND the projection
(so a field the narrow projection drops is really absent from what the reader sees):

  * each narrow reader returns, field for field, the subset of the route's body the edition
    reads — and the edition's ``week`` and ``life`` blocks composed from either are identical;
  * each reader makes only its projected reads (one window for nutrition, two for training);
  * MUST_FAIL: a projection narrowed one field too far is caught by the same comparison, so the
    fixture really exercises every field the projections carry.

Offline: a fake table only.
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from coach import persona_registry  # noqa: E402
from common.constants import PLAN_DAILY_PROTEIN_MIN_G  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_common as common,
    site_api_edition as ed,
    site_api_nutrition as nutrition_mod,
    site_api_observatory as obs,
    site_api_training as training_mod,
)
from web.prediction_reason import metric_words  # noqa: E402

_WIRE_DIR = os.path.join(_REPO, "tests", "fixtures", "edition_wire_4582")
_PREFIX = common.USER_PREFIX


def _today():
    return datetime.now(common.PT).strftime("%Y-%m-%d")


def _day(n_back):
    return (datetime.now(common.PT) - timedelta(days=n_back)).strftime("%Y-%m-%d")


# ── the fixture: rows relative to today, so the routes' own clocks see them in-window ──


def _macrofactor_rows():
    """Legacy and current macro field names, an honest zero, a day with no protein cell, a
    superseded row, a row outside the window, and the food log the edition never reads."""
    food_log = [{"time": "08:15", "food_name": "eggs", "protein_g": 30}, {"time": "19:40", "food_name": "steak", "protein_g": 60}]
    rows = [
        {"sk": f"DATE#{_day(40)}", "date": _day(40), "total_calories_kcal": 2500, "total_protein_g": 200},  # outside 30 d
        {"sk": f"DATE#{_day(9)}", "date": _day(9), "calories": 1810.4, "protein_g": 171.26, "food_log": food_log},
        {"sk": f"DATE#{_day(8)}", "date": _day(8), "total_calories_kcal": 1650, "total_protein_g": 150.04, "total_carbs_g": 90},
        {"sk": f"DATE#{_day(7)}", "date": _day(7), "total_calories": 1920, "total_protein_g": 0, "total_fat_g": 70},
        {
            "sk": f"DATE#{_day(6)}",
            "date": _day(6),
            "total_calories_kcal": 1700,
            "total_protein_g": PLAN_DAILY_PROTEIN_MIN_G,
        },  # AT the floor
        {"sk": f"DATE#{_day(5)}", "date": _day(5), "total_calories_kcal": 1700, "food_log": food_log},  # no protein cell
        {"sk": f"DATE#{_day(4)}", "date": _day(4), "total_calories_kcal": 1600, "total_protein_g": 185, "tombstone": True},
        {"sk": f"DATE#{_day(3)}", "total_calories_kcal": 1755.5, "protein_g": 182.95, "total_protein_g": 1.0},  # no `date`
        {"sk": f"DATE#{_day(1)}", "date": _day(1), "calories": 0, "protein_g": 190, "total_fiber_g": 31, "food_log": food_log},
    ]
    for r in rows:
        r.update(pk=f"{_PREFIX}macrofactor", phase="experiment")
    return rows


def _strava_rows():
    """WHOOP duplicates of a Garmin walk (dropped), a WHOOP-only workout (kept), a row with
    no activity list standing in as one activity, a superseded row, and heavy fields."""
    polyline = "x" * 4000
    rows = [
        {
            "sk": f"DATE#{_day(6)}",
            "date": _day(6),
            "activities": [
                {"sport_type": "Walk", "device_name": "Garmin Forerunner", "moving_time_seconds": 2700, "polyline": polyline},
                {"sport_type": "Walk", "device_name": "WHOOP", "moving_time_seconds": 2650},
                {"sport_type": "WeightTraining", "device_name": "WHOOP", "duration_minutes": 52.4},
            ],
            "total_distance_miles": 2.1,
        },
        {"sk": f"DATE#{_day(4)}", "date": _day(4), "activities": [], "sport_type": "Ride", "moving_time_minutes": 41, "splits": polyline},
        {"sk": f"DATE#{_day(2)}", "date": _day(2), "activities": [{"type": "Yoga", "moving_time_seconds": 1500}], "tombstone": True},
        {"sk": f"DATE#{_day(1)}", "date": _day(1), "activities": [{"sport_type": "Soccer", "moving_time_seconds": 3600}]},
        {"sk": f"DATE#{_day(0)}", "date": _day(0), "activities": [{"sport_type": "Hike", "duration_minutes": 95}]},
    ]
    for r in rows:
        r.update(pk=f"{_PREFIX}strava", phase="experiment")
    return rows


def _apple_health_rows():
    rows = [
        {"sk": f"DATE#{_day(6)}", "date": _day(6), "breathwork_minutes": 12.6, "steps": 9000, "heart_rate_samples": list(range(200))},
        {"sk": f"DATE#{_day(3)}", "date": _day(3), "breathwork_minutes": 0, "mindful_minutes": 10, "steps": 4000},
        {"sk": f"DATE#{_day(0)}", "breathwork_minutes": 5, "steps": 1200},
    ]
    for r in rows:
        r.update(pk=f"{_PREFIX}apple_health", phase="experiment")
    return rows


def _table(rows, queries):
    """A table answering pk + sk BETWEEN key conditions and honouring ProjectionExpression."""
    by_pk: dict = {}
    for r in rows:
        by_pk.setdefault(r["pk"], []).append(r)

    def hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        pk_cond, sk_cond = (expr["values"][0], expr["values"][1]) if expr.get("operator") == "AND" else (kw["KeyConditionExpression"], None)
        pk = pk_cond.get_expression()["values"][1]
        out = sorted(by_pk.get(pk, []), key=lambda r: r["sk"])
        if sk_cond is not None:
            sk = sk_cond.get_expression()
            if sk["operator"] == "BETWEEN":
                lo, hi = sk["values"][1], sk["values"][2]
                out = [r for r in out if lo <= r["sk"] <= hi]
            elif sk["operator"] == "BEGINS_WITH":
                out = [r for r in out if r["sk"].startswith(sk["values"][1])]
        fields = None
        if kw.get("ProjectionExpression"):
            names = kw.get("ExpressionAttributeNames") or {}
            fields = tuple(names.get(n.strip(), n.strip()) for n in kw["ProjectionExpression"].split(","))
            out = [{f: r[f] for f in fields if f in r} for r in out]
        queries.append((pk, fields))
        return {"Items": json.loads(json.dumps(out))}

    return FakeDdbTable(query_hook=hook, get_item_hook=lambda table, key, **kw: {})


@pytest.fixture
def fake_table(monkeypatch):
    queries: list = []
    table = _table(_macrofactor_rows() + _strava_rows() + _apple_health_rows(), queries)
    for mod in (common, obs):
        monkeypatch.setattr(mod, "table", table)
    return queries


def _compose_with(key, body):
    bodies = {}
    for k in ed.SOURCES:
        with open(os.path.join(_WIRE_DIR, f"{k}.json"), encoding="utf-8") as fh:
            bodies[k] = json.load(fh)
    bodies[key] = body
    today = _today()
    return ed.compose(
        bodies,
        today=today,
        now=datetime.now(common.PT),
        start_date=common.EXPERIMENT_START,
        persona_of=persona_registry.resolve,
        persona_of_short=lambda sid: persona_registry.by_short_id(sid)[1],
        metric_words=metric_words,
    )


def _edition_nutrition_subset(body):
    n = body["nutrition"]
    return {
        "nutrition": {k: n[k] for k in ("protein_floor_g", "protein_floor_hit_days", "days_logged", "latest_date")},
        "nutrition_trend": [{k: r[k] for k in nutrition_mod._EDITION_TREND_KEYS} for r in body["nutrition_trend"]],
    }


# ── nutrition ────────────────────────────────────────────────────────────────────


def test_the_narrow_nutrition_reader_serves_the_routes_own_edition_fields(fake_table):
    whole = ed.body_of(obs.handle_nutrition_overview())
    assert whole is not None
    # The fixture exercises the facts: 7 visible in-window rows (the tombstone and the 40-day
    # row are not), a protein-floor hit count, and both macro field spellings.
    assert whole["nutrition"]["days_logged"] == 7 and whole["nutrition"]["latest_date"] == _day(1), whole["nutrition"]
    assert whole["nutrition"]["protein_floor_hit_days"] > 0

    del fake_table[:]
    narrow = obs.edition_nutrition()
    assert set(narrow) == set(ed.NARROW_JOBS["nutrition"])
    assert fake_table == [(f"{_PREFIX}macrofactor", ("sk", "tombstone", *nutrition_mod._EDITION_MF_FIELDS))], fake_table
    assert json.dumps(json.loads(json.dumps(narrow["nutrition"])), sort_keys=True) == json.dumps(
        _edition_nutrition_subset(whole), sort_keys=True
    )

    # The edition's own blocks, composed from either body, are byte-identical.
    assert json.dumps(_compose_with("nutrition", narrow["nutrition"])) == json.dumps(_compose_with("nutrition", whole))
    week_food = _compose_with("nutrition", narrow["nutrition"])["blocks"]["week"]["data"]["measures"]["food"]
    assert week_food["state"] == "ok", "the fixture does not reach the week's food measure"


def test_MUST_FAIL_a_nutrition_projection_one_field_too_narrow_is_caught(fake_table, monkeypatch):
    whole = json.dumps(_edition_nutrition_subset(ed.body_of(obs.handle_nutrition_overview())), sort_keys=True)
    fields = nutrition_mod._EDITION_MF_FIELDS
    # Every macro spelling `_mf` resolves. (`date` is carried for the day; a row without it is
    # read by its `sk`, which is always projected — so the fixture cannot tell them apart.)
    for dropped in [f for f in fields if f != "date"]:
        monkeypatch.setattr(nutrition_mod, "_EDITION_MF_FIELDS", tuple(f for f in fields if f != dropped))
        narrow = json.dumps(obs.edition_nutrition()["nutrition"], sort_keys=True)
        assert narrow != whole, f"dropping {dropped!r} from the projection went unnoticed"
    monkeypatch.setattr(nutrition_mod, "_EDITION_MF_FIELDS", fields)
    assert json.dumps(obs.edition_nutrition()["nutrition"], sort_keys=True) == whole


# ── training ─────────────────────────────────────────────────────────────────────


def test_the_narrow_training_reader_serves_the_routes_own_modality_minutes(fake_table):
    whole = ed.body_of(obs.handle_training_overview())
    assert whole is not None
    rows = {r["date"]: r for r in whole["daily_modality_minutes_30d"]}
    # The fixture exercises the rules: the WHOOP walk duplicate is dropped (45 min, not 89),
    # the WHOOP-only lift is kept, a row with no activity list counts as one ride, the
    # tombstoned yoga day is gone, and Apple Health breathwork lands on its day.
    assert rows[_day(6)]["walking_min"] == 45 and rows[_day(6)]["strength_min"] == 52 and rows[_day(6)]["breathwork_min"] == 13
    assert rows[_day(4)]["cycling_min"] == 41 and rows[_day(2)]["total_min"] == 0 and rows[_day(0)]["breathwork_min"] == 5

    del fake_table[:]
    narrow = obs.edition_training()
    assert set(narrow) == set(ed.NARROW_JOBS["training"])
    assert sorted(fake_table) == sorted(
        [
            (f"{_PREFIX}strava", ("sk", "tombstone", *training_mod._EDITION_STRAVA_FIELDS)),
            (f"{_PREFIX}apple_health", ("sk", "tombstone", *training_mod._EDITION_AH_FIELDS)),
        ]
    ), fake_table
    assert json.dumps(narrow["training"]["daily_modality_minutes_30d"]) == json.dumps(whole["daily_modality_minutes_30d"])
    assert json.dumps(_compose_with("training", narrow["training"])) == json.dumps(_compose_with("training", whole))
    week_training = _compose_with("training", narrow["training"])["blocks"]["week"]["data"]["measures"]["training"]
    assert week_training["state"] == "ok", "the fixture does not reach the week's training measure"


def test_MUST_FAIL_a_training_projection_one_field_too_narrow_is_caught(fake_table, monkeypatch):
    whole = ed.body_of(obs.handle_training_overview())["daily_modality_minutes_30d"]
    # The fields the fixture's rows carry and the minutes depend on. (`type`, `device_name`,
    # `activities_deduped` and `moving_time_seconds` at day level are carried for row shapes this
    # fixture does not hold; `date` falls back to the always-projected `sk`.)
    for attr, field in (
        ("_EDITION_STRAVA_FIELDS", "activities"),
        ("_EDITION_STRAVA_FIELDS", "sport_type"),
        ("_EDITION_STRAVA_FIELDS", "moving_time_minutes"),
        ("_EDITION_AH_FIELDS", "breathwork_minutes"),
    ):
        fields = getattr(training_mod, attr)
        monkeypatch.setattr(training_mod, attr, tuple(f for f in fields if f != field))
        narrow = obs.edition_training()["training"]["daily_modality_minutes_30d"]
        assert json.dumps(narrow) != json.dumps(whole), f"dropping {attr}.{field} went unnoticed"
        monkeypatch.setattr(training_mod, attr, fields)


# ── the wiring ───────────────────────────────────────────────────────────────────


def test_the_edition_reads_nutrition_and_training_through_their_narrow_readers():
    with open(os.path.join(_REPO, "lambdas", "web", "site_api_edition.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '"nutrition": site_api_observatory.edition_nutrition' in src
    assert '"training": site_api_observatory.edition_training' in src
    assert ed.NARROW_JOBS["nutrition"] == ("nutrition",) and ed.NARROW_JOBS["training"] == ("training",)

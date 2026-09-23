"""tests/test_shared_quantities_4068.py — one definition of weekly walking hours and of the loss rate (#4068).

THE TWO LIVE PAIRS, DECODED (fixtures are the wire: field-projected copies of the live
`USER#matthew#SOURCE#{strava,hevy,withings}` rows, read 2026-09-22)

  walking 12.82 vs 15.82 — the SAME layer over two windows: 09-17..09-23 (the plan's target
          day and a half-lived 09-22 inside the "week") vs 09-15..09-21 (seven completed
          days). Both also counted 5.75 h twice: WHOOP-detected walks recorded inside Hevy
          treadmill sessions. The de-duplicated week 09-15..09-21 is 10.07 h.
  loss    4.52 vs 2.99 — get_benchmark's 28-day cross-phase least-squares slope (pre-genesis
          weigh-ins + both water weeks) vs the nutrition resolver's 14-day first-vs-last
          endpoint ending 09-21 (inside water weeks 1-2). Per v0.3 §1 neither was the rate:
          on 09-22 the post-water window holds two weigh-ins over one day — provisional.

THE DERIVATION GUARD (AST) names every critic/tool call site that reports either quantity and
asserts it reaches `mcp.shared_quantities`; and it asserts no other module builds the walking
layer or computes an endpoint weight trend outside the ruled TDEE back-solve sites.

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import ast
import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics  # noqa: E402
from health import tdee  # noqa: E402
from training import walking_volume as wv  # noqa: E402

from mcp import (
    nutrition_critics_inputs as nci,  # noqa: E402
    shared_quantities as sq,  # noqa: E402
    tools_benchmark as tb,  # noqa: E402
    tools_plan as tp,  # noqa: E402
)

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "shared_quantities_4068"
TODAY = "2026-09-22"  # the evening the owner read both pairs


@pytest.fixture(autouse=True)
def _frozen_pacific_clock(monkeypatch):
    """Every test reads the shared window as of the evening the owner read both pairs.
    `completed_end` reads the handler's own clock; unfrozen, the dated fixtures below would
    drift out of the window on a later day (#2376)."""
    monkeypatch.setattr(sq, "pacific_today", lambda: TODAY)


def _load(name: str) -> list[dict]:
    return json.loads((FIX / name).read_text())


STRAVA = _load("strava_2026-09-08_22.json")
HEVY = _load("hevy_2026-09-08_22.json")
WITHINGS = _load("withings_2026-08-16_09-22.json")


def _day(r: dict) -> str:
    return str(r.get("date") or r["sk"][5:15])[:10]


def _between(rows, a, b):
    return [r for r in rows if a <= _day(r) <= b]


def _reader(source, start, end, **_kw):
    rows = {"strava": STRAVA, "hevy": HEVY, "withings": WITHINGS}.get(source, [])
    return _between(rows, start, end)


def _untimed(items):
    """The v1.0 layer never read a timestamp — strip them to replay what it computed."""
    out = []
    for it in items:
        it = json.loads(json.dumps(it))
        for a in it.get("activities") or []:
            a.pop("start_date", None)
        it.pop("start_time", None)
        it.pop("end_time", None)
        out.append(it)
    return out


def _shift(d, n):
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


# ── decode: walking ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("start,end,expected", [("2026-09-17", "2026-09-23", 12.82), ("2026-09-15", "2026-09-21", 15.82)])
def test_both_live_walking_figures_replay_exactly_without_the_de_dup(start, end, expected):
    """The two numbers the owner read, reproduced from the wire: one layer, two windows,
    no de-dup. Proves the disagreement was the WINDOW (and both were inflated), not a sum."""
    layer = wv.build(
        window_start=start,
        window_end=end,
        strava_items=_untimed(_between(STRAVA, start, end)),
        hevy_workouts=_untimed(_between(HEVY, start, end)),
    )
    assert layer["total_hr"] == expected
    assert layer["dedup"]["untimed"] > 0 and any("no start timestamp" in h for h in layer["honesty"])


def test_whoop_walks_inside_hevy_treadmill_sessions_are_counted_once():
    """Mutation control: return `[]` from `hevy_cardio_intervals` — the five WHOOP walks
    count again and the week reads 15.82."""
    layer = wv.build(
        window_start="2026-09-15",
        window_end="2026-09-21",
        strava_items=_between(STRAVA, "2026-09-15", "2026-09-21"),
        hevy_workouts=_between(HEVY, "2026-09-15", "2026-09-21"),
    )
    assert layer["dedup"]["hours_removed"] == 5.75
    assert {r["device"] for r in layer["dedup"]["removed"]} == {"WHOOP"}
    assert layer["by_source"]["hevy"]["hours"] == 9.83
    assert layer["by_source"]["strava"]["hours"] == 0.24  # the one Garmin evening walk outside every session
    assert layer["total_hr"] == 10.07
    assert layer["dedup"]["untimed"] == 0


def test_two_devices_recording_one_walk_count_once_and_a_separate_walk_still_counts():
    """Garmin and WHOOP both push the same outdoor walk to Strava. Mutation control: skip
    `claimed.append(...)` for Strava activities — the pair counts twice (2.0 h)."""
    items = [
        {
            "date": "2026-10-01",
            "activities": [
                {
                    "type": "Walk",
                    "device_name": "Garmin epix (Gen2)",
                    "start_date": "2026-10-01T17:00:00Z",
                    "moving_time_seconds": 3600,
                    "elapsed_time_seconds": 3600,
                },
                {
                    "type": "Walk",
                    "device_name": "WHOOP",
                    "start_date": "2026-10-01T17:02:00Z",
                    "moving_time_seconds": 3480,
                    "elapsed_time_seconds": 3480,
                },
                {
                    "type": "Walk",
                    "device_name": "WHOOP",
                    "start_date": "2026-10-01T23:00:00Z",
                    "moving_time_seconds": 1800,
                    "elapsed_time_seconds": 1800,
                },
            ],
        }
    ]
    layer = wv.build(window_start="2026-10-01", window_end="2026-10-01", strava_items=items, hevy_workouts=[])
    assert layer["total_hr"] == 1.5
    assert layer["dedup"]["hours_removed"] == pytest.approx(0.97, abs=0.01)


def test_a_partial_overlap_keeps_only_the_unclaimed_time():
    """A walk that starts inside a Hevy cardio session and runs 30 min past its end keeps the
    30 min. Mutation control: drop the whole activity on any overlap — the half hour is lost."""
    hevy = [
        {
            "date": "2026-10-02",
            "start_time": "2026-10-02T17:00:00+00:00",
            "end_time": "2026-10-02T18:00:00+00:00",
            "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 3600}]}],
        }
    ]
    strava = [
        {
            "date": "2026-10-02",
            "activities": [
                {"type": "Walk", "start_date": "2026-10-02T17:30:00Z", "moving_time_seconds": 3600, "elapsed_time_seconds": 3600}
            ],
        }
    ]
    layer = wv.build(window_start="2026-10-02", window_end="2026-10-02", strava_items=strava, hevy_workouts=hevy)
    assert layer["by_source"]["strava"]["hours"] == 0.5 and layer["total_hr"] == 1.5


# ── the shared window: every surface reads the same week ───────────────────────────
def test_the_plan_and_the_adherence_critic_read_the_same_week_and_the_same_hours():
    """The live-proof shape, offline: on 09-22 a plan for 09-23 and the nutrition critics
    (window end = the latest complete nutrition day, 09-21) both read 09-15..09-21. Mutation
    control: make `_walking_volume_last_7d` pass `end_date` instead of the day before — the plan
    reads a different week and this reds."""
    with patch("mcp.core.query_source_range", side_effect=_reader), patch.object(sq, "pacific_today", return_value=TODAY):
        plan = tp._walking_volume_last_7d("2026-09-23")
        adherence_this = nci._walking_hours(sq.completed_end("2026-09-21"))
        plan_same_day = tp._walking_volume_last_7d(TODAY)
    assert plan["window"] == {"start": "2026-09-15", "end": "2026-09-21", "days": 7}
    assert plan["total_hr"] == adherence_this == plan_same_day["total_hr"] == 10.07


def test_get_benchmark_walking_hours_are_the_same_definition():
    """`get_benchmark`'s 7-day figure is the plan's figure; its 28-day chronic figure is the same
    definition over more days. Mutation control: restore the Strava-only loop in
    `_recent_volume` — walk_hr_wk_7d disappears and the 28-day rate falls to Strava's."""
    with patch.object(tb, "query_source", side_effect=_reader), patch.object(sq, "pacific_today", return_value=TODAY):
        now = tb._recent_volume("2026-09-23", days=14)
    assert now["walk_hr_wk_7d"] == 10.07
    assert now["walk_hr_window"] == {"start": "2026-09-08", "end": "2026-09-21", "days": 14}
    assert now["walk_hr_definition"].startswith(sq.SHARED_QUANTITIES_VERSION)


def test_completed_end_never_reads_a_day_in_progress():
    assert sq.completed_end("2026-09-23", today=TODAY) == "2026-09-21"
    assert sq.completed_end("2026-09-21", today=TODAY) == "2026-09-21"
    assert sq.completed_end("2026-09-10", today=TODAY) == "2026-09-10"


# ── decode: loss rate ───────────────────────────────────────────────────────────────
def _ols_rate(pts):
    d0 = date.fromisoformat(pts[0][0])
    xs = [(date.fromisoformat(d) - d0).days for d, _ in pts]
    ys = [w for _, w in pts]
    n = len(xs)
    xb, yb = sum(xs) / n, sum(ys) / n
    return round(-sum((x - xb) * (y - yb) for x, y in zip(xs, ys)) / sum((x - xb) ** 2 for x in xs) * 7, 2)


def test_both_live_loss_rates_replay_exactly():
    """4.52 = the old get_benchmark read (28 days, cross-phase, OLS) ending 09-22;
    2.99 = the old nutrition read (14 days, tdee endpoint) ending 09-21."""
    pts = sorted((_day(r), float(r["weight_lbs"])) for r in WITHINGS)
    old_benchmark = _ols_rate([p for p in pts if _shift("2026-09-22", -28) <= p[0] <= "2026-09-22"])
    assert old_benchmark == 4.52
    assert any(r["phase"] == "pilot" for r in _between(WITHINGS, _shift("2026-09-22", -28), "2026-09-22"))
    old_nutrition, span = tdee.weight_trend_lb_per_wk(_between(WITHINGS, _shift("2026-09-21", -13), "2026-09-21"))
    assert round(-old_nutrition, 2) == 2.99 and span == 9


def test_the_deficit_critic_and_the_rate_advocate_read_one_loss_rate():
    """On 09-22 both surfaces now carry the SAME rate, and both call it provisional: the
    post-water window (from 09-20) holds two weigh-ins one day apart. Mutation control: drop
    the water floor — both read ~3.3 and `provisional` goes False on a window v0.3 excludes."""
    with patch.object(sq, "pacific_today", return_value=TODAY):
        nutrition = nci.withings_trend(_between(WITHINGS, "2026-09-08", "2026-09-21"), nci.day_keys("2026-09-21"))["loss_rate"]
        with patch.object(tb, "query_source", side_effect=_reader):
            benchmark = tb._loss_rate_block("2026-09-23")
    for block in (nutrition, benchmark):
        assert block["window"]["start"] == "2026-09-20" and block["window"]["end"] == "2026-09-21"
        assert block["water_weeks_excluded_through"] == "2026-09-19"
        assert block["n_weighins"] == 2 and block["provisional"] is True
    assert nutrition["rate_lb_wk"] == benchmark["rate_lb_wk"]


def test_one_rate_once_the_window_clears_the_water_weeks():
    """A synthetic continuation (0.5 lb/day) read on 10-10: both surfaces agree, not provisional."""
    rows = [{"date": _shift("2026-09-20", i), "weight_lbs": 316.9 - 0.5 * i} for i in range(20)]
    with patch.object(sq, "pacific_today", return_value="2026-10-10"):
        n = nci.withings_trend(rows, nci.day_keys("2026-10-09"))
        b = tb._loss_rate_block("2026-10-11", rows)
    assert n["loss_rate"]["rate_lb_wk"] == b["rate_lb_wk"] == 3.5
    assert b["provisional"] is False and n["weight_trend_lb_wk"] == -3.5


def test_a_provisional_rate_argues_nothing_in_the_rate_advocate():
    """Mutation control: drop the `rate_provisional` branch — a provisional 7.56 lb/wk reads
    ABOVE the band and the advocate says it has nothing to add."""
    kw = dict(tripwires=[], walking=None, rate_target={"low_lb_wk": 3.0, "high_lb_wk": 4.0}, lifting_sessions_7d=2)
    p = critics.build_rate_advocate_packet({"total_sets": 20}, current_rate_lb_wk=7.56, rate_provisional=True, **kw)
    assert p["numbers"]["current_rate_lb_wk"] == 7.56 and p["numbers"]["current_rate_provisional"] is True
    assert not [f for f in p["flags"] if f["metric"] in ("current_rate_lb_wk", "current_rate_provisional")]
    firm = critics.build_rate_advocate_packet({"total_sets": 20}, current_rate_lb_wk=7.56, rate_provisional=False, **kw)
    assert [f for f in firm["flags"] if f["metric"] == "current_rate_lb_wk"]


def test_the_stage_2_rate_advocate_reads_the_reference_loss_rate_block():
    assert tp._loss_rate_of({"loss_rate": {"rate_lb_wk": 3.1, "provisional": False}, "current_rate_lb_wk": 9.9}) == (3.1, False)
    assert tp._loss_rate_of({"current_rate_lb_wk": 2.0}) == (2.0, None)
    assert tp._loss_rate_of(None) == (None, None)


# ── the derivation guard ───────────────────────────────────────────────────────────
# (file, function) -> a name the function body MUST reference. Every critic/tool call site
# that reports weekly walking hours or the loss rate, including get_benchmark (owner, #4068).
CALL_SITES = {
    ("mcp/tools_plan.py", "_walking_volume_last_7d"): "shared_quantities.walking_layer",  # plan_next_session + walking layer
    ("mcp/tools_plan.py", "_run_stage_2"): "_loss_rate_of",  # rate_advocate's loss rate
    ("mcp/nutrition_critics_inputs.py", "_walking_hours"): "shared_quantities.weekly_walking_hours",  # adherence critic
    ("mcp/nutrition_critics_inputs.py", "resolve"): "shared_quantities.completed_end",  # adherence critic's two weeks
    ("mcp/nutrition_critics_inputs.py", "withings_trend"): "shared_quantities.loss_rate_from_rows",  # deficit critic
    ("mcp/tools_benchmark.py", "_recent_volume"): "shared_quantities.walking_layer",  # get_benchmark walking hours
    ("mcp/tools_benchmark.py", "_loss_rate_block"): "shared_quantities.loss_rate_from_rows",  # get_benchmark loss rate
    ("mcp/tools_benchmark.py", "_current_weight_and_rate"): "_loss_rate_block",  # every get_benchmark view's rate
}

# Sites that compute the TDEE back-solve's endpoint trend — a DIFFERENT quantity (#3931: "could
# this intake have produced this change"), never reported as the loss rate.
RULED_TDEE_TREND = {
    "mcp/tools_nutrition.py": "get_deficit_sustainability's impossibility check",
    "mcp/tools_health.py": "the energy-budget trend check",
    "lambdas/web/site_api_nutrition.py": "the public energy-budget trend check",
    "lambdas/health/tdee.py": "the definition itself",
}


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _references(fn: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            out.add(f"{n.value.id}.{n.attr}")
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


@pytest.mark.parametrize("site,required", sorted(CALL_SITES.items()))
def test_every_named_call_site_reads_the_shared_definition(site, required):
    """Mutation control: point any one site back at its old private derivation."""
    path, fn = site
    funcs = _functions(ROOT / path)
    assert fn in funcs, f"{path}::{fn} is gone — re-point the guard at its successor, never delete the row"
    assert required in _references(funcs[fn]), f"{path}::{fn} no longer reads {required}"


def _py_files():
    for base in ("mcp", "lambdas"):
        yield from sorted((ROOT / base).rglob("*.py"))


def test_only_the_shared_module_builds_the_walking_layer():
    """Mutation control: call `walking_volume.build` from any tool — this reds, naming it."""
    offenders = []
    for path in _py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ("mcp/shared_quantities.py", "lambdas/training/walking_volume.py"):
            continue
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "build":
                if isinstance(n.func.value, ast.Name) and n.func.value.id in ("walking_volume", "wv"):
                    offenders.append(f"{rel}:{n.lineno}")
    assert offenders == []


def test_the_endpoint_weight_trend_is_only_the_tdee_back_solve():
    """Mutation control: have a critic input read `weight_trend_lb_per_wk` again — this reds."""
    offenders = []
    for path in _py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in RULED_TDEE_TREND:
            continue
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "weight_trend_lb_per_wk":
                offenders.append(f"{rel}:{n.lineno}")
    assert offenders == []


def test_the_ruled_sites_still_exist():
    for rel in RULED_TDEE_TREND:
        assert "weight_trend_lb_per_wk" in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} no longer needs its ruling — delete it"

"""tests/nutrition_consistency_6195_surfaces.py — every surface the #6195 switchboard touches, rendered from synthetic
fixtures (no AWS, no live clock), as ONE JSON-able dict.

Two uses, one code path:
  * ``tests/test_nutrition_consistency_6195.py`` renders it with every switch OFF and compares the result to
    ``tests/fixtures/nutrition_consistency_6195/off_golden.json`` — the SAME function run against the tree before the
    switchboard existed (origin/main at the lane's base). OFF equal to that golden is the byte-for-byte proof that the
    shipped default changes nothing.
  * It renders again with switches ON, and the test asserts the ON properties and that no target value moved.

The fixtures are synthetic: round numbers chosen to exercise each branch (a refused deficit, a partial export, a
maintenance estimate dated inside the window). None is a real intake figure.

A module that does not exist on the old tree (``common.nutrition_consistency``) is treated as "every switch OFF", and a
helper the switchboard added is rendered through the expression it replaced, so the old tree renders the old output.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

for _k, _v in {
    "TABLE_NAME": "life-platform",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "S3_BUCKET": "test-bucket",
    "USER_ID": "matthew",
    "EMAIL_RECIPIENT": "owner@example.invalid",
    "EMAIL_SENDER": "platform@example.invalid",
    "AI_VALIDATOR_AUTOLOAD": "off",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
}.items():
    os.environ.setdefault(_k, _v)

FROZEN_NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)  # 10:40 PT, Sunday 2026-05-10
TODAY = "2026-05-10"
GENESIS = "2026-01-01"

# ── synthetic calorie layers (the resolver's shape; the values are the public charter's, not a private figure) ──────
REST_KCAL, LIFT_KCAL, BASE_KCAL = 1600, 1900, 1500


def fake_resolve(day=None, *, titration_reader=None, charter_reader=None, day_type=None, week_day_types=None):
    kcal = LIFT_KCAL if day_type == "lifting" else REST_KCAL
    return {
        "kcal": kcal,
        "band_low": REST_KCAL,
        "band_high": LIFT_KCAL,
        "floor_any_day_kcal": REST_KCAL,
        "floor_lifting_day_kcal": LIFT_KCAL,
        "source": "charter",
        "provenance": "synthetic",
        "charter_version": None,
        "week": None,
        "base_kcal": BASE_KCAL,
        "day_type": day_type or "unknown",
    }


def fake_charter(path):
    return {
        "governing_goal.rate_band_lb_per_wk": {"floor": 3.0, "ceiling": 3.5},
        "nutrition.training_day.lifting_uplift_kcal": 300,
    }.get(path)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


def _day(offset: int) -> str:
    return (datetime(2026, 5, 10) - timedelta(days=offset)).strftime("%Y-%m-%d")


def _rows(source: str, days: list[str], **fields) -> list[dict]:
    return [{"pk": f"USER#matthew#SOURCE#{source}", "sk": f"DATE#{d}", "date": d, **fields} for d in days]


def macrofactor_rows() -> list[dict]:
    """13 complete days at 1,000 kcal / 150 g protein (one carries a dated adaptive expenditure), plus a partial export."""
    days = [_day(i) for i in range(13, 0, -1)]  # 04-27 .. 05-09
    rows = []
    for d in days:
        r = {
            "pk": "USER#matthew#SOURCE#macrofactor",
            "sk": f"DATE#{d}",
            "date": d,
            "total_calories_kcal": 1000,
            "total_protein_g": 150,
            "total_fat_g": 40,
            "total_carbs_g": 80,
            "entries_count": 6,
            "food_log": [{"time": "08:00"}, {"time": "18:00"}],
        }
        if d == _day(9):  # 05-01: the last row carrying MacroFactor's adaptive expenditure
            r["expenditure_kcal"] = 3000
        rows.append(r)
    rows.append(
        {
            "pk": "USER#matthew#SOURCE#macrofactor",
            "sk": f"DATE#{TODAY}",
            "date": TODAY,
            "total_calories_kcal": 80,
            "total_protein_g": 10,
            "total_fat_g": 0,
            "total_carbs_g": 4,
            "entries_count": 1,
            "partial_at_export": True,
            "food_log": [{"time": "07:30"}],
        }
    )
    return rows


class FakeSources:
    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}

    def __call__(self, source, start, end, include_pilot=False, projection=None):
        if start > end:
            return []
        return [dict(r) for r in self.data.get(source, []) if start <= (r.get("date") or r["sk"][5:]) <= end]


def _flat_sources() -> FakeSources:
    wdays = [_day(i) for i in range(6, 0, -1)]
    return FakeSources(
        macrofactor=macrofactor_rows(),
        whoop=_rows("whoop", wdays, hrv=60, sleep_efficiency_pct=90, recovery_score=60),
        habitify=_rows("habitify", wdays, completion_pct=0.8),
    )


def _on(items: set[str]):
    """Context: the switchboard with exactly ``items`` on (absent on the old tree: OFF by construction)."""
    try:
        nc = importlib.import_module("common.nutrition_consistency")
    except ImportError:
        if items:
            raise
        return contextlib.nullcontext()
    return mock.patch.dict(nc.SWITCHES, {k: (k in items) for k in nc.SWITCHES})


def _strip_meta(body: dict) -> dict:
    body = dict(body)
    body.pop("_meta", None)
    return body


# ── surfaces ────────────────────────────────────────────────────────────────────────────────────────────────────────
def site_api() -> dict:
    from web import site_api_common as sac, site_api_nutrition as nut

    out = {}
    with (
        mock.patch.object(nut, "datetime", _FrozenDatetime),
        mock.patch.object(sac, "datetime", _FrozenDatetime),
        mock.patch.object(sac, "EXPERIMENT_START", GENESIS),
        mock.patch.object(nut, "_get_profile", lambda: {"height_inches": 72}),
    ):
        g = {"_query_source": _flat_sources(), "_experiment_date": sac._experiment_date, "EXPERIMENT_START": GENESIS}
        out["deficit_sustainability"] = _strip_meta(json.loads(nut.deficit_sustainability(_g=g)["body"]))
        g = {"_query_source": _flat_sources(), "_experiment_date": sac._experiment_date, "EXPERIMENT_START": GENESIS}
        ov = _strip_meta(json.loads(nut.nutrition_overview(_g=g)["body"]))
        out["nutrition_overview.nutrition"] = ov.get("nutrition")
        out["nutrition_overview.loss_rate"] = ov.get("loss_rate")
    return out


def mcp_tool() -> dict:
    from mcp import tools_descriptions, tools_nutrition as tn

    mf = macrofactor_rows()
    wdays = [_day(i) for i in range(6, 0, -1)]
    others = {
        "whoop": _rows("whoop", wdays, hrv=60, sleep_efficiency_pct=90, recovery_score=60),
        "habitify": _rows("habitify", wdays, completion_pct=0.8),
        "strava": [],
        "hevy": [],
    }
    with (
        mock.patch.object(tn, "query_source_cross_phase", lambda s, a, b: [dict(r) for r in mf if a <= r["date"] <= b]),
        mock.patch.object(tn, "parallel_query_sources_cross_phase", lambda srcs, a, b: {s: others.get(s, []) for s in srcs}),
        mock.patch.object(tn, "get_profile", lambda: {"tdee_estimate": 3000}),
        mock.patch.object(tn, "_nutrition_critics_block", lambda *a, **k: {"critics": {"veto": True}, "decisions_offered": []}),
    ):
        res = tn.tool_get_deficit_sustainability({"start_date": _day(13), "end_date": TODAY})
    desc = importlib.reload(tools_descriptions).GET_DEFICIT_SUSTAINABILITY_DESCRIPTION
    return {"deficit_tool": json.loads(json.dumps(res, default=str)), "description": desc}


def critics() -> dict:
    from health import nutrition_critics as ncr

    energy = {"base_kcal": BASE_KCAL, "step_kcal": 150, "floor_any_day": REST_KCAL, "floor_lifting_day": LIFT_KCAL}
    with mock.patch.object(ncr, "charter_value", fake_charter):
        return {"overshoot_to_text": ncr._overshoot_to_text(energy)}


def brief() -> dict:
    from ai import ai_calls
    from content import html_builder
    from health import calorie_target

    data = {"date": "2026-05-11", "latest_weight": 280}
    profile = {
        "active_goals": ["lose weight"],
        "weight_loss_phases": [{"phase": 1, "name": "Ignition", "weekly_target_lbs": 3, "deficit_target_kcal": 1500, "end_lbs": 250}],
    }
    with (
        mock.patch.object(calorie_target, "resolve", fake_resolve),
        mock.patch.object(calorie_target, "_default_charter_reader", fake_charter),
    ):
        system = ai_calls.daily_brief_shared_system(data, profile)
        line = next((ln for ln in system.split("\n") if ln.startswith("- Calorie target:")), None)
        bod = ai_calls._bod_phase_targets(data, profile)
        if hasattr(html_builder, "_cal_tile_label"):
            tile = html_builder._cal_tile_label(data["date"], html_builder.target_kcal(data["date"]))
        else:  # the old tree: the tile's own expression
            cal_target = html_builder.target_kcal(data["date"])
            tile = "/" + str(cal_target or "—")
    return {"profile_calorie_line": line, "bod_phase_targets": bod, "tile_calorie_label": tile}


def emails() -> dict:
    from emails import nutrition_review_lambda as nr, weekly_plate_lambda as wp
    from health import calorie_target

    with (
        mock.patch.object(calorie_target, "resolve", fake_resolve),
        mock.patch.object(calorie_target, "_default_charter_reader", fake_charter),
    ):
        cal = calorie_target.target_kcal() or "—"
        if hasattr(nr, "_fallback_system_prompt"):
            fb = nr._fallback_system_prompt(cal, 170)
        else:
            fb = nr._FALLBACK_SYSTEM_PROMPT.format(
                calorie_target=cal,
                protein_target_g=170,
                feeding_threshold_g=nr._feeding_threshold_text(),
                eating_window=nr.eating_window.published_text(),
            )
        plate = wp.build_system_prompt({}, {})
    return {
        "nutrition_review_fallback_calorie_line": next(ln for ln in fb.split("\n") if "Weekly calorie avg" in ln),
        "weekly_plate_targets_line": next(ln for ln in plate.split("\n") if ln.startswith("Targets:")),
    }


def day_pages() -> dict:
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import inspect

    import publish_snapshot_day as pd

    dated = "tdee_as_of" in inspect.signature(pd.food_of).parameters
    out = {}
    for label, row in (
        ("before_as_of", {"date": "2026-04-28", "calories": 1000, "protein_g": 150, "carbs_g": 80, "fat_g": 40, "partial_export": False}),
        ("after_as_of", {"date": "2026-05-05", "calories": 1000, "protein_g": 150, "carbs_g": 80, "fat_g": 40, "partial_export": False}),
        ("partial", {"date": TODAY, "calories": 80, "protein_g": 10, "carbs_g": 4, "fat_g": 0, "partial_export": True}),
    ):
        kw = {"logging_gap": False, "floor_g": 170, "tdee": 3000}
        if dated:
            kw["tdee_as_of"] = "2026-05-01"
        out[label] = pd.food_of(row, **kw)
    return out


def render(items: set[str] | frozenset = frozenset()) -> dict:
    """Every surface, with exactly ``items`` switched on."""
    lambdas = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
    root = os.path.dirname(lambdas)
    for p in (lambdas, root):
        if p not in sys.path:
            sys.path.insert(0, p)
    with _on(set(items)):
        out: dict[str, Any] = {}
        for name, fn in (
            ("site_api", site_api),
            ("mcp", mcp_tool),
            ("critics", critics),
            ("brief", brief),
            ("emails", emails),
            ("day_pages", day_pages),
        ):
            out[name] = fn()
    if "mcp.tools_descriptions" in sys.modules:  # the description is built at import: rebuild it under the restored switches
        importlib.reload(sys.modules["mcp.tools_descriptions"])
    return json.loads(json.dumps(out, default=str, sort_keys=True))


if __name__ == "__main__":  # the golden generator: `python3 <tree>/tests/nutrition_consistency_6195_surfaces.py`
    print(json.dumps(render(), indent=1, sort_keys=True, ensure_ascii=False))

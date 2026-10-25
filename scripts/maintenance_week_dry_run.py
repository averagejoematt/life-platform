#!/usr/bin/env python3
"""scripts/maintenance_week_dry_run.py — the maintenance-week + reverse-diet sequence on a fixture (#5107).

No AWS, no clock: the live charter's rules (``config/training_charter.json``) with ONE fixture change —
the late-December window gets dates (``--start`` / ``--end``; the live charter's are null, so the live
engine is inert) — run through the real weekly decision (``health.titration.decide``) and the real
resolver (``health.calorie_target.resolve``) over a synthetic run of weeks:

  * the weeks around the window: the hold with the maintenance dates, the resolver's per-date kcal, the
    trend-window hold after it, and the window's grade from fixture weigh-ins;
  * the reverse diet from ``nutrition.reverse_diet.starts_on``: a step up each week until the trend settles.

    python3 scripts/maintenance_week_dry_run.py [--start 2026-12-24 --end 2026-12-31] [--json]

Every number printed comes from the charter or the fixture below; the fixture's trends, weights and the
maintenance estimate are made up for the demonstration and say so.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_REPO, "lambdas"), _REPO]

from health import (
    calorie_target as ct,  # noqa: E402
    maintenance_week as mw,  # noqa: E402
    titration as ti,  # noqa: E402
)
from training import training_charter as tc  # noqa: E402

from mcp import titration_leg as tl  # noqa: E402

FIXTURE_ESTIMATE_KCAL = 2900  # fixture: the best-matching model's maintenance estimate (made up)
BAND = {"floor_lb_wk": 3.0, "ceiling_lb_wk": 3.5, "source": "fixture band", "guidance_capped": False}


def _reader(start: str, end: str):
    def read(path: str):
        v = tc.charter_value(path)
        if path == mw.TRAVEL_PATH and isinstance(v, list):
            return [{**w, "start": start, "end": end} if w.get("label") == "late December 2026" else w for w in v]
        return v

    return read


def _mondays(first: str, n: int) -> list:
    d = date.fromisoformat(first)
    d -= timedelta(days=d.weekday())
    return [(d + timedelta(days=7 * i)).isoformat() for i in range(n)]


def _recon() -> dict:
    return {
        "best_match": "platform_measured",
        "best_match_actionable": True,
        "models": {"platform_measured": {"kcal": FIXTURE_ESTIMATE_KCAL}},
    }


def run(start: str, end: str, trends: dict) -> dict:
    cfg = ti.settings(_reader(start, end))
    history: list = []
    weeks = []
    for week, trend in trends.items():
        tw_end = (date.fromisoformat(week) - timedelta(days=4)).isoformat()  # the Friday-before run reads through Thursday
        tw = {"start": (date.fromisoformat(tw_end) - timedelta(days=13)).isoformat(), "end": tw_end}
        run_day = (date.fromisoformat(week) - timedelta(days=3)).isoformat()
        win = mw.dated(cfg["maintenance"])
        weigh = [(start, 268.4), ((date.fromisoformat(end) + timedelta(days=1)).isoformat(), 269.9)]  # fixture weigh-ins
        weigh = [p for p in weigh if p[0] < run_day]  # the leg reads completed days only
        horizon = [
            w for w in win if w["end"] < run_day <= (date.fromisoformat(w["end"]) + timedelta(days=tl.GRADE_HORIZON_DAYS)).isoformat()
        ]
        grades = [g for w in horizon if (g := mw.grade(w, weigh, run_day, cfg["maintenance"]))]
        d = ti.decide(
            week=week,
            trend_lb_wk=trend,
            trend_provisional=False,
            weight_lb=268.0,
            band=BAND,
            steps_avg=12500,
            complete_log_days=7,
            complete_days_trailing=14,
            history=list(history),
            experiment_day=120,
            cfg=cfg,
            maintenance={"estimate": mw.estimate(_recon()), "trend_window": tw, "grades": grades},
        )
        history.append(d)
        days = []
        for i in range(7):
            day = (date.fromisoformat(week) + timedelta(days=i)).isoformat()
            r = ct.resolve(day, titration_reader=lambda wk, d=d: d if wk == d["week"] else None)
            days.append({"date": day, "kcal": r["kcal"], "maintenance": bool(r.get("maintenance_day"))})
        weeks.append({"week": week, "trend_lb_wk": trend, "decision": d, "days": days})
    return {"window": {"start": start, "end": end}, "weeks": weeks}


def _print(out: dict) -> None:
    print(f"fixture window {out['window']['start']}..{out['window']['end']}; maintenance estimate {FIXTURE_ESTIMATE_KCAL} (fixture)")
    for w in out["weeks"]:
        d = w["decision"]
        maint = [x["date"][5:] for x in w["days"] if x["maintenance"]]
        line = f"{w['week']}  trend {w['trend_lb_wk']:+.2f}  {d['action']:<4} {d['kcal']:>5}  {d['reason_code']}"
        if maint:
            line += f"  maintenance {FIXTURE_ESTIMATE_KCAL} on {', '.join(maint)}"
        for g in d.get("maintenance_grades") or []:
            line += f"  GRADE {g['state']} ({g['reason']})"
        print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default="2026-12-24")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    starts_on = tc.charter_value("nutrition.reverse_diet.starts_on")
    trends = dict(zip(_mondays("2026-12-14", 6), [3.2, 3.3, 3.1, 2.4, 2.6, 3.2]))
    trends.update(zip(_mondays(starts_on, 6), [2.6, 2.1, 1.4, 0.9, 0.4, -0.2]))
    out = run(a.start, a.end, trends)
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        _print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

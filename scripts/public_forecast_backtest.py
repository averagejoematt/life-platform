#!/usr/bin/env python3
"""scripts/public_forecast_backtest.py — the rules-based platform forecast, walked forward over this experiment cycle (#6156).

WHY (owner ruling 2026-11-22 §5, "Scoring"): the ±1 SD tolerance a coach's number call is graded with (about ±4.5 lb for
weight) needed a justification before the forecast stream may go live. This script answers four questions from the
public record only:

  * how close is the rule, and how close is a guess that nothing changes (mean absolute error of each);
  * how often each is "confirmed" under that ±1 SD tolerance;
  * how often the tolerance cannot tell them apart at all (both confirmed, or both refuted);
  * how often the rule lands closer than the guess — the partition's frozen head-to-head rule
    (``common.public_forecast_policy.SCORING_RULE``).

HOW. For every weekly filing day (a Monday, the producer's run day) from ``--start`` to the last day whose target has a
reading: the served series is CUT at the day before filing (``cut_before`` — nothing on or after the filing day exists in
what the rule is handed, so no future reading can leak in; ``tests/test_public_forecast_backtest_6156.py`` proves it by
changing every later reading and getting the same forecast), and the producer's own ``public_forecast.build`` files the
forecast exactly as the live run would. The outcome is the reading the grader would read: the target day's, else the
latest within ``POINT_GRACE_DAYS`` before it and after the filing day (``prediction_point_grader.metric_value_on``'s rule).

WHAT IT READS. ``GET https://averagejoematt.com/api/series`` — the public route any reader can call — once per metric.
No credentials, no AWS client, no write. Inputs are clamped to this experiment cycle (on or after
``EXPERIMENT_START_DATE``), so the first filing days use fewer than 30 days of history.

    python3 scripts/public_forecast_backtest.py              # every rule, this cycle to date
    python3 scripts/public_forecast_backtest.py --json       # the same, machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import public_forecast as F  # noqa: E402
from coach.prediction_point_grader import POINT_GRACE_DAYS, forecast_closer  # noqa: E402
from common import public_brief_policy as BPOL  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402

FILING_WEEKDAY = 0  # Monday: the producer rides public_brief's Monday run


def _d(s: str, delta: int = 0) -> str:
    return (datetime.strptime(s[:10], "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def cut_before(payload: dict, day: str, start: str) -> dict:
    """The served payload with every day ON OR AFTER ``day`` (and before ``start``) removed — what the rule may see."""
    days = [d for d in (payload or {}).get("days") or [] if start <= str((d or {}).get("date") or "")[:10] < day]
    return {**(payload or {}), "days": days, "as_of": _d(day, -1)}


def outcome(readings: list, target: str, filed: str) -> tuple:
    """``(value, day)`` the grader would read for ``target``: that day's reading, else the latest within POINT_GRACE_DAYS
    before it, never one on or before the filing day. ``(None, None)`` when there is none."""
    floor = max(_d(target, -POINT_GRACE_DAYS), _d(filed, 1))
    hits = [(d, v) for d, v in readings if floor <= d <= target]
    return (hits[-1][1], hits[-1][0]) if hits else (None, None)


def filing_days(start: str, last_target: str) -> list:
    """Every Monday from ``start`` whose target day (filing + HORIZON_DAYS) is on or before ``last_target``."""
    d = datetime.strptime(start, "%Y-%m-%d")
    d += timedelta(days=(FILING_WEEKDAY - d.weekday()) % 7)
    out = []
    while (d + timedelta(days=F.HORIZON_DAYS)).strftime("%Y-%m-%d") <= last_target:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=7)
    return out


def walk(rule_id: str, payload: dict, start: str, genesis: str = EXPERIMENT_START_DATE, url: str = "backtest") -> list:
    """One entry per filing day: the forecast the producer would have filed, the guess, the band and the outcome."""
    all_readings = F.readings_of(payload, genesis, "9999-12-31")
    if not all_readings:
        return []
    weeks = []
    for day in filing_days(start, all_readings[-1][0]):
        seen = cut_before(payload, day, genesis)
        row, why = F.build(rule_id, day, seen, url, BPOL.cycle_of(day), phase_stamp=False)
        entry: dict = {"filed": day, "rule": rule_id}
        if row is None:
            weeks.append({**entry, "held": why})
            continue
        spec = row["evaluation"]
        band = F.sd_band([tuple(x) for x in row["lineage"]["readings"]], day)
        actual, on = outcome(all_readings, spec["target_date"], day)
        entry.update(
            target=spec["target_date"],
            forecast=float(spec["threshold"]),
            guess=float(spec["baseline_value"]),
            band=float(band[0]) if band else None,
            actual=actual,
            actual_on=on,
            inputs_last=row["lineage"]["readings"][-1][0],
        )
        weeks.append(entry)
    return weeks


def summarise(weeks: list) -> dict:
    graded = [w for w in weeks if w.get("actual") is not None and w.get("band") is not None]
    held = [w for w in weeks if w.get("held")]
    n = len(graded)
    out: dict = {"filing_days": len(weeks), "held": len(held), "no_reading": len(weeks) - len(held) - n, "n": n}
    if not n:
        return out
    err_f = [abs(w["actual"] - w["forecast"]) for w in graded]
    err_g = [abs(w["actual"] - w["guess"]) for w in graded]
    in_f = [e <= w["band"] for e, w in zip(err_f, graded)]
    in_g = [e <= w["band"] for e, w in zip(err_g, graded)]
    both_in = sum(a and b for a, b in zip(in_f, in_g))
    both_out = sum((not a) and (not b) for a, b in zip(in_f, in_g))
    closer = sum(forecast_closer(w["actual"], w["forecast"], w["guess"]) for w in graded)
    out.update(
        mae_rule=round(sum(err_f) / n, 3),
        mae_no_change=round(sum(err_g) / n, 3),
        mean_band=round(sum(w["band"] for w in graded) / n, 3),
        mean_abs_week_change=round(sum(abs(w["actual"] - w["guess"]) for w in graded) / n, 3),
        sd_confirmed_rule=sum(in_f),
        sd_confirmed_no_change=sum(in_g),
        sd_both_confirmed=both_in,
        sd_both_refuted=both_out,
        sd_not_distinguished=both_in + both_out,
        h2h_rule_closer=closer,
        h2h_no_change_as_close_or_closer=n - closer,
    )
    return out


def _pct(k: int, n: int) -> str:
    """A count out of n — never a percentage: every n here is below the platform's rate floor (ADR-104, 20 calls)."""
    return f"{k} of {n}"


def render(results: dict, period: tuple) -> str:
    lines = [f"Rules-based platform forecast — walk-forward backtest, filing Mondays {period[0]} .. {period[1]} (public /api/series only)"]
    for rule_id, r in results.items():
        s, n = r["summary"], r["summary"]["n"]
        lines.append("")
        lines.append(
            f"{rule_id} ({F.RULES[rule_id]['metric']}): {s['filing_days']} filing days, {s['held']} held, {s['no_reading']} without a reading, n={n} graded"
        )
        if not n:
            continue
        lines += [
            f"  mean absolute error      rule {s['mae_rule']:g} · no-change guess {s['mae_no_change']:g}",
            f"  mean ±1 SD band          ±{s['mean_band']:g} (mean |actual − last reading| {s['mean_abs_week_change']:g})",
            f"  ±1 SD: rule confirmed    {_pct(s['sd_confirmed_rule'], n)} · guess confirmed {_pct(s['sd_confirmed_no_change'], n)}",
            f"  ±1 SD: not distinguished {_pct(s['sd_not_distinguished'], n)} (both confirmed {s['sd_both_confirmed']}, both refuted {s['sd_both_refuted']})",
            f"  head-to-head (frozen)    rule closer {_pct(s['h2h_rule_closer'], n)} · guess as close or closer {_pct(s['h2h_no_change_as_close_or_closer'], n)}",
        ]
        for w in r["weeks"]:
            if w.get("held"):
                lines.append(f"    {w['filed']}  held: {w['held']}")
            elif w.get("actual") is None:
                lines.append(f"    {w['filed']}  forecast {w['forecast']:g} · guess {w['guess']:g} · no reading by {w['target']}")
            else:
                f_in = abs(w["actual"] - w["forecast"]) <= w["band"]
                g_in = abs(w["actual"] - w["guess"]) <= w["band"]
                win = "rule" if forecast_closer(w["actual"], w["forecast"], w["guess"]) else "guess"
                lines.append(
                    f"    {w['filed']}  forecast {w['forecast']:g} · guess {w['guess']:g} · actual {w['actual']:g} ({w['actual_on']}) · "
                    f"±{w['band']:.2f}: rule {'in' if f_in else 'out'}, guess {'in' if g_in else 'out'} · closer: {win}"
                )
    return "\n".join(lines)


def run(
    fetch_json: Callable = F.http_get_json,
    *,
    base: str = F.PUBLIC_BASE,
    start: Optional[str] = None,
    end: Optional[str] = None,
    rules: Optional[list] = None,
) -> dict:
    """``{rule_id: {"weeks": [...], "summary": {...}}}`` — one public GET per metric, nothing else."""
    genesis = EXPERIMENT_START_DATE
    first = start or _d(genesis, 14)  # two weeks in: the weight line's 14-day fit window lies inside the cycle
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {}
    for rule_id in rules or list(F.RULES):
        metric = F.RULES[rule_id]["metric"]
        payload = fetch_json(F.series_url(metric, genesis, end, base))
        weeks = walk(rule_id, payload, first, genesis)
        out[rule_id] = {"weeks": weeks, "summary": summarise(weeks)}
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", help="first filing day considered (default: genesis + 14 days)")
    ap.add_argument("--end", help="last day of public data read (default: today, UTC)")
    ap.add_argument("--rule", action="append", choices=sorted(F.RULES), help="one rule (repeatable); default every rule")
    ap.add_argument("--base", default=F.PUBLIC_BASE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    results = run(start=a.start, end=a.end, rules=a.rule, base=a.base)
    if a.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        days = [w["filed"] for r in results.values() for w in r["weeks"]]
        print(render(results, (min(days), max(days)) if days else ("-", "-")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

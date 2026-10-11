#!/usr/bin/env python3
"""Runs/day for every scheduled ingestion Lambda, derived — never hand-stated (#4641).

    python3 scripts/ingestion_runs_per_day.py          # table
    python3 scripts/ingestion_runs_per_day.py --json

Own runs come from the `schedule=` of each create_platform_lambda call in
cdk/stacks/ingestion_stack.py (module constants such as INGEST_HOURLY resolved by AST,
no cdk import, no AWS). Extra invocations come from lambdas/web/site_stats_refresh_lambda.py
INGESTION_LAMBDAS x the number of SiteStatsRefresh cron rules in cdk/stacks/operational_stack.py.
The registry `method` facet text is printed alongside so a cadence/prose mismatch is visible.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACK = os.path.join(ROOT, "cdk", "stacks", "ingestion_stack.py")
OPS_STACK = os.path.join(ROOT, "cdk", "stacks", "operational_stack.py")
REFRESH = os.path.join(ROOT, "lambdas", "web", "site_stats_refresh_lambda.py")


def _count_field(field: str, hi: int) -> int:
    if field in ("*", "?"):
        return hi
    if field.startswith("*/"):
        return len(range(0, hi, int(field[2:])))
    return len([p for p in field.split(",") if p])


def runs_per_day_expr(expr: str) -> int | None:
    """cron(min hour dom mon dow yr) or rate(N unit) -> runs per day (daily-or-finer only)."""
    m = re.fullmatch(r"cron\((\S+) (\S+) .*\)", expr.strip())
    if m:
        return _count_field(m.group(1), 60) * _count_field(m.group(2), 24)
    m = re.fullmatch(r"rate\((\d+) (minute|minutes|hour|hours|day|days)\)", expr.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        per = {"minute": 1440, "hour": 24, "day": 1}[unit.rstrip("s")]
        return max(1, per // n) if per >= n else 0
    return None


def _consts(tree: ast.Module) -> dict:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out[node.targets[0].id] = node.value.value
    return out


def _resolve(node: ast.AST, consts: dict) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in consts:
                parts.append(consts[v.value.id])
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        kws = {k.arg: _resolve(k.value, consts) for k in node.keywords}
        if node.func.attr == "expression" and node.args:
            return _resolve(node.args[0], consts)
        if node.func.attr == "cron":
            return f"cron({kws.get('minute') or '0'} {kws.get('hour') or '*'} * * ? *)"
    return None


def own_schedules() -> dict:
    tree = ast.parse(open(STACK, encoding="utf-8").read())
    consts = _consts(tree)
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kws = {k.arg: k.value for k in node.keywords}
        if "function_name" in kws and "schedule" in kws:
            fn = _resolve(kws["function_name"], consts)
            sched = _resolve(kws["schedule"], consts)
            if fn and sched:
                out[fn] = {"schedule": sched, "own": runs_per_day_expr(sched)}
    return out


def site_stats_extra() -> dict:
    src = open(REFRESH, encoding="utf-8").read()
    names = ast.literal_eval(re.search(r"INGESTION_LAMBDAS\s*=\s*(\[.*?\])", src, re.S).group(1))
    ops = open(OPS_STACK, encoding="utf-8").read()
    rules = int(
        len(ast.literal_eval(re.search(r"for utc_hour, label in (\[.*?\]):", ops, re.S).group(1)))
    )  # the SiteStatsRefresh cron rules
    return {n: rules for n in names}


def table() -> list[dict]:
    rows = own_schedules()
    extra = site_stats_extra()
    for fn, n in extra.items():
        rows.setdefault(fn, {"schedule": None, "own": 0})["via_site_stats_refresh"] = n
    for r in rows.values():
        r.setdefault("via_site_stats_refresh", 0)
        r["total"] = (r["own"] or 0) + r["via_site_stats_refresh"]
    return [dict(function=k, **v) for k, v in sorted(rows.items())]


def main() -> int:
    rows = table()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{'function':38} {'own/day':>8} {'+site-stats':>11} {'total':>6}  schedule")
    for r in rows:
        own = "?" if r["own"] is None else r["own"]
        print(f"{r['function']:38} {own:>8} {r['via_site_stats_refresh']:>11} {r['total']:>6}  {r['schedule']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

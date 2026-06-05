"""
vacation_fund.py — shared compute for the "vacation fund" tracker.

Game: every mile of workout distance since EXPERIMENT_START_DATE earns $1
(configurable) toward a shared vacation fund. This module is the single source
of the miles->USD math, imported by three Lambdas via the shared layer:
  - MCP tool        (mcp/tools_vacation.py)
  - site-api        (lambdas/web/site_api_lambda.py  →  /api/vacation_fund)
  - daily brief     (lambdas/emails/daily_brief_lambda.py)

Sources (additive, per the user's choice — see plan / ADR):
  - strava                  daily aggregate, field `total_distance_miles` (MILES),
                            per-activity `activities[].{sport_type, distance_miles}`.
                            Strava already holds Zwift VirtualRides + Garmin auto-syncs
                            + outdoor walks/runs, so Garmin is NOT counted separately.
  - hevy (opt-in)           per-workout records; cardio distance at
                            `exercises[].sets[].distance_m` (METERS).
  - macrofactor_export      legacy daily aggregate partition `macrofactor_workouts`;
                            `workouts[].exercises[].sets[].{distance_miles, distance_yards}`.

Hevy/MacroFactor MAY overlap Strava (same ride logged twice). That's accepted by
design; the per-source breakdown surfaces it and `manual_adjustment_usd` corrects it.

No mcp.* imports — this module lives in the shared layer (lambdas/*.py) and uses
boto3 directly. Read-only: queries DDB + reads S3 config; never writes.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from constants import EXPERIMENT_START_DATE

logger = logging.getLogger("vacation_fund")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
S3_CONFIG_PREFIX = os.environ.get("CONFIG_S3_PREFIX", "config/")
CONFIG_DIR = os.environ.get(
    "CONFIG_DIR", os.path.join(os.path.dirname(__file__), "..", "config"))

_MI_PER_METER = 1.0 / 1609.34
_MI_PER_YARD = 1.0 / 1760.0
_VALID_EXTRA_SOURCES = ("hevy", "macrofactor_export")

# macrofactor_export is the public label; the DDB partition is macrofactor_workouts.
_SOURCE_PARTITION = {
    "hevy": "hevy",
    "macrofactor_export": "macrofactor_workouts",
}

_DEFAULT_CONFIG = {
    "rate_per_mile": 1.0,
    "start_date": None,                       # None → EXPERIMENT_START_DATE
    "included_sport_types": "all",            # "all" or list of Strava sport_types
    "extra_sources": ["hevy", "macrofactor_export"],
    "manual_adjustment_usd": 0.0,
}

_ddb_table = None


def _table():
    global _ddb_table
    if _ddb_table is None:
        _ddb_table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")
        ).Table(TABLE_NAME)
    return _ddb_table


def _f(x) -> float:
    """Decimal/None-safe float."""
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _today_pt() -> str:
    """Today's date in Pacific (the platform's user-facing zone)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def load_config() -> dict[str, Any]:
    """Load config/vacation_fund.json (local first for tests, then S3); merge over
    defaults so a missing/partial file never errors."""
    cfg = dict(_DEFAULT_CONFIG)
    raw: dict[str, Any] = {}
    local = os.path.join(CONFIG_DIR, "vacation_fund.json")
    try:
        if os.path.exists(local):
            with open(local, encoding="utf-8") as fh:
                raw = json.load(fh) or {}
        else:
            obj = boto3.client(
                "s3", region_name=os.environ.get("AWS_REGION", "us-west-2")
            ).get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}vacation_fund.json")
            raw = json.loads(obj["Body"].read()) or {}
    except Exception as e:
        logger.info(f"vacation_fund config load fell back to defaults: {e}")
    for k, v in raw.items():
        if v is not None and k in cfg:
            cfg[k] = v
    return cfg


def _query_range(partition: str, start_date: str, end_date: str) -> list[dict]:
    """All items for a source partition with sk in [DATE#start, DATE#end + suffixes].
    The high sentinel captures DATE#end and any DATE#end#WORKOUT#... suffix."""
    pk = f"USER#{USER_ID}#SOURCE#{partition}"
    items: list[dict] = []
    last_key = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk)
            & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}￿"),
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table().query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


def _strava_miles(start_date: str, end_date: str, included_sport_types):
    """Return (total_miles, per_sport_type). When included_sport_types is a list,
    only those Strava sport_types count; otherwise use the daily total."""
    records = _query_range("strava", start_date, end_date)
    filter_set = None
    if isinstance(included_sport_types, (list, tuple)):
        filter_set = {str(s).strip().lower() for s in included_sport_types}
    total = 0.0
    per_sport: dict[str, float] = {}
    for rec in records:
        activities = rec.get("activities") or []
        # Per-sport breakdown always comes from the activity list.
        for a in activities:
            sport = (a.get("sport_type") or "Unknown")
            miles = _f(a.get("distance_miles"))
            if filter_set is not None and sport.lower() not in filter_set:
                continue
            per_sport[sport] = round(per_sport.get(sport, 0.0) + miles, 2)
        if filter_set is None:
            total += _f(rec.get("total_distance_miles"))
        else:
            total += sum(_f(a.get("distance_miles")) for a in activities
                         if (a.get("sport_type") or "").lower() in filter_set)
    return round(total, 2), per_sport


def _hevy_miles(start_date: str, end_date: str) -> float:
    miles = 0.0
    for w in _query_range("hevy", start_date, end_date):
        for ex in (w.get("exercises") or []):
            for s in (ex.get("sets") or []):
                miles += _f(s.get("distance_m")) * _MI_PER_METER
    return round(miles, 2)


def _macrofactor_miles(start_date: str, end_date: str) -> float:
    miles = 0.0
    for day in _query_range(_SOURCE_PARTITION["macrofactor_export"], start_date, end_date):
        for w in (day.get("workouts") or []):
            for ex in (w.get("exercises") or []):
                for s in (ex.get("sets") or []):
                    if s.get("distance_miles") is not None:
                        miles += _f(s.get("distance_miles"))
                    elif s.get("distance_yards") is not None:
                        miles += _f(s.get("distance_yards")) * _MI_PER_YARD
                    elif s.get("distance_m") is not None:
                        miles += _f(s.get("distance_m")) * _MI_PER_METER
    return round(miles, 2)


def compute_vacation_fund(start_date: str | None = None,
                          end_date: str | None = None) -> dict[str, Any]:
    """Total workout miles -> USD vacation fund. See module docstring. Never raises
    on missing data/config — returns zeros with a warning instead."""
    cfg = load_config()
    start = start_date or cfg.get("start_date") or EXPERIMENT_START_DATE
    end = end_date or _today_pt()
    rate = _f(cfg.get("rate_per_mile")) or 1.0
    manual_adj = _f(cfg.get("manual_adjustment_usd"))
    included = cfg.get("included_sport_types", "all")
    warnings: list[str] = []

    enabled_extras = [s for s in (cfg.get("extra_sources") or [])
                      if s in _VALID_EXTRA_SOURCES]
    type_filter_active = isinstance(included, (list, tuple))

    strava_miles, per_sport = _strava_miles(start, end, included)
    per_source: dict[str, float] = {"strava": strava_miles}
    total_miles = strava_miles

    # Extra sources can't be sport-type-classified, so they're only added when no
    # type filter is in effect (the default "all" case).
    if type_filter_active and enabled_extras:
        warnings.append(
            "included_sport_types filter is active; Hevy/MacroFactor extra sources "
            "skipped (they have no Strava sport_type to filter on).")
    else:
        for src in enabled_extras:
            m = _hevy_miles(start, end) if src == "hevy" else _macrofactor_miles(start, end)
            per_source[src] = m
            total_miles += m
        if enabled_extras:
            warnings.append(
                "Hevy/MacroFactor miles are added on top of Strava and may overlap it "
                "(a ride logged in both is counted twice). Per-source breakdown shows each; "
                "use manual_adjustment_usd to correct.")

    total_miles = round(total_miles, 2)
    miles_usd = round(total_miles * rate, 2)
    total_usd = round(miles_usd + manual_adj, 2)

    day_count = max((date.fromisoformat(end) - date.fromisoformat(start)).days + 1, 1)
    weeks = day_count / 7.0
    miles_per_week = round(total_miles / weeks, 2) if weeks else 0.0
    projected_usd_1yr = round(miles_per_week * 52 * rate + manual_adj, 2)

    if total_miles == 0:
        warnings.append(
            f"No workout miles recorded yet for {start}..{end} "
            f"(experiment genesis is {EXPERIMENT_START_DATE}).")

    return {
        "start_date": start,
        "end_date": end,
        "day_count": day_count,
        "rate_per_mile": rate,
        "total_miles": total_miles,
        "miles_usd": miles_usd,
        "manual_adjustment_usd": round(manual_adj, 2),
        "total_usd": total_usd,
        "per_sport_type": per_sport,
        "per_source": per_source,
        "pace": {
            "miles_per_week": miles_per_week,
            "projected_usd_1yr": projected_usd_1yr,
        },
        "extra_sources_enabled": enabled_extras if not type_filter_active else [],
        "included_sport_types": included,
        "warnings": warnings,
    }

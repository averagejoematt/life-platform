"""cdk/stacks/schedule_table.py — the reader for config/schedules.json, THE schedule table (#4284).

Every EventBridge schedule the CDK app creates is a row in `config/schedules.json`; no stack
carries a `cron(...)`/`rate(...)` literal (tests/test_schedule_table_4284.py). Two kinds of key:

  ``<function-name>``                 the schedule `create_platform_lambda` attaches to that
                                      function — the factory looks it up by `function_name`, so a
                                      call site cannot forget it or state it a second time.
  ``<function-name>#<ConstructId>``   a schedule built BESIDE the factory (a second schedule with
                                      a constant input, a disabled one, a named one) — the stack
                                      builds it by key through `lambda_helpers.add_table_schedule`,
                                      naming the row as `table_schedule("<key>")`.

THE ZONE (owner ruling on #4284, 2026-10-27; ADR-165). The table's top-level `platform_timezone`
(America/Los_Angeles) is the one system-level zone every row follows: a `cron(...)` expression is
WALL-CLOCK time in that zone, carried by an EventBridge Scheduler schedule that follows the DST
change. A row may opt out with `"timezone": "UTC"` ONLY beside a non-empty `utc_reason` (it then
stays a fixed-UTC `events.Rule`); a `rate(...)` row has no wall clock and may carry no zone.
`load()` returns every row with the zone RESOLVED: `timezone` is present (the platform zone,
unless the row names another IANA zone) exactly when the row runs on wall-clock time, and absent
on a UTC opt-out or a rate — so every reader keeps the one test it already had,
`row.get("timezone")` -> zoned. `zone(row)` is the same answer as a function.

Stdlib only, no CDK import: the platform model, the boot brief and the CI guards read the same
rows without a CDK install. The path comes from `common.repo_config` (never a fixed nesting depth).
"""

from __future__ import annotations

import functools
import json
import os
import sys

_LAMBDAS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "lambdas"))
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)
from common.repo_config import config_path  # noqa: E402

REQUIRED = ("function", "stack", "expression", "facing", "purpose")
FACINGS = ("reader", "internal")


class ScheduleTableError(ValueError):
    """The table is malformed, or a stack asked for a key it does not carry."""


def table_path() -> str:
    return config_path("schedules.json")


PLATFORM_TIMEZONE_KEY = "platform_timezone"
UTC = "UTC"


@functools.lru_cache(maxsize=None)
def _raw(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def platform_timezone(path: str | None = None) -> str:
    """The ONE system-level zone every schedule follows (config/schedules.json `platform_timezone`)."""
    tz = _raw(path or table_path()).get(PLATFORM_TIMEZONE_KEY)
    if not isinstance(tz, str) or not tz:
        raise ScheduleTableError("config/schedules.json lacks the top-level `platform_timezone` (#4284, ADR-165)")
    return tz


def _resolve_zone(key: str, row: dict, platform_tz: str) -> str | None:
    """The zone a raw row runs in: None for a rate or a UTC opt-out (fixed UTC), else an IANA zone."""
    explicit = row.get("timezone")
    if row["expression"].startswith("rate("):
        if explicit:
            raise ScheduleTableError(f"config/schedules.json[{key!r}]: a rate(...) row has no wall clock — drop its `timezone`")
        return None
    if explicit == UTC:
        if not str(row.get("utc_reason") or "").strip():
            raise ScheduleTableError(
                f"config/schedules.json[{key!r}] opts out to UTC without a `utc_reason` — every row follows "
                f"`platform_timezone` unless it says why not (#4284, ADR-165)"
            )
        return None
    if row.get("utc_reason"):
        raise ScheduleTableError(f"config/schedules.json[{key!r}] carries a `utc_reason` but is not a UTC row")
    zone = explicit or platform_tz
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(zone)
    except Exception as exc:  # noqa: BLE001 — any lookup failure is a malformed table
        raise ScheduleTableError(f"config/schedules.json[{key!r}]: {zone!r} is not an IANA time zone ({exc})") from exc
    return zone


@functools.lru_cache(maxsize=None)
def _load(path: str) -> dict[str, dict]:
    raw = _raw(path)
    platform_tz = platform_timezone(path)
    rows = {}
    for key, raw_row in raw["schedules"].items():
        row = {k: v for k, v in raw_row.items() if k != "timezone"}
        rows[key] = row
        missing = [f for f in REQUIRED if not row.get(f)]
        if missing:
            raise ScheduleTableError(f"config/schedules.json[{key!r}] lacks {missing}")
        base = key.split("#", 1)[0]
        if base != row["function"]:
            raise ScheduleTableError(f"config/schedules.json[{key!r}]: key names {base!r} but function is {row['function']!r}")
        if row["facing"] not in FACINGS:
            raise ScheduleTableError(f"config/schedules.json[{key!r}]: facing {row['facing']!r} not in {FACINGS}")
        expr = row["expression"]
        if not (expr.startswith(("cron(", "rate(")) and expr.endswith(")")):
            raise ScheduleTableError(f"config/schedules.json[{key!r}]: {expr!r} is not a cron(...)/rate(...) expression")
        zone = _resolve_zone(key, raw_row, platform_tz)
        if zone:
            row["timezone"] = zone
    return rows


def zone(row: dict) -> str | None:
    """A loaded row's zone: the IANA zone its wall-clock expression runs in, or None (fixed UTC / rate)."""
    return row.get("timezone") or None


def load(path: str | None = None) -> dict[str, dict]:
    """Every row, keyed as above, its zone RESOLVED (see the module docstring). Cached per path;
    callers must not mutate the result."""
    return _load(path or table_path())


def entry(key: str, path: str | None = None) -> dict:
    """The row for `key`, or ScheduleTableError naming the file to edit."""
    rows = load(path)
    if key not in rows:
        raise ScheduleTableError(f"no schedule {key!r} in config/schedules.json — add the row there, never a literal in the stack")
    return rows[key]


def factory_entry(function_name: str, path: str | None = None) -> dict | None:
    """The schedule `create_platform_lambda` attaches to `function_name`, or None (unscheduled)."""
    return load(path).get(function_name)


def by_function(path: str | None = None) -> dict[str, list[dict]]:
    """function name -> its rows (each with its `key`), in key order."""
    out: dict[str, list[dict]] = {}
    for key, row in sorted(load(path).items()):
        out.setdefault(row["function"], []).append({"key": key, **row})
    return out

#!/usr/bin/env python3
"""scripts/schedule_tz_convert.py — shift an EventBridge cron expression by a whole-hour offset (#4284).

WHY THIS EXISTS
  The owner's 2026-10-27 ruling on #4284 ("B"): one `platform_timezone` at the top of
  config/schedules.json, every schedule on it, before the clocks change on 2026-11-01. Every
  row had been a fixed-UTC `cron(...)`; each had to become the SAME instants as Pacific
  wall-clock under PDT (UTC-7), so that nothing moves on the day of the migration and from
  2026-11-01 every job keeps its Pacific time. This is the deterministic converter that did
  it — run once (`--apply`), and re-derived for every migrated row by
  tests/test_platform_timezone_4284.py from the pre-migration snapshot
  (tests/fixtures/schedules_utc_pre_4284.json), so the rewrite is checkable, never trusted.

WHAT IT HANDLES
  minute       unchanged (the offset is whole hours)
  hour         `*`, single values, lists, ranges and steps — expanded to a set, shifted, and
               re-rendered canonically: a whole-day every-n progression of three or more
               stays a step (`0/8` UTC -> `1/8`), runs of three or more become `a-b`
  midnight     an hour that crosses midnight moves to the previous (or next) day. When the
               day fields are unrestricted (`* * ?` / `? * *`) every day is the same, so no day
               field changes. When the day-of-week is restricted it shifts (`SAT`->`FRI`,
               `MON-FRI`->`SUN-THU`, numeric `1`=SUN..`7`=SAT). When the day-of-month is
               restricted it shifts inside the month (`15`->`14`); a shift that would leave the
               month (`1`->"last day of the previous month") is refused.
  refused      (CronShiftError — the row is opted out to UTC with a reason, or rewritten by
               hand) an nth-weekday (`1#1`) or `L`/`W` day field whose hours cross midnight
               (the weekday before "the first Sunday" can be in the previous month), and a
               day-of-month shift across a month edge.
  split        an hour list whose hours land on DIFFERENT days on a restricted-day row comes
               back as two expressions (one per day shift). `--apply` refuses a split rather
               than invent a second row key; none of the 2026-10-27 rows needed one.

USAGE
  python3 scripts/schedule_tz_convert.py "cron(0 2 ? * SAT *)" --hours -7     # -> cron(0 19 ? * FRI *)
  python3 scripts/schedule_tz_convert.py --apply [--hours -7]                  # the one-time migration

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLE = ROOT / "config" / "schedules.json"
PLATFORM_TIMEZONE = "America/Los_Angeles"
TABLE_DOC = (
    "THE schedule table (#4284): every EventBridge schedule the CDK app creates. Key = the AWS function name for the "
    "create_platform_lambda schedule (the factory reads it by function_name), or '<function>#<ConstructId>' for a schedule "
    "built beside the factory (lambda_helpers.add_table_schedule). `expression` is WALL-CLOCK time in `platform_timezone` "
    "(owner ruling on #4284, 2026-10-27; ADR-165) on an EventBridge Scheduler schedule that follows the DST change. A row "
    'may opt out with "timezone": "UTC" ONLY beside a `utc_reason` (it then stays a fixed-UTC events.Rule); a `rate(...)` '
    "row has no wall clock and stays an events.Rule. `facing` records the reader/internal split; `stack` is the CloudFormation "
    "stack the factory asserts at synth. Reader: cdk/stacks/schedule_table.py; guards: tests/test_schedule_table_4284.py, "
    "tests/test_platform_timezone_4284.py; rule: docs/CONVENTIONS.md 1b."
)
#: PDT is UTC-7: a UTC hour h is Pacific wall-clock h-7 on the migration day (2026-10-27).
PDT_OFFSET_HOURS = -7

#: Rows the migration leaves on fixed UTC, each with the reason the table records (`utc_reason`).
#: An every-hour cron is zone-invariant as an expression, but a zoned schedule runs ONCE in the
#: repeated fall-back hour and not at all in the skipped spring-forward hour (the AWS Scheduler
#: DST rule) — a fixed-UTC rule keeps exactly one run every 60 minutes through both changes.
UTC_OPT_OUTS = {
    "habitify-data-ingestion": "every hour at :05 — a cadence, not a wall-clock time; fixed UTC keeps 24 evenly spaced runs through both DST changes (a zoned schedule would drop the repeated 01:05 on the fall-back night)",
    "hevy-backfill": "every hour at :00 — a cadence, not a wall-clock time (#3720: never a blind hour); fixed UTC keeps 24 evenly spaced runs through both DST changes (a zoned schedule would drop the repeated 01:00 on the fall-back night)",
}

DOW_NAMES = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")  # EventBridge numeric: 1=SUN .. 7=SAT


class CronShiftError(ValueError):
    """The expression has a shape this converter refuses to shift (see the module docstring)."""


def _expand(field: str, lo: int, hi: int, names: tuple[str, ...] = ()) -> set[int]:
    """Every value a numeric cron field selects. `names` maps a name to lo+index (DOW)."""

    def val(tok: str) -> int:
        tok = tok.upper()
        if names and tok in names:
            return lo + names.index(tok)
        if not tok.isdigit():
            raise CronShiftError(f"cannot read cron value {tok!r} in field {field!r}")
        v = int(tok)
        if not lo <= v <= hi:
            raise CronShiftError(f"cron value {v} outside {lo}-{hi} in field {field!r}")
        return v

    out: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronShiftError(f"bad step in cron field {field!r}")
            step = int(step_s)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = val(a), val(b)
            if end < start:
                raise CronShiftError(f"wrapping range {part!r} in cron field {field!r}")
        else:
            start = val(part)
            end = hi if step > 1 else start
        out.update(range(start, end + 1, step))
    return out


def _render(values: set[int], lo: int, hi: int, names: tuple[str, ...] = ()) -> str:
    """Canonical text for a set of field values: `*` when full; `a/n` when the values are an
    every-n progression of three or more across the whole field (`1,9,17` hours -> `1/8`, so "every 8 hours" stays
    readable as a cadence); else runs of >=3 as `a-b`."""
    if values == set(range(lo, hi + 1)):
        return "*"
    vals = sorted(values)
    if not names and len(vals) >= 3:
        step = vals[1] - vals[0]
        if step > 1 and vals[0] - lo < step and values == set(range(vals[0], hi + 1, step)):
            return f"{vals[0]}/{step}"

    def txt(v: int) -> str:
        return names[v - lo] if names else str(v)

    vals = sorted(values)
    parts: list[str] = []
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{txt(vals[i])}-{txt(vals[j])}")
        else:
            parts.extend(txt(v) for v in vals[i : j + 1])
        i = j + 1
    return ",".join(parts)


def _shift_dow(field: str, delta: int) -> str:
    if any(c in field for c in "#L"):
        raise CronShiftError(f"day-of-week {field!r} is an nth/last weekday; shifting it across midnight can leave the month")
    numeric = not any(ch.isalpha() for ch in field)
    days = _expand(field, 1, 7, DOW_NAMES)
    shifted = {((d - 1 + delta) % 7) + 1 for d in days}
    if numeric:
        return _render(shifted, 1, 7)
    return _render(shifted, 1, 7, DOW_NAMES)


def _shift_dom(field: str, delta: int) -> str:
    if any(c in field for c in "LW#"):
        raise CronShiftError(f"day-of-month {field!r} uses L/W; shifting it across midnight is not well-defined")
    days = _expand(field, 1, 31)
    shifted = {d + delta for d in days}
    if min(shifted) < 1 or max(shifted) > 28:
        raise CronShiftError(f"day-of-month {field!r} shifted by {delta} day(s) leaves the month for some month")
    return _render(shifted, 1, 31)


def shift_cron(expr: str, hours: int) -> list[str]:
    """`expr` shifted by `hours` (UTC -> PDT is -7; PDT -> UTC is +7). One expression, or two on a
    split (see the module docstring). A `rate(...)` expression is returned unchanged."""
    expr = expr.strip()
    if expr.startswith("rate(") and expr.endswith(")"):
        return [expr]
    if not (expr.startswith("cron(") and expr.endswith(")")):
        raise CronShiftError(f"{expr!r} is not a cron(...)/rate(...) expression")
    if not -23 <= hours <= 23:
        raise CronShiftError(f"offset {hours} h is not inside one day")
    fields = expr[len("cron(") : -1].split()
    if len(fields) != 6:
        raise CronShiftError(f"{expr!r} does not have the six EventBridge cron fields")
    minute, hour, dom, month, dow, year = fields
    by_delta: dict[int, set[int]] = {}
    for h in _expand(hour, 0, 23):
        by_delta.setdefault((h + hours) // 24, set()).add((h + hours) % 24)
    days_free = dom in ("*", "?") and dow in ("*", "?")
    if days_free or set(by_delta) == {0}:
        hours_out = set().union(*by_delta.values())
        return [f"cron({minute} {_render(hours_out, 0, 23)} {dom} {month} {dow} {year})"]
    out = []
    for delta in sorted(by_delta):
        new_dom, new_dow = dom, dow
        if delta:
            if dow not in ("*", "?"):
                new_dow = _shift_dow(dow, delta)
            if dom not in ("*", "?"):
                new_dom = _shift_dom(dom, delta)
        out.append(f"cron({minute} {_render(by_delta[delta], 0, 23)} {new_dom} {month} {new_dow} {year})")
    return out


def migrate(table: dict, hours: int = PDT_OFFSET_HOURS) -> tuple[dict, list[str]]:
    """The migrated table + a change log. Rows already carrying a `timezone` are wall-clock
    already (the 2026-10-18 `daily-brief`): their expression is kept and the now-redundant
    zone key dropped when it equals the platform zone. Refuses (raises) on a split."""
    out = {"_doc": TABLE_DOC, "platform_timezone": PLATFORM_TIMEZONE}
    out.update({k: v for k, v in table.items() if k not in ("_doc", "platform_timezone", "schedules")})
    rows: dict[str, dict] = {}
    log: list[str] = []
    for key, row in table["schedules"].items():
        row = dict(row)
        expr = row["expression"]
        if row.get("timezone") == PLATFORM_TIMEZONE:
            row.pop("timezone")
            log.append(f"{key}: already {PLATFORM_TIMEZONE} wall-clock — {expr} kept, explicit zone dropped")
        elif row.get("timezone"):
            log.append(f"{key}: explicit zone {row['timezone']} — untouched")
        elif key in UTC_OPT_OUTS:
            row["timezone"] = "UTC"
            row["utc_reason"] = UTC_OPT_OUTS[key]
            log.append(f"{key}: {expr} — opted out to fixed UTC: {UTC_OPT_OUTS[key]}")
        elif expr.startswith("cron("):
            new = shift_cron(expr, hours)
            if len(new) != 1:
                raise CronShiftError(f"{key}: {expr} splits into {new} — add the second row by hand or opt the row out to UTC")
            row["expression"] = new[0]
            log.append(f"{key}: {expr} UTC -> {new[0]} {PLATFORM_TIMEZONE}")
        else:
            log.append(f"{key}: {expr} — a rate, no wall clock; unchanged")
        rows[key] = row
    out["schedules"] = rows
    return out, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("expression", nargs="?", help="a cron(...) expression to shift and print")
    ap.add_argument("--hours", type=int, default=PDT_OFFSET_HOURS, help="whole-hour offset (default -7: UTC -> PDT)")
    ap.add_argument("--apply", action="store_true", help="rewrite config/schedules.json in place (the one-time #4284 migration)")
    args = ap.parse_args(argv)
    if args.expression:
        print("\n".join(shift_cron(args.expression, args.hours)))
        return 0
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    if "platform_timezone" in table and args.apply:
        print("config/schedules.json already carries platform_timezone — the migration has run; refusing to shift twice", file=sys.stderr)
        return 1
    new, log = migrate(table, args.hours)
    print("\n".join(log))
    if args.apply:
        TABLE.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""cdk/stacks/schedule_table.py — the reader for config/schedules.json, THE schedule table (#4284).

Every EventBridge schedule the CDK app creates is a row in `config/schedules.json`; no stack
carries a `cron(...)`/`rate(...)` literal (tests/test_schedule_table_4284.py). Two kinds of key:

  ``<function-name>``                 the schedule `create_platform_lambda` attaches to that
                                      function — the factory looks it up by `function_name`, so a
                                      call site cannot forget it or state it a second time.
  ``<function-name>#<ConstructId>``   a rule built BESIDE the factory (a second schedule with a
                                      constant input, a disabled rule, a named rule) — the stack
                                      asks for it by key through `lambda_helpers.table_schedule`.

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


@functools.lru_cache(maxsize=None)
def _load(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)["schedules"]
    for key, row in rows.items():
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
    return rows


def load(path: str | None = None) -> dict[str, dict]:
    """Every row, keyed as above. Cached per path; callers must not mutate the result."""
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

"""supplement_join_qa.py — #4245 box 5: the dead-man on the supplement join going dark.

Micronutrient intake joins two channels (#4333/#4465): food from MacroFactor and the
supplement stack from `USER#matthew#SOURCE#supplements`. The supplements partition has
exactly one writer, habitify's post-store `supplement_bridge`, and that bridge fails
SILENTLY by design ("failures here are logged but never raised"). On 2026-09-06 the owner
ticked four supplements and the bridge wrote nothing (#3666). When the join goes dark
nothing reds: `nutrient_intake` reads a missing row as `supplements_state: "absent"`, which
is the honest state for a day with no record, so every consumer quietly falls back to a
food-only number.

Two legs, each over the last three CLOSED Pacific days:

  * **bridge dark** — Habitify resolved at least one registry supplement `completed` on a
    day, and the supplements partition holds no bridge entry for that day. The owner took
    something and the join cannot see it. The reverse (a bridge row with no tick) is not a
    violation: MCP `log_supplement` writes manual entries to the same row.
  * **join dark** — the day's row carries a dose the registry can convert (a content-bearing
    `SUPPLEMENT_NUTRIENT_CONTENT` entry), yet `nutrient_intake` counts nothing from it. The
    row reached the partition and fell out at the read seam (a renamed bridge habit, an
    emptied registry row, a lost unit conversion).

Absence is louder than failure: a window with no Habitify record at all, or no supplement
tick on any day, WARNS by name ("not evaluable") instead of passing.

Dependency-injected like habit_cross_source_qa: qa_smoke_lambda owns the clients and the
nightly wiring, this module owns the logic, and `join_violations` is a pure function so the
contract replays offline against stored rows (tests/test_habit_cross_source_contract_3666.py).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Optional

from health.nutrient_intake import SUPPLEMENT_NUTRIENT_CONTENT, nutrient_intake

# Closed Pacific days replayed per run. Three, like acwr_liveness: one dark night pages on
# the next sweep, and a single late tick never has to carry the verdict alone.
WINDOW_DAYS = 3
BRIDGE_SOURCE = "habitify_bridge"

_REGISTRY_BY_NORM = {name.strip().lower(): spec for name, spec in SUPPLEMENT_NUTRIENT_CONTENT.items()}


def ticked_supplements(habit_row: Optional[Mapping[str, Any]]) -> list[str]:
    """Registry supplement habits Habitify resolved `completed` that day, sorted."""
    statuses = (habit_row or {}).get("habit_statuses")
    if not isinstance(statuses, Mapping):
        return []
    out = []
    for name, hs in statuses.items():
        if str(name).strip().lower() not in _REGISTRY_BY_NORM or not isinstance(hs, Mapping):
            continue
        if hs.get("status") == "completed":
            out.append(str(name))
    return sorted(out)


def _bridge_entries(supplement_row: Optional[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    entries = (supplement_row or {}).get("supplements")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, Mapping) and e.get("source") == BRIDGE_SOURCE]


def _content_bearing(supplement_row: Optional[Mapping[str, Any]]) -> list[str]:
    """Names in the row whose registry entry carries nutrient content the join must count."""
    entries = (supplement_row or {}).get("supplements")
    names = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, Mapping):
            continue
        spec = _REGISTRY_BY_NORM.get(str(e.get("name") or "").strip().lower())
        if spec and spec.get("content"):
            names.append(str(e.get("name")))
    return sorted(set(names))


def join_violations(date_str: str, habit_row, supplement_row) -> list[str]:
    """The pure contract for one day. Returns one message per dark leg (empty == joined)."""
    out = []
    ticked = ticked_supplements(habit_row)
    if ticked and not _bridge_entries(supplement_row):
        out.append(
            f"{date_str}: bridge dark — Habitify resolved {len(ticked)} supplement(s) completed "
            f"({', '.join(ticked[:6])}{'…' if len(ticked) > 6 else ''}) but the supplements partition "
            f"holds no {BRIDGE_SOURCE} entry for that day (#4245)"
        )
    bearing = _content_bearing(supplement_row)
    if bearing and not nutrient_intake(None, supplement_row, habit_row).get("counted"):
        out.append(
            f"{date_str}: join dark — the supplements row carries content-bearing dose(s) "
            f"({', '.join(bearing[:6])}) but nutrient_intake counted nothing from them (#4245)"
        )
    return out


def check_supplement_join_liveness(table, user_prefix, check_cls, partition, pt_now):
    """Nightly leg: replay the join contract over the last WINDOW_DAYS closed Pacific days."""
    c = check_cls("supplement_join_liveness", "Data Freshness", partition)
    now_pt = pt_now()
    violations: list[str] = []
    habit_days = 0
    tick_days = 0
    try:
        for i in range(1, WINDOW_DAYS + 1):
            day = (now_pt - timedelta(days=i)).strftime("%Y-%m-%d")
            habit = table.get_item(Key={"pk": user_prefix + "habitify", "sk": "DATE#" + day}).get("Item") or {}
            supp = table.get_item(Key={"pk": user_prefix + "supplements", "sk": "DATE#" + day}).get("Item") or None
            if habit.get("habit_statuses"):
                habit_days += 1
            if ticked_supplements(habit):
                tick_days += 1
            violations += join_violations(day, habit, supp)
    except Exception as e:
        c.fail(f"supplement join liveness — DDB error: {e}")
        return [c]
    if violations:
        c.fail("; ".join(violations))
    elif not habit_days:
        c.warn(f"no habitify habit_statuses on any of the last {WINDOW_DAYS} closed days — supplement join not evaluable")
    elif not tick_days:
        c.warn(f"no supplement habit completed on any of the last {WINDOW_DAYS} closed days — the bridge leg had nothing to carry")
    else:
        c.ok(f"supplement join live: {tick_days}/{WINDOW_DAYS} closed day(s) with ticks, each bridged and counted")
    return [c]

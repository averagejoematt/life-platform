"""habit_identity.py — #4632: a habit IS its vendor habit id; its display names are aliases.

Habitify lets the owner rename a habit at any time, and until #4632 every structure on the
platform was keyed on the display name, so a rename split one habit's history (and its
streak) in two. Since #4632 (PR #4921) the Habitify ingest stores the vendor's `habit_id`
on every `habit_statuses` entry, and stamps `aliases` — every OTHER name that same id has
carried on earlier stored days, derived at ingest from id continuity between rows
(`habitify_lambda._prior_identity`). This module is the read side of that: given one
stored day and one registry entry, under which name does the day carry that habit?

Resolution order (first hit wins):

  1. the registry entry's own `habitify_id` matches an entry's `habit_id`   (id-keyed);
  2. the entry's key or any of its `habitify_names` is a name on the day   (#4362, the
     only rule the rows written before ids existed can answer);
  3. an entry on the day lists one of those names in its `aliases`        (a rename the
     registry has not caught up with — id continuity found it at ingest).

#4644 Q26 (recommended answer, HELD for the owner's ruling): "same habit keeps its streak
(id-keyed), applied to the history too". Rule 3 is what makes a rename after ids began keep
its streak with no registry edit; renames already in history (before ids were stored) still
resolve through rule 2's hand-kept `habitify_names`.

Pure: no I/O, no clock.
"""

from typing import Any, Optional


def registry_names(key: str, meta: Optional[dict[str, Any]]) -> list[str]:
    """The names a registry entry answers to: its key, then its `habitify_names` (#4362)."""
    names = [key]
    for n in (meta or {}).get("habitify_names") or []:
        if isinstance(n, str) and n and n not in names:
            names.append(n)
    return names


def _by_id(statuses: dict, habit_id: str) -> Optional[str]:
    for n, hs in statuses.items():
        if isinstance(hs, dict) and hs.get("habit_id") and str(hs["habit_id"]) == habit_id:
            return n
    return None


def _by_alias(statuses: dict, names: list[str]) -> Optional[str]:
    wanted = set(names)
    for n in sorted(statuses):
        hs = statuses[n]
        aliases = hs.get("aliases") if isinstance(hs, dict) else None
        if isinstance(aliases, (list, tuple, set)) and wanted & {a for a in aliases if isinstance(a, str)}:
            return n
    return None


def day_name_for(habits_map: dict, statuses: Optional[dict], key: str, meta: Optional[dict[str, Any]] = None) -> Optional[str]:
    """The name under which ONE stored day carries registry habit `key`, or None (unobserved)."""
    statuses = statuses if isinstance(statuses, dict) else {}
    habit_id = (meta or {}).get("habitify_id")
    if habit_id and statuses:
        hit = _by_id(statuses, str(habit_id))
        if hit is not None:
            return hit
    names = registry_names(key, meta)
    for n in names:
        if n in habits_map or n in statuses:
            return n
    return _by_alias(statuses, names) if statuses else None

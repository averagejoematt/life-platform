"""habit_pct_public.py — the PUBLIC habit-completion share, ``habit-pct-public-v2`` (owner rulings 2026-11-06, 2026-11-26).

"Recompute habit_pct using only public-eligible habits, with versioned methodology and an auditable correction
record." ``habit_pct`` (the day's completed share of the habits Habitify reported) feeds the weekly correlations,
``/api/what_changed`` and the hypothesis engine — all published. Method 1 counted every habit the day's record named,
the Morning and Evening Journal habits among them, so a public correlation moved with journal activity.

The public method counts only habits ``common.activity_publication.habit_is_public`` classifies public, by identity
(the stored status's Habitify id; an unclassified habit fails closed). A day with no public habit has no value (None),
never a 0. Pure; the stored Habitify rows are unchanged.

v2 (#6224, owner ruling 2026-11-26: "Remove restraint-derived contributions from public streak milestones and
correlation metrics"): restraint habits are left out too, through THE shared restraint set
(``activity_publication.restraint_exclusions`` — the tracker group, the registry flag, a stored streak key). v1 counted
them, so a v1 share moved with whether a restraint habit was kept; ``activity_publication.PUBLIC_METRIC_METHODS`` names
v2 only, and a weekly_correlations record stamped v1 has its habit_pct pairs withheld.
"""

from __future__ import annotations

from typing import Any, Optional

from common import activity_publication

METHOD_VERSION = "habit-pct-public-v2"
METHOD_HISTORY = ("habit-pct-public-v1",)  # public habits, restraint habits counted (2026-11-06 → 2026-11-26)
EFFECTIVE_FROM = "2026-09-06"
METHOD_1 = "habit-pct-method-1"  # every habit the day's record named


def method1_habit_pct(habitify: Any) -> Optional[float]:
    """Method 1, kept for the correction record: done / total over every habit the record names."""
    habits = (habitify or {}).get("habits") if isinstance(habitify, dict) else None
    if not isinstance(habits, dict) or not habits:
        return None
    return sum(1 for v in habits.values() if v) / len(habits)


def public_habit_pct(habitify: Any, registry: Any = None, restraints: Any = None, window: Any = None) -> Optional[float]:
    """done / total over the PUBLIC, non-restraint habits the day's record names (None when it names none).
    ``restraints``: further restraint names the caller knows (stored streak keys, the window's union); ``window``: the
    stored Habitify rows around the day, whose restraint marks count too (``window_restraints``)."""
    rec: dict[str, Any] = habitify if isinstance(habitify, dict) else {}
    raw_habits, raw_statuses = rec.get("habits"), rec.get("habit_statuses")
    habits: dict[str, Any] = raw_habits if isinstance(raw_habits, dict) else {}
    statuses: dict[str, Any] = raw_statuses if isinstance(raw_statuses, dict) else {}
    reg: dict[str, Any] = registry if isinstance(registry, dict) else {}
    extra = set(restraints or ()) | (window_restraints(window, reg) if window else set())
    excluded = activity_publication.restraint_exclusions(statuses, reg, extra)
    public = [n for n in habits if str(n) not in excluded and activity_publication.habit_is_public(n, statuses.get(n), reg.get(n))]
    if not public:
        return None
    return len([n for n in public if habits[n]]) / len(public)


def window_restraints(habitify_rows: Any, registry: Any = None, extra: Any = None) -> set:
    """The restraint set over a window of stored Habitify rows (a habit marked a restraint on any day is one on every
    day) plus ``extra`` (stored streak keys) — what a caller passes as ``restraints`` (#6224)."""
    out = {str(x) for x in (extra or ())}
    for row in habitify_rows or ():
        if isinstance(row, dict):
            out |= activity_publication.restraint_exclusions(row.get("habit_statuses") or {}, registry)
    return out

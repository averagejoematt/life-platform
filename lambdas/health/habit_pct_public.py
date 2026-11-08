"""habit_pct_public.py — the PUBLIC habit-completion share, ``habit-pct-public-v1`` (owner ruling 2026-11-06).

"Recompute habit_pct using only public-eligible habits, with versioned methodology and an auditable correction
record." ``habit_pct`` (the day's completed share of the habits Habitify reported) feeds the weekly correlations,
``/api/what_changed`` and the hypothesis engine — all published. Method 1 counted every habit the day's record named,
the Morning and Evening Journal habits among them, so a public correlation moved with journal activity.

The public method counts only habits ``common.activity_publication.habit_is_public`` classifies public, by identity
(the stored status's Habitify id; an unclassified habit fails closed). A day with no public habit has no value (None),
never a 0. Pure; the stored Habitify rows are unchanged.
"""

from __future__ import annotations

from typing import Any, Optional

from common import activity_publication

METHOD_VERSION = "habit-pct-public-v1"
EFFECTIVE_FROM = "2026-09-06"
METHOD_1 = "habit-pct-method-1"  # every habit the day's record named


def method1_habit_pct(habitify: Any) -> Optional[float]:
    """Method 1, kept for the correction record: done / total over every habit the record names."""
    habits = (habitify or {}).get("habits") if isinstance(habitify, dict) else None
    if not isinstance(habits, dict) or not habits:
        return None
    return sum(1 for v in habits.values() if v) / len(habits)


def public_habit_pct(habitify: Any, registry: Any = None) -> Optional[float]:
    """done / total over the PUBLIC habits the day's record names (None when it names none)."""
    rec: dict[str, Any] = habitify if isinstance(habitify, dict) else {}
    raw_habits, raw_statuses = rec.get("habits"), rec.get("habit_statuses")
    habits: dict[str, Any] = raw_habits if isinstance(raw_habits, dict) else {}
    statuses: dict[str, Any] = raw_statuses if isinstance(raw_statuses, dict) else {}
    reg: dict[str, Any] = registry if isinstance(registry, dict) else {}
    public = [n for n in habits if activity_publication.habit_is_public(n, statuses.get(n), reg.get(n))]
    if not public:
        return None
    return len([n for n in public if habits[n]]) / len(public)

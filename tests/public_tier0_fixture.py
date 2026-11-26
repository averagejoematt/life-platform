"""tests/public_tier0_fixture.py — synthetic stored rows whose PUBLIC tier-0 run is a chosen length (#6224).

Since #6224 the milestone streak rungs are judged on the public tier-0 run (``activity_publication.public_tier0_figures``
over the stored Habitify rows and the owner's registry), never on the stored ``habit_scores.t0_perfect_streak`` (it
counts restraint habits). A test that used to plant a stored streak plants these rows instead. Synthetic names only.
"""

from __future__ import annotations

from datetime import date, timedelta

ORDINARY = "ordinary_a"  # one public tier-0 habit (a classified-public tracker id below)


def _public_id() -> str:
    from common import activity_publication as AP

    return sorted(AP.PUBLIC_HABIT_IDS)[0]


def profile_row(user_root: str = "USER#matthew") -> dict:
    """The owner's profile with one public tier-0 habit in the registry."""
    return {"pk": user_root, "sk": "PROFILE#v1", "habit_registry": {ORDINARY: {"status": "active", "tier": 0}}}


def habitify_row(user_prefix: str, day: str, done: bool) -> dict:
    status = {"status": "completed" if done else "failed", "habit_id": _public_id(), "group": "Core", "scheduled_today": True}
    return {"pk": user_prefix + "habitify", "sk": f"DATE#{day}", "date": day, "habit_statuses": {ORDINARY: status}}


def plant_public_run(put, user_prefix: str, day: str, streak: int, user_root: str = "USER#matthew") -> None:
    """Write (via ``put(item)``) the profile and the Habitify rows that make the public run ending ``day`` exactly
    ``streak``: perfect days ``day-streak+1 .. day`` and an imperfect day before them."""
    d = date.fromisoformat(day)
    put(profile_row(user_root))
    for back in range(streak):
        put(habitify_row(user_prefix, (d - timedelta(days=back)).isoformat(), True))
    put(habitify_row(user_prefix, (d - timedelta(days=streak)).isoformat(), False))

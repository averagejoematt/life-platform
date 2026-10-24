"""habit_context.py — the daily coaches' habit read (#5124, M4), split out of `ai.ai_calls` (at its size ceiling, #1665).

Two callers in `ai_calls` — the board of directors and the TL;DR + guidance call — name the day's missed habits to
the model. Once the core-12 calculation set is ARMED (any registry entry carries a `core` flag, `health.core_habits`),
they name only missed CORE habits, graded by `scoring_engine.core_day` (the scorer's own read, so a coach never names
a miss the score did not count) with the count of unknown ones; every other habit is retained and tracked but is not
named as a miss. Unarmed, the tier-0 / tier-1 lines are exactly what they were.
"""

from __future__ import annotations

from common.habit_registry import habit_tier  # #5232
from health import core_habits
from health.scoring_engine import core_day, habitify_reading  # #4362; #5124


def missed_registry_habits(registry, habitify):
    """The active registry habits the day records as NOT done, as (name, meta) in registry order.

    #4362/#4632: each resolved through `scoring_engine.habitify_reading` WITH the day's
    `habit_statuses` — by vendor id first, names as aliases (`health.habit_identity`) — so a
    habit renamed in Habitify is the same habit here as in the scoring and the streaks
    (#4644 Q26). Unobserved (None) is not a miss."""
    habitify = habitify or {}
    h_map, statuses = habitify.get("habits", {}), habitify.get("habit_statuses")
    out = []
    for h_name, meta in (registry or {}).items():
        if meta.get("status") != "active":
            continue
        done = habitify_reading(
            h_map, h_name, meta, statuses, (habitify.get("sk") or "").replace("DATE#", "") or habitify.get("date")
        )  # #5007
        if done is not None and done < 1:
            out.append((h_name, meta))
    return out


def core_habit_lines(data, profile):
    """`(lines, missed_labels)` once the core set is armed, or None (the tier lines stay). An unknown core habit is
    said as unknown, never as a miss."""
    if not core_habits.is_armed(profile.get("habit_registry") or {}):
        return None
    core = core_day(data, profile)
    head = f"\nCORE HABITS (the calculation set, charter habits.core): {core['done']} of {core['known']} known done"
    if core["unknown"]:
        head += f", {core['unknown']} unknown (no reading; never a miss)"
    if core["missed_labels"]:
        head += "\nMISSED CORE HABITS: " + "; ".join(core["missed_labels"])
    return head, list(core["missed_labels"])


def board_habit_ctx(data, profile):
    """`(habit_ctx, missed)` for the board call: the core lines when armed (and `missed`, which the synergy alert
    reads, limited to core members), else the tier-0 / tier-1 lines over every missed registry habit."""
    registry = profile.get("habit_registry", {})
    missed = missed_registry_habits(registry, data.get("habitify"))
    core_read = core_habit_lines(data, profile)
    if core_read is not None:
        keys = core_habits.core_keys(registry)
        return core_read[0], [(n, m) for n, m in missed if n in keys]
    missed_t0, missed_t1 = [], []
    for h_name, meta in missed:
        why = meta.get("why_matthew", "")
        tier = habit_tier(meta)
        if tier == 0:
            missed_t0.append(h_name + (" — " + why[:80] if why else ""))
        elif tier == 1:
            missed_t1.append(h_name)
    habit_ctx = ""
    if missed_t0:
        habit_ctx += "\nMISSED TIER 0 (non-negotiable): " + "; ".join(missed_t0)
    if missed_t1:
        habit_ctx += "\nMISSED TIER 1 (high priority): " + ", ".join(missed_t1[:8])
    return habit_ctx, missed


def tldr_missed(data, profile):
    """`(missed_mvp, missed_context)` for the TL;DR call when a registry exists: the missed core labels and the core
    count line when armed, else every missed tier-0/1 habit with its why."""
    core_read = core_habit_lines(data, profile)
    if core_read is not None:
        return core_read[1], [core_read[0].strip().splitlines()[0]]
    missed_mvp, missed_context = [], []
    for h_name, meta in missed_registry_habits(profile.get("habit_registry", {}), data.get("habitify") or {}):
        if habit_tier(meta) > 1:
            continue
        missed_mvp.append(h_name)
        why = meta.get("why_matthew", "")
        if why:
            missed_context.append(h_name + " (T" + str(habit_tier(meta)) + "): " + why[:60])
    return missed_mvp, missed_context

"""habit_streaks.py — the Tier-0 / Tier-0+1 / per-vice streak scan (#2221).

Lifted out of `daily_brief_lambda` (#1654's shape — that module is baselined by the
module-size guard and may not grow). Pure apart from the `fetch_date` callable the
caller injects, so the whole ADR-104 gap/absence contract is unit-testable offline.

The streak numbers this returns are the most motivating figures in the morning
email and they are published to `public_stats.json`'s platform block, so what a
MISSING reading does to them is a reader-facing decision, not an implementation
detail. See the block comment inside `compute_habit_streaks`.
"""

from datetime import datetime, timedelta

# #2221: a run of missing habitify days longer than this is treated as the end of
# available history rather than as a gap inside a live streak.
STREAK_GAP_TOLERANCE_DAYS = 3


def compute_habit_streaks(profile, yesterday_str, fetch_date):
    """Compute streaks: Tier 0 streak, Tier 0+1 streak, and per-vice streaks."""
    registry = profile.get("habit_registry", {})
    mvp_list = profile.get("mvp_habits", [])

    tier0_habits = []
    tier01_habits = []
    vice_habits = []
    for name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        tier = meta.get("tier", 2)
        if tier == 0:
            tier0_habits.append(name)
            tier01_habits.append(name)
        elif tier == 1:
            tier01_habits.append(name)
        if meta.get("vice", False):
            vice_habits.append(name)

    if not tier0_habits:
        tier0_habits = mvp_list
        tier01_habits = mvp_list

    tier0_streak = 0
    tier01_streak = 0
    t0_broken = False
    t01_broken = False
    vice_streaks = {v: 0 for v in vice_habits}
    vice_broken = {v: False for v in vice_habits}

    # #2221, ADR-104. Three ways this scan turned an ABSENCE into a fact:
    #   1. `if not rec: break` read one missing habitify day (an API blip, a travel
    #      day, a phone left off) as the end of history, so a 40-day vice streak
    #      rendered as 2 — presented as a fact, with no marker that the scan hit a
    #      gap. A gap is now skipped, and the scan stops only after a RUN of missing
    #      days long enough to mean "history exhausted".
    #   2. `habits_map.get(h, 0)` mapped an absent habit key to "not done", so a
    #      habit added to the registry today retroactively destroyed the streak, and
    #      a habit Habitify simply did not return read as a miss. Absent is unknown.
    #   3. a day whose applicable habits are ALL unknown proves nothing either way,
    #      so it is skipped rather than counted as clean.
    # The tier loops are additionally guarded on a NON-EMPTY habit set: with no
    # active tier-0 habits and no mvp_habits — the state right after a reset — the
    # inner all() was vacuously true and the streak grew by one for every day that
    # merely HAD a habitify record. A streak over an empty set is not a streak.
    gap_days = 0
    consecutive_missing = 0

    def _day_verdict(habit_names, is_weekday, habits_map, skip_post_training):
        """(any_reading, all_done) over the habits applicable on this day."""
        any_reading = False
        for h in habit_names:
            meta = registry.get(h, {})
            applicable = meta.get("applicable_days", "daily")
            if applicable == "weekdays" and not is_weekday:
                continue
            if skip_post_training and applicable == "post_training":
                continue
            if h not in habits_map:
                continue  # no reading — not evidence of a miss
            any_reading = True
            done = habits_map.get(h)
            if not (done is not None and float(done) >= 1):
                return True, False
        return any_reading, True

    for i in range(0, 90):
        dt = datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=i)
        date_str = dt.strftime("%Y-%m-%d")
        is_weekday = dt.weekday() < 5
        rec = fetch_date("habitify", date_str)
        if not rec:
            consecutive_missing += 1
            if consecutive_missing > STREAK_GAP_TOLERANCE_DAYS:
                break  # a run this long is the end of history, not a gap
            gap_days += 1
            continue
        consecutive_missing = 0
        habits_map = rec.get("habits", {})

        if tier0_habits and not t0_broken:
            seen_t0, all_t0 = _day_verdict(tier0_habits, is_weekday, habits_map, False)
            if seen_t0:
                if all_t0:
                    tier0_streak += 1
                else:
                    t0_broken = True

        if tier01_habits and not t01_broken:
            seen_t01, all_t01 = _day_verdict(tier01_habits, is_weekday, habits_map, True)
            if seen_t01:
                if all_t01:
                    tier01_streak += 1
                else:
                    t01_broken = True

        for v in vice_habits:
            if vice_broken[v] or v not in habits_map:
                continue
            done = habits_map.get(v)
            if done is not None and float(done) >= 1:
                vice_streaks[v] += 1
            else:
                vice_broken[v] = True

        if (t0_broken or not tier0_habits) and (t01_broken or not tier01_habits) and all(vice_broken.values()):
            break

    return {
        "tier0_streak": tier0_streak,
        "tier01_streak": tier01_streak,
        "vice_streaks": vice_streaks,
        # #2221: the reader is entitled to know the scan crossed a data gap rather
        # than an unbroken run of days.
        "streak_gap_days": gap_days,
    }

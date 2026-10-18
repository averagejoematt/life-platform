"""max_hr.py — the ONE fallback maximum heart rate (#4624 backlog row, 2026-10-18).

Seven readers carried their own default for ``profile.get("max_heart_rate", <n>)`` — 186, 184,
190 — plus a pinned 183 in ``training/training_load.py``. The stored profile
(``USER#matthew / PROFILE#v1 .max_heart_rate``) is 183 (the owner's MEASURED value, read
2026-09-23), so while the profile loads every reader agrees; the defaults only differ on the day
a profile read fails, which is exactly the day nobody is checking. They now share this value, so
a profile miss moves no activity across the Zone 2 line (60-70 % of max) in one reader and not in
another.

Guard: ``tests/test_max_hr_single_default_4624.py`` fails on any new numeric default.
If the measured value changes, change it here and in the profile together.
"""

DEFAULT_MAX_HR = 183


def max_hr_from_profile(profile) -> float:
    """The profile's ``max_heart_rate`` as a float; ``DEFAULT_MAX_HR`` when absent, None or non-positive.

    A value that is PRESENT and unparseable ("one eighty") raises ValueError, as the readers' own
    ``float(...)`` / arithmetic did: a malformed profile must fail the caller's guarded block (which keeps
    the earlier figure) rather than be answered with a guessed number.
    """
    raw = (profile or {}).get("max_heart_rate")
    if raw is None:
        return float(DEFAULT_MAX_HR)
    value = float(raw)
    return value if value > 0 else float(DEFAULT_MAX_HR)

"""habit_registry numeric fields, read as numbers (#5232, class of #4704).

The registry is hand-edited. Twice now a numeric field was stored as a string
(2026-10-04 `target_frequency`; 2026-10-20 `tier`), and each time a reader that compared it
with an int raised. #4704 fixed the scorer only; this module is the shared boundary so no
reader has to: `coerce_registry` normalises a whole registry once where the profile is
read, and `habit_tier` is the accessor for a reader holding a single meta dict.

`coerce_registry` converts only a value that PARSES as a plain number (a str or Decimal holding
one); a bool or garbage value is left raw, so the scorer's #4704 `registry_type_drift` report
still names it. `habit_tier` reads such a value as the default - it never raises, and never
invents a tier for a habit.
"""

from typing import Any

NUMERIC_FIELDS = {"tier": 2, "scoring_weight": 1.0, "target_frequency": 7}


def _parse(raw: Any) -> Any:
    """`raw` as an int/float, or None when it is not a plain number (bool, "weekly", None, nan)."""
    if isinstance(raw, bool):
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return int(n) if n == int(n) else n


def _number(raw: Any, default: Any) -> Any:
    n = _parse(raw)
    return default if n is None else n


def habit_tier(meta: dict | None, default: int = 2) -> int:
    """A registry entry's tier as an int, whatever the registry stored (str, Decimal, float)."""
    n = _number((meta or {}).get("tier", default), default)
    return int(n)


def coerce_registry(registry: Any) -> Any:
    """A copy of `registry` with the numeric fields as numbers. Non-dict input is returned as-is."""
    if not isinstance(registry, dict):
        return registry
    out = {}
    for name, meta in registry.items():
        if isinstance(meta, dict):
            meta = dict(meta)
            for key in NUMERIC_FIELDS:
                n = _parse(meta[key]) if key in meta else None
                if n is not None:  # a non-number stays raw: the scorer's drift report must still see it
                    meta[key] = n
        out[name] = meta
    return out


def coerce_profile(profile: Any) -> Any:
    """`profile` with its habit_registry coerced (the profile read boundary)."""
    if isinstance(profile, dict) and "habit_registry" in profile:
        profile["habit_registry"] = coerce_registry(profile["habit_registry"])
    return profile

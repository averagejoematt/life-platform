"""
character_headline.py — Step 6's headline level, in exact arithmetic (#6066, engine v1.9.0).

The headline Character Level is floor(Σ level·weight / Σ weight), clamped to 1..100, over the pillars the headline
includes (the caller applies the #960 not-instrumented exclusion). Until v1.9.0 that mean was a FLOAT, and at an exact
integer boundary the order of the additions decided the floor: on 2026-11-14 the mean was exactly 20, which summed to
19.999999999999996 in the compute's order (stored 19) and 20.000000000000004 alphabetically (replayed 20).

Owner ruling 2026-11-16, "an exact boundary counts as reached": the mean is computed as an exact rational, each weight
read as the decimal it is configured as, so a mean that is mathematically N+1 reads N+1 in every order. Exactness
promotes nothing genuinely below a boundary — floor of the exact mean is the true floor, for any weights. With the
config's weights in hundredths the mean is K/W for integers K and W ≤ 100, so the largest value under N+1 is
N+1 − 1/W (N + 0.99 over all seven pillars, N + 92/93 over the six instrumented ones) and it floors to N.

ONE function, two callers: character_engine.compute_character_sheet (write time) and
progression_receipts._replay_headline (replay from storage) — which is why write-time and read-time cannot disagree.
Kept beside the engine rather than in it: character_engine.py is at its module-size ceiling (#1665).
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Iterable


def _exact(x: Any) -> Fraction:
    """A number as the exact rational it is CONFIGURED as. A float is read through its shortest repr (0.18 → 9/50, not
    the binary double 0.17999999999999999334…), so a weight means the decimal literal in config/character_sheet.json;
    int, Decimal (a DynamoDB read) and str convert exactly as they are."""
    return Fraction(repr(x)) if isinstance(x, float) else Fraction(x)


def headline_level(entries: Iterable[tuple[Any, Any]]) -> int:
    """floor(Σ level·weight / Σ weight) over (level, weight) pairs, exact, clamped to 1..100; 1 when no weight remains."""
    num = Fraction(0)
    den = Fraction(0)
    for level, weight in entries:
        w = _exact(weight)
        num += _exact(level) * w
        den += w
    if den <= 0:
        return 1
    return max(1, min(100, math.floor(num / den)))

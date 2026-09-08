"""band_reference.py — nearest-weight-band resolution over `training_reference` (#3709).

The question this answers: *what was Matthew doing the last time he weighed
about what he weighs now?* It is deliberately a lookup, not a model.

Why widening is the whole point. On 2026-09-08 he weighed 327.3 lb, which is
above his entire 14-year Withings record — 10 days ever logged at >=320, all of
them in 2026. There is no exact mirror and there may never be one. A lookup that
returns nothing in that case is useless; a lookup that silently returns the
300-309 band is dishonest. `resolve_band` returns the nearest band that clears an
evidence floor **and reports how far away it was**, so every downstream
prescription can carry its own distance.

Shared by the weekly producer (`compute/episode_detect_lambda.py`) and the
read-side consumer (`mcp/tools_benchmark.py`), so the band contract has one
definition rather than two that drift.
"""

from __future__ import annotations

from typing import Any

BAND_WIDTH_LB = 10

# How many 10-lb bands out we are willing to look before declining. Beyond
# ~2 bands (20 lb) the period stops being a comparable bodyweight era.
MAX_WIDENING = 2

# A band under this dwell is returned, but marked — its weekly rates were
# produced by dividing by a window shorter than the rate's own unit.
MIN_DWELL_DAYS = 14


def band_key(weight_lb: float) -> str:
    """The 10-lb band a weight falls in. '327.3' -> '320-329'."""
    low = int(weight_lb // BAND_WIDTH_LB) * BAND_WIDTH_LB
    return f"{low}-{low + BAND_WIDTH_LB - 1}"


def band_low(key: str) -> int:
    return int(str(key).split("-")[0])


def _distance_lb(weight_lb: float, key: str) -> int:
    """Shortest distance from `weight_lb` to the band's own interval, in lb.

    Zero when the weight falls inside the band. Measured to the interval rather
    than to its midpoint so a weight sitting on a band edge is not reported as
    5 lb away from the band that contains it.
    """
    low = band_low(key)
    high = low + BAND_WIDTH_LB - 1
    if low <= weight_lb <= high:
        return 0
    return int(round(low - weight_lb if weight_lb < low else weight_lb - high))


def resolve_band(
    weight_lb: float,
    bands: dict[str, Any] | None,
    max_widening: int = MAX_WIDENING,
    min_weighins: int = 3,
) -> dict[str, Any] | None:
    """Nearest usable band for `weight_lb`, or None when nothing is close enough.

    Returns the band's stored covariates plus:
      band              — the band key actually used
      band_requested    — the band the weight actually falls in
      band_distance_lb  — 0 when exact; >0 when the answer came from elsewhere
      exact             — whether the containing band was the one used
      confidence        — 'low' when dwell or n is thin, else the band's own

    Never invents a band and never averages two of them together: a blended
    answer would have no window and no `n`, which is exactly the property that
    made the v1 table unciteable.
    """
    if not bands or weight_lb is None:
        return None
    target = band_key(weight_lb)

    def _usable(key: str) -> bool:
        b = bands.get(key)
        if not isinstance(b, dict):
            return False
        return int(b.get("n_weighins") or 0) >= min_weighins

    candidates = [target] if _usable(target) else []
    if not candidates:
        # Widen outward one band at a time, preferring the closer side; ties go
        # to the heavier band, which is the more conservative reference when
        # prescribing at a weight above the record.
        for step in range(1, max_widening + 1):
            ring = []
            for direction in (1, -1):
                low = band_low(target) + direction * step * BAND_WIDTH_LB
                key = f"{low}-{low + BAND_WIDTH_LB - 1}"
                if _usable(key):
                    ring.append(key)
            if ring:
                candidates = sorted(ring, key=lambda k: (_distance_lb(weight_lb, k), -band_low(k)))
                break
    if not candidates:
        return None

    key = candidates[0]
    out = dict(bands[key])
    out["band"] = key
    out["band_requested"] = target
    out["band_distance_lb"] = _distance_lb(weight_lb, key)
    out["exact"] = key == target
    if int(out.get("n_days") or 0) < MIN_DWELL_DAYS or int(out.get("n_weighins") or 0) < min_weighins:
        out["confidence"] = "low"
    out.setdefault("confidence", "low")
    return out

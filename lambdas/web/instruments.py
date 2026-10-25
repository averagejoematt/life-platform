"""lambdas/web/instruments.py — the public words for the two instruments on his wrists (#4980).

Whoop and the Apple Watch are both worn, day and night (owner rulings 2026-10-17 (a) and (b)).
Every public surface that names which device a reading came from, or which device answers for
a measure, reads its words from here, so the site says the same thing everywhere and never
names a device the registry does not.

Three things live here, all derived from `ingestion.source_registry` (never restated):

  * `device_of(source, day)` — the device behind one stored reading. The stored Apple Health
    rows carry no device, so the registry's `watch_first_day` facet decides: an Apple Health
    reading on or after it is the Apple Watch; one before it is said as "Apple Health" (an
    earlier device or the phone), never claimed for the watch.
  * `instruments()` — for each measure both devices can report, which one answers today, what
    the other does, and whether the two are combined. Read from `METRIC_TRUTH`.
  * `study(n_nights, min_nights)` — where the dual-wear agreement study (#4974) stands. The
    study has a verdict only once the owner has ruled a combination for resting heart rate
    in `METRIC_TRUTH` (mode or blend moved off the default); until then no surface may state
    that the devices agree or disagree.

Privacy (lambdas/privacy/field_tiers.py): nothing here reads a value. The Apple Watch's resting
heart rate, HRV and sleep are TIER_INTERNAL / owner-only and are never served; this module only
names the instruments and the rule between them.
"""

from __future__ import annotations

from typing import Optional

from common import metric_truth
from ingestion.source_registry import SOURCE_REGISTRY

WATCH = "Apple Watch"
STRAP = "Whoop"
_EARLIER_APPLE = "Apple Health"
_DEVICE_WORDS = {"whoop": STRAP, "garmin": "Garmin watch"}

#: the compared measure whose ruling ends the study (the one #4974 grades first)
STUDY_METRIC = metric_truth.RHR_BPM


def watch_first_day() -> str:
    """The first day the Apple Watch is the sensor behind the apple_health partition (ISO)."""
    return str(SOURCE_REGISTRY["apple_health"]["watch_first_day"]["date"])


def device_of(source: Optional[str], day: Optional[str]) -> Optional[str]:
    """The device behind one stored reading, in public words, or None for no source."""
    if not source:
        return None
    if source == "apple_health":
        return WATCH if str(day or "")[:10] >= watch_first_day() else _EARLIER_APPLE
    return _DEVICE_WORDS.get(source) or source


# One sentence per measure, in the order a reader meets them. Each names the device that
# answers and what the other one does; the rule itself is read from METRIC_TRUTH below.
_MEASURES = (
    (metric_truth.STEPS, "Steps"),
    (metric_truth.VO2_MAX, "VO2 max"),
    (metric_truth.RHR_BPM, "Resting heart rate"),
    (metric_truth.SLEEP_HOURS, "Sleep"),
    (metric_truth.HRV_MS, "Heart-rate variability"),
)


def _answering(source: str, metric: str) -> str:
    """A source in a precedence sentence. Apple Health steps are the phone's and the watch's
    together (HealthKit merges both); the retired Garmin feed is its stored history only."""
    if source == "apple_health":
        return f"the phone and {WATCH}" if metric == metric_truth.STEPS else f"the {WATCH}"
    if source == "garmin":
        return "the Garmin watch's stored history"
    return _DEVICE_WORDS.get(source) or source


def _answers(metric: str, facet: dict) -> str:
    """Which device answers, in the facet's precedence order."""
    first, rest = facet["fallback_order"][0], facet["fallback_order"][1:]
    lead = _answering(first, metric)
    lead = lead[0].upper() + lead[1:]
    if not rest:
        return f"{lead}."
    return f"{lead} first; when it has none, {', then '.join(_answering(s, metric) for s in rest)}."


def _other(metric: str, facet: dict) -> str:
    blend = facet.get("blend", "pending")
    if not facet.get("companions"):
        return ""
    if blend == "never":
        return f"The {WATCH} records its own reading beside it, kept private. The two are never combined: they measure different things."
    if blend == "active":
        return f"The {WATCH} records its own reading, and the two are averaged."  # the owner's ruling after the study
    return (
        f"The {WATCH} records its own reading beside it, kept private. Whether to combine them waits on the comparison of the two devices."
    )


def instruments() -> list[dict]:
    """Which device answers for each measure both can report, and what the other does."""
    out = []
    for metric, name in _MEASURES:
        facet = metric_truth.metric_truth(metric)
        out.append({"measure": name, "answers": _answers(metric, facet), "other": _other(metric, facet), "combined": facet.get("blend")})
    return out


def study_ruled(metric: str = STUDY_METRIC) -> bool:
    """True once the owner has ruled how the two devices combine for `metric` (#4975)."""
    facet = metric_truth.metric_truth(metric)
    return facet.get("mode", "primary") != "primary" or facet.get("blend") == "active"


def study(n_nights: int, min_nights: int) -> dict:
    """Where the agreement study stands: collecting, waiting for its ruling, or ruled."""
    if study_ruled():
        state = "ruled"
    elif n_nights < min_nights:
        state = "collecting"
    else:
        state = "awaiting_ruling"
    return {"state": state, "n_nights": n_nights, "min_nights": min_nights, "verdict_published": state == "ruled"}

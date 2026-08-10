"""strava_population.py — what the Strava distance and elevation populations ARE (#2331, ADR-104).

Strava's API never omits `distance` or `total_elevation_gain`: it sends `0.0` for a
bench-press session exactly as it sends `0.0` for a genuinely flat run. `_normalize`
used to write `... if activity.get("distance") else None`, so every one of those zeros
was stored as *absent*. That is the ADR-104 defect — but the naive repair (store every
zero) is a second, worse one: it would tell the reader that 758 gym `Workout` sessions
each covered a measured 0.0 miles, and every "top 1% distance ever" percentile is
computed over exactly that denominator (`ingestion/enrichment_lambda.build_percentile_pools`,
`mcp/tools_data.tool_search_activities`).

So the question is population membership, and it has TWO parts. A stored `0` is only
honest when both hold:

1. **The metric is a measurement of this activity type.** Distance means something for a
   Run; it means nothing for WeightTraining, where `0.0` is schema filler. The per-type
   decision is `_DECISIONS` below — one explicit (distance, elevation) verdict per type.
   The type set is not hand-typed: it is checked against the machine-generated census in
   ``config/strava_activity_type_census.json`` (see ``scripts/strava_type_census.py``) by
   ``tests/test_strava_population.py``, so an undecided observed type is a red test.

2. **The activity carried a channel that could measure it.** This is what the archive
   forced. Of the 650 zero-distance activities on distance-bearing types, 648 are
   `trainer=True` — WHOOP-synced indoor sessions with no GPS (372 Walks, 159 Rides).
   Those are walks that plainly covered ground; their distance was *not measured*, so
   `0` would be a fabricated measurement, not a corrected one. `manual=True` records are
   the same story from the other direction: a hand-logged activity's `0` is an unfilled
   field. Both stay absent.

The net effect on the live archive is small and that is the point: measured against the
2026-08-10 archive (1,207 days / 2,769 activities), 2 distance values and 6 elevation
values — all pre-2024 outdoor GPS activities, e.g. flat Apple Watch runs in 2021 — stop
reading as unmeasured. The 1,237 gym rows and the 650 indoor/manual rows keep the absence
they should have had all along. See `scripts/reconcile_strava_measured_zero.py`.

Both public helpers take the metres value explicitly so the same rule serves the two
call sites with different key names: the ingest path passes the API's `distance` /
`total_elevation_gain`, the reconciliation script passes the stored `distance_meters` /
`total_elevation_gain_meters`.
"""

from typing import Any

_METERS_TO_MILES = 0.000621371
_METERS_TO_FEET = 3.28084

# Per Strava activity type: (distance is a measurement, elevation is a measurement).
#
# In-population  = the athlete's displacement / vertical gain IS what the activity does,
#                  so a measured 0 is a real data point at the bottom of the distribution.
# Out-of-population = the metric is not a property of the activity; Strava's 0.0 is filler.
#
# Water sports are in the distance population but out of the elevation one — a swim or a
# sail has a real distance and no meaningful vertical gain. Fixed-machine cardio
# (Elliptical, StairStepper) is out of both: Strava reports 0.0 for machine sessions
# regardless of what the machine's own console showed, so its zeros carry no measurement.
# VirtualRide stays in both: Zwift-style platforms report simulated distance AND grade,
# and the archive's 159 virtual rides all carry non-zero values for both.
_DECISIONS: dict[str, tuple[bool, bool]] = {
    # ── land locomotion: distance ✔ elevation ✔ ────────────────────────────────
    "Walk": (True, True),
    "Run": (True, True),
    "TrailRun": (True, True),
    "Hike": (True, True),
    "Ride": (True, True),
    "VirtualRide": (True, True),
    "VirtualRun": (True, True),
    "GravelRide": (True, True),
    "MountainBikeRide": (True, True),
    "EBikeRide": (True, True),
    "EMountainBikeRide": (True, True),
    "Handcycle": (True, True),
    "Velomobile": (True, True),
    "Wheelchair": (True, True),
    "InlineSkate": (True, True),
    "RollerSki": (True, True),
    "Skateboard": (True, True),
    "Snowshoe": (True, True),
    "AlpineSki": (True, True),
    "BackcountrySki": (True, True),
    "NordicSki": (True, True),
    "Snowboard": (True, True),
    # ── water locomotion: distance ✔ elevation ✘ ───────────────────────────────
    "Swim": (True, False),
    "Sail": (True, False),
    "Rowing": (True, False),
    "VirtualRow": (True, False),
    "Canoeing": (True, False),
    "Kayaking": (True, False),
    "StandUpPaddling": (True, False),
    "Surfing": (True, False),
    "Windsurf": (True, False),
    "Kitesurf": (True, False),
    "IceSkate": (True, False),
    # ── gym / court / studio / fixed machine: neither is a measurement ─────────
    "Workout": (False, False),
    "WeightTraining": (False, False),
    "HighIntensityIntervalTraining": (False, False),
    "Crossfit": (False, False),
    "Yoga": (False, False),
    "Pilates": (False, False),
    "Elliptical": (False, False),
    "StairStepper": (False, False),
    "Golf": (False, False),
    "Soccer": (False, False),
    "Tennis": (False, False),
    "Pickleball": (False, False),
    "Squash": (False, False),
    "Badminton": (False, False),
    "TableTennis": (False, False),
    "Racquetball": (False, False),
    "RockClimbing": (False, False),
    "Hunt": (False, False),
    "Skiing": (False, False),
}

#: Types whose ``distance`` is a measurement of the activity.
DISTANCE_POPULATION = frozenset(t for t, (d, _e) in _DECISIONS.items() if d)
#: Types whose ``total_elevation_gain`` is a measurement of the activity.
ELEVATION_POPULATION = frozenset(t for t, (_d, e) in _DECISIONS.items() if e)

#: Human-readable population statements for any surface publishing an aggregate or
#: percentile over these metrics (acceptance criterion 3 of #2331).
DISTANCE_POPULATION_LABEL = (
    "distance-bearing Strava activities recorded with a distance channel (GPS/device, not indoor-trainer or manually entered)"
)
ELEVATION_POPULATION_LABEL = (
    "land-locomotion Strava activities recorded with an elevation channel (GPS/device, not indoor-trainer or manually entered)"
)


def activity_type(activity: dict) -> str:
    """The type token to classify by. `sport_type` is Strava's modern field; `type` is legacy."""
    return str(activity.get("sport_type") or activity.get("type") or "").strip()


def is_decided(activity_type_token: str) -> bool:
    """True when this type carries an explicit population verdict (used by the census test)."""
    return activity_type_token in _DECISIONS


def has_measurement_channel(activity: dict) -> bool:
    """Could this record have measured displacement at all?

    `trainer` is Strava's indoor/stationary flag and is what every WHOOP-synced session
    carries — no GPS, so no distance and no barometric gain. `manual` means a human typed
    the activity in, and an untyped field arrives as 0. In both cases a zero is the
    absence of a measurement, so it must not be stored as one. An activity that *did*
    report a non-zero value never reaches this gate.
    """
    return not activity.get("trainer") and not activity.get("manual")


def _resolve(activity: dict, meters: Any, population: frozenset, factor: float, ndigits: int) -> float | None:
    if meters is None:
        return None
    value = float(meters)
    if value != 0:
        return round(value * factor, ndigits)
    # A zero. Store it only if it is a measurement of a metric this activity has.
    if activity_type(activity) not in population:
        return None
    if not has_measurement_channel(activity):
        return None
    return 0.0


def distance_miles(activity: dict, meters: Any) -> float | None:
    """Miles, or None when distance is not a measured property of this activity."""
    return _resolve(activity, meters, DISTANCE_POPULATION, _METERS_TO_MILES, 2)


def elevation_gain_feet(activity: dict, meters: Any) -> float | None:
    """Feet of gain, or None when elevation is not a measured property of this activity."""
    return _resolve(activity, meters, ELEVATION_POPULATION, _METERS_TO_FEET, 1)

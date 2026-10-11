"""legacy_workouts.py — THE one reader of the retired per-day training shape (#4636).

Strength training has been stored in two shapes:

* **Live (Hevy, ADR-060):** one DynamoDB item per workout, ``sk = DATE#<d>#WORKOUT#<uuid>``,
  exercises at the top level, set weights in ``weight_kg``, a native ``workout_uid``.
* **Retired (per-day aggregate):** one item per DAY carrying a nested ``workouts`` list
  (``item["workouts"]``, or ``item["data"]["workouts"]`` on the pre-2026-05-26 Hevy
  aggregates), set weights in ``weight_lbs``. The ``macrofactor_workouts`` partition is
  this shape and has had no writer since its last row on 2026-03-07; the Hevy partition's
  own per-day aggregates were tombstoned when the per-workout schema superseded them.

Three readers kept reading the retired shape after the live source moved (#4636): the
monthly digest counted 0 of 24 September sessions, the MCP periodization volume and
muscle-group recency were empty for everything after March, and ``get_workouts`` returned
the same session twice on 421 days. ``tests/test_retired_training_shapes_4636.py`` now
fails on any read of the ``macrofactor_workouts`` partition or of a row's nested
``workouts`` list outside this module and the callers it names.
"""

from __future__ import annotations

from typing import Any

# The retired per-day partition. Kept as a name here so the readers that still need the
# archive (the MCP legacy bridge, the vacation-fund mileage, the routine counters) import
# it from the one place the guard test watches, instead of re-typing the literal.
LEGACY_WORKOUTS_PARTITION = "macrofactor_workouts"


def day_workouts(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The nested per-day ``workouts`` list of one retired-shape row, dicts only.

    Reads ``item["data"]["workouts"]`` first (the pre-2026-05-26 Hevy aggregates) and then
    ``item["workouts"]`` (``macrofactor_workouts``). A live per-workout row has neither and
    returns ``[]`` — this function never turns a live row into a legacy one.
    """
    if not isinstance(item, dict):
        return []
    data = item.get("data")
    nested = data.get("workouts") if isinstance(data, dict) else None
    workouts = nested or item.get("workouts") or []
    return [w for w in workouts if isinstance(w, dict)]

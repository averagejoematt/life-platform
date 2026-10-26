"""lambdas/common/hevy_schema.py — the ONE spelling for the stored Hevy set-duration
field (#4158).

Lives in ``common/``, not ``training/``, on purpose: ``lambdas/health/tdee.py`` (the
calorie side) is asserted by
``tests/test_training_load_worked_set_4075.py::test_the_energy_targets_load_input_is_the_stored_tsb_not_a_recompute``
to import NOTHING from the ``training`` package — the calorie target reads no load
model — so this constant could not live there without breaking that boundary. It is
also pure (no boto3, no I/O, no clock reads), so importing it does not pull the AWS SDK
into ``tdee.py``, which is deliberately dependency-free per ADR-152.

``lambdas/training/hevy_common.py`` (the ingestion writer, ``_normalize_set``) is the
schema owner: every Hevy set row it writes to DynamoDB carries its measured duration
under ``SET_DURATION_FIELD``. That is deliberately NOT the raw Hevy API wire field
(``duration_seconds``) — normalization renames it at ingest, and
``training.training_load.hevy_session_load`` keeps a documented, tested fallback to
the raw wire spelling for a payload that reaches it pre-normalization.

**#4158:** ``health.tdee.worked_set_seconds`` read ``duration_seconds`` only — a key no
stored Hevy set row has ever carried — so ``sets_with_logged_duration`` read 0 on every
day replayed 2026-09-08 -> 09-22, and Hevy-logged cardio (cycling/treadmill/walking,
which carries a measured ``duration_sec`` but no ``reps``) earned zero exercise energy
while every unlogged rep set was still charged the flat 40 s assumption. Both readers of
the stored field now derive it from here rather than each spelling it independently.
"""

from __future__ import annotations

from decimal import Decimal

#: The key every NORMALIZED Hevy set row carries for its measured duration
#: (see ``hevy_common._normalize_set``). Import this — never re-type the literal.
SET_DURATION_FIELD = "duration_sec"

#: #5373: the Hevy exercise type whose distance field is the owner's STEP COUNT — a loaded distance (the farmers walk, the
#: suitcase carry, the dumbbell walking lunge). The gym has no distance markings, so on these he counts steps and types the
#: count into the yards field. `training.logging_conventions` writes `distance_unit_convention: steps` onto every catalog
#: entry of this type; the rule lives here because `health.tdee` (which may import nothing from `training`) reads it too.
STEP_COUNT_HEVY_TYPES = frozenset({"short_distance_weight"})

_WARMUP_TYPES = frozenset({"warmup", "warm_up", "warm-up"})


def _num(v: object) -> float:
    try:
        return float(v) if isinstance(v, (int, float, str, Decimal)) and v != "" else 0.0  # DynamoDB hands back Decimal
    except (TypeError, ValueError):
        return 0.0


def loaded_distance_shape(sets: object) -> bool:
    """#5373: True when an exercise's sets have the shape of `STEP_COUNT_HEVY_TYPES` — a working set carrying a load AND a
    distance, and no set carrying reps. Pure. That shape is the type: on such an exercise the distance field is a step count,
    never metres. (A timed cardio block has a distance but no load; a rep set has reps.)"""
    work = [
        s
        for s in (sets if isinstance(sets, (list, tuple)) else [])
        if isinstance(s, dict) and str(s.get("set_type") or s.get("type") or "normal").strip().lower() not in _WARMUP_TYPES
    ]
    if not work or any(_num(s.get("reps")) > 0 for s in work):
        return False
    return any(
        (_num(s.get("distance_m")) or _num(s.get("distance_meters"))) > 0
        and (_num(s.get("weight_kg")) > 0 or _num(s.get("weight_lbs")) > 0)
        for s in work
    )

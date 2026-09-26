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

#: The key every NORMALIZED Hevy set row carries for its measured duration
#: (see ``hevy_common._normalize_set``). Import this — never re-type the literal.
SET_DURATION_FIELD = "duration_sec"

"""tests/test_whoop_reconciler_frame_3677.py — #3677, the half of #3666 that measurement
turned around.

WHAT #3666 BELIEVED, AND WHAT THE STORE SAYS
--------------------------------------------
#3666 derived the set of ingestion `DATE#` writers and left two members open. The second
was this one, entered as: whoop's gap reconciler computes its expected keys with
``_utc_day(sleep["start"])`` while "the real writes go through ingestion_framework in the
Pacific frame", so the two frames must disagree for the evening PT hours — same class as
the habitify bug, own blast radius, unmeasured.

The blast radius was measured before anything was changed, and it is zero, because the
premise is wrong. The framework enumerates Pacific date LABELS; whoop's ``fetch_day``
turns each label into a UTC WINDOW (``{d}T00:00:00.000Z`` .. ``{d+1}T00:00:00.000Z``) and
``transform`` files whatever that window returns under the same label. So a whoop
``DATE#{d}`` names the UTC day ``d`` — which is what TD-19's own cross-source matrix
recorded in 2026-05 ("Whoop today, 9pm PT -> DATE#(next day)") before #3666 re-derived a
different belief from the framework's stamp.

Measured read-only against the live partition on 2026-09-19 (`USER#matthew#SOURCE#whoop`,
projecting `sk`, `sleep_start`, `start_time`; 4,858 rows):

    straddling rows (UTC day != Pacific day of start, i.e. 17:00 PT..midnight)
        daily aggregates   1,649   keyed by UTC day 1,649   keyed by Pacific day 0
        workout records      600   keyed by UTC day   600   keyed by Pacific day 0
        range 2020-03-23 .. 2026-09-19

and the live instrument agrees: `LifePlatform/IngestReconciliation::MissingActivityCount
{Source=whoop}` = 0 on 30 of 30 consecutive daily runs, 2026-08-19..09-17. A frame
disagreement cannot produce that — a main sleep starts after 17:00 PT nearly every night,
so a Pacific-framed expected set would have reported a phantom gap most days.

WHAT THIS FILE IS FOR
---------------------
The correction is one comment away from being re-broken: the next reader to notice a
`_utc_day` next to a platform whose keys are "Pacific days by default" has every reason to
re-file the same bug and flip it. These tests fail if they do. They pin the DIRECTION
against a straddling instant — a sleep beginning 2026-09-06 23:30 PT, i.e. 09-07T06:30Z —
by driving the real ``_records_missing_from_store``:

  * with the store holding the UTC key, nothing is missing  (the frame agrees)
  * with the store holding the PACIFIC key instead, the record IS reported missing
    (which is precisely the phantom gap a re-frame would mint every night)

They assert behaviour through the reconciler's own function, not by reading `_utc_day`'s
source, so a re-frame implemented anywhere in that path is caught.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import whoop_lambda as whoop  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")

# The straddling instant, stated once, in both frames. 23:30 on a Pacific Saturday is
# 06:30 the next morning in UTC — the shape that is true of nearly every night's sleep,
# which is why getting the frame wrong here is not an edge case.
SLEEP_START_UTC = "2026-09-07T06:30:00.000Z"
PACIFIC_DAY = "2026-09-06"
UTC_DAY = "2026-09-07"

SCORED_SLEEP = {"id": "s-1", "start": SLEEP_START_UTC, "nap": False, "score_state": "SCORED"}
EVENING_WORKOUT = {"id": "w-1", "start": SLEEP_START_UTC}


def test_the_fixture_really_straddles_the_boundary():
    """The control. If this instant ever stopped straddling — a bad constant, a DST edit
    — every assertion below would pass for the wrong reason, agreeing with both frames at
    once. A comparison gate is blind when both sides agree."""
    t = datetime.fromisoformat(SLEEP_START_UTC.replace("Z", "+00:00"))
    assert t.astimezone(timezone.utc).strftime("%Y-%m-%d") == UTC_DAY
    assert t.astimezone(PACIFIC).strftime("%Y-%m-%d") == PACIFIC_DAY
    assert UTC_DAY != PACIFIC_DAY
    assert t.astimezone(PACIFIC).hour >= 17, "the boundary only bites from 17:00 PT; this fixture must be in that window"


def test_an_evening_sleep_is_expected_under_the_UTC_day_which_is_what_the_store_holds():
    """The measurement, as a test: 1,649 of 1,649 straddling daily rows are keyed by the
    UTC day. So the store holding DATE#2026-09-07 for a sleep begun 23:30 PT on the 6th is
    the NORMAL case, and the reconciler must call it present."""
    missing = whoop._records_missing_from_store(
        sleeps=[SCORED_SLEEP],
        workouts=[],
        stored_sks={f"DATE#{UTC_DAY}"},
        stored_workout_starts=[],
    )
    assert missing == [], f"the reconciler reported a gap for a record the store actually holds: {missing}"


def test_re_framing_the_reconciler_to_pacific_would_mint_a_phantom_gap():
    """The must-fail direction, and the reason this file exists. If the expected set is
    ever re-derived in the Pacific frame, THIS is what the store looks like to it — the
    UTC key it is holding stops matching — and MissingActivityCount goes to 1 most nights
    on records that were never missing."""
    missing = whoop._records_missing_from_store(
        sleeps=[SCORED_SLEEP],
        workouts=[],
        stored_sks={f"DATE#{PACIFIC_DAY}"},
        stored_workout_starts=[],
    )
    assert [m["sk"] for m in missing] == [f"DATE#{UTC_DAY}"], (
        "a Pacific-keyed store is NOT what whoop has (measured: 0 of 2,249 straddling rows), and the "
        f"reconciler must keep expecting the UTC key. Got: {missing}"
    )


def test_a_workout_sub_record_uses_the_same_frame_as_the_daily_key():
    """600 straddling workout rows, all UTC-keyed. The sub-record key must not drift from
    the daily one — they are built by the same helper and stored by the same loop."""
    present = whoop._records_missing_from_store(
        sleeps=[],
        workouts=[EVENING_WORKOUT],
        stored_sks={f"DATE#{UTC_DAY}#WORKOUT#w-1"},
        stored_workout_starts=[],
    )
    assert present == [], f"an evening workout stored on its UTC day was reported missing: {present}"

    pacific_keyed = whoop._records_missing_from_store(
        sleeps=[],
        workouts=[EVENING_WORKOUT],
        stored_sks={f"DATE#{PACIFIC_DAY}#WORKOUT#w-1"},
        stored_workout_starts=[],
    )
    assert [m["date"] for m in pacific_keyed] == [UTC_DAY], f"the workout key's frame moved: {pacific_keyed}"


def test_a_real_gap_is_still_reported():
    """The instrument must still be able to fail for the RIGHT reason. A guard that only
    ever says 'present' is the #3666 class wearing a different hat."""
    missing = whoop._records_missing_from_store(
        sleeps=[SCORED_SLEEP],
        workouts=[EVENING_WORKOUT],
        stored_sks=set(),
        stored_workout_starts=[],
    )
    kinds = sorted(m["kind"] for m in missing)
    assert kinds == ["daily", "workout"], f"an empty store must surface both records as gaps, got {missing}"

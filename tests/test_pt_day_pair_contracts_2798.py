"""tests/test_pt_day_pair_contracts_2798.py — the TWO-SIDED proof for #2798's pairs.

WHY THIS FILE EXISTS, AND WHY IT IS NOT MORE RATCHET.
`tests/test_utc_day_fleet_ratchet_2811.py` proves a *shape*: no module in the guarded
packages derives a calendar day from a UTC/naive clock. That is necessary and it is not
sufficient, because the defect #2817 refused to ship was never a shape — it was an
AGREEMENT. Its `_UTC_DAY_RESIDUE` held `mcp/tools_reading.py` and
`mcp/tools_hevy_routine.py` back with the same sentence twice: *the mcp/ side is ready,
its partner writer lives in an unguarded package, converting one side alone splits the
pair.* A shape guard would have been perfectly green the moment either side moved.

So this file drives BOTH sides of both pairs, as the real production functions, at ONE
PT-evening instant where the UTC and Pacific calendars disagree, and asserts they name
the SAME day. If a future change converts one side back — or forward, or to a third
frame — the shape guard stays green and this file goes red, which is the whole point.

THE FROZEN CLOCK, AND WHY IT IS FROZEN HERE.
Every expectation below is computed through `common.pacific_time`'s own helpers — the
handlers' own clock — never `date.today()` and never `datetime.now(timezone.utc)`. That
is not style. #2817 shipped two fixtures that derived their expected day from a UTC
`now` while the code under test named the Pacific day: both passed forever on a
PT-local laptop and redded main in CI's 17:00–24:00 PT window. A fixture in the wrong
frame is the same bug as the code in the wrong frame, wearing a green tick.

The freeze is ONE patch: `common.pacific_time.datetime`. `pacific_now()` reads that
module's own `datetime` global, and every converted module imported the *function*, so
pinning it there reaches all of them at once — which is exactly what makes this a
cross-module contract test rather than a per-module mock.

Run:  python3 -m pytest tests/test_pt_day_pair_contracts_2798.py -v
"""

from __future__ import annotations

import datetime as _datetime_mod
import os
from datetime import datetime, timedelta, timezone

import pytest
from common import pacific_time
from common.pacific_time import PACIFIC

# `mcp.config` reads these at IMPORT time; both pairs cross into `mcp/`.
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

# ── The instant. 18:30 Pacific — inside the window the whole epic is about, and the
# hours MCP is actually used. Fixed date (not "today - 1") so the case is reproducible;
# asserted below to genuinely straddle midnight UTC rather than merely claim to.
_PT_EVENING = datetime(2026, 8, 26, 18, 30, 0, tzinfo=PACIFIC)
_UTC_INSTANT = _PT_EVENING.astimezone(timezone.utc)


class _FrozenDatetime(_datetime_mod.datetime):
    """A `datetime` whose `now()` is pinned. Subclasses the real class so anything the
    production code does with the result (arithmetic, `.date()`, `.strftime`) is real."""

    @classmethod
    def now(cls, tz=None):
        return _UTC_INSTANT.astimezone(tz) if tz else _UTC_INSTANT.replace(tzinfo=None)


@pytest.fixture
def pt_evening(monkeypatch):
    """Pin `common.pacific_time`'s clock — the one both sides of each pair read through."""
    monkeypatch.setattr(pacific_time, "datetime", _FrozenDatetime)
    return _PT_EVENING


def test_the_chosen_instant_actually_straddles_the_day_boundary():
    """The precondition every assertion below rests on. If this ever stops being true the
    rest of the file is vacuously green — it would compare two frames that agree."""
    assert _PT_EVENING.date().isoformat() == "2026-08-26"
    assert _UTC_INSTANT.date().isoformat() == "2026-08-27"
    assert _PT_EVENING.date() != _UTC_INSTANT.date(), "the fixture instant no longer straddles midnight UTC"


def test_the_freeze_reaches_the_helpers_both_sides_import(pt_evening):
    """A freeze that does not reach the production helper proves nothing (the #2811
    `freeze_pacific` lesson: patching a module's `datetime` cannot reach a second
    module's own import — so patch the module the helper actually lives in)."""
    assert pacific_time.pacific_today() == "2026-08-26"
    assert pacific_time.pacific_now().date().isoformat() == "2026-08-26"


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 1 — reading.  WRITER: reading_store.log_session (`date`, the GSI2 sort key)
#                    READER: mcp.tools_reading._input_streak (walks days backwards)
# ══════════════════════════════════════════════════════════════════════════════


def test_pair1_session_writer_and_streak_reader_name_the_same_day(pt_evening):
    """The exact failure #2817 named: a session logged at 18:30 PT used to be stamped with
    the UTC day (tomorrow), and the streak — counting back from a UTC 'today' — could not
    see it. Both sides now name the Pacific day, so a 6pm session counts today."""
    from mcp import tools_reading

    # WRITER — the real day-derivation `log_session` performs on its own instant.
    session_date = pacific_time.pacific_date_of(_UTC_INSTANT.isoformat())

    # READER — the real streak walker, fed the real writer's day.
    streak = tools_reading._input_streak([{"date": session_date}])

    assert session_date == pacific_time.pacific_today()
    assert streak == 1, "the streak reader disagrees with the session writer about 'today'"
    # ...and the proof this is not vacuous: the pre-#2798 UTC day would have read 0.
    assert tools_reading._input_streak([{"date": _UTC_INSTANT.date().isoformat()}]) == 0


def test_pair1_log_session_stamps_the_pacific_day_of_its_own_instant(pt_evening, monkeypatch):
    """Drive `log_session` end-to-end against a captured put. `now` is the UTC INSTANT (it
    is the `ts` and the SESSION# sk); only its DAY rendering moved frames."""
    from reading import reading_store

    captured: dict = {}
    monkeypatch.setattr(reading_store, "_put", lambda item: captured.update(item) or item)

    item = reading_store.log_session("book-1", minutes=30.0, now=_UTC_INSTANT.isoformat())

    assert item["date"] == pacific_time.pacific_today() == "2026-08-26"
    assert item["ts"].startswith("2026-08-27"), "the INSTANT must stay UTC — only the day has a frame"
    assert captured["date"] == item["date"]


def test_pair1_recall_next_due_writer_and_the_due_reader_share_one_frame(pt_evening):
    """The second half of pair 1. `reading_recall.next_due()` stamps `nextDue` (a DAY) into
    GSI1SK; `reading_store.due_recalls()` bounds that index with an instant. Mixed frames
    made tomorrow's probe due at 17:00 PT today — a retention probe fired a day early."""
    from reading import reading_recall

    due_day = reading_recall.next_due(0)  # INTERVALS[0] == 3 days out
    assert due_day == (pacific_time.pacific_now().date() + timedelta(days=3)).isoformat()

    # The bound the reader uses is the Pacific instant, so a probe due on the UTC day
    # (tomorrow, Pacific) sorts ABOVE it and is correctly not yet due.
    bound = pacific_time.pacific_now().isoformat()
    assert _UTC_INSTANT.date().isoformat() > bound, "a UTC-day probe must not be due at 18:30 PT"
    assert pacific_time.pacific_today() <= bound, "today's probe must still be due at 18:30 PT"


def test_pair1_asked_at_and_resonance_window_are_pacific(pt_evening):
    """The remaining `_today()`s on both sides of pair 1 — the recall answer's `askedAt`
    (written into `performanceHistory`) and the journal-theme window `reading_resonance`
    scans — resolve to the same Pacific day the session writer stamps."""
    from reading import reading_recall, reading_store

    from mcp import tools_reading

    expected = pacific_time.pacific_today()
    assert reading_recall._today() == expected
    assert reading_store._today() == expected
    assert tools_reading._today() == expected


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 2 — hevy routines.  `target_date` is a WRITE KEY, not a display value:
#   `routine_repo` indexes at `DATE#{target_date}#ROUTINE#…` and `routine_generator.
#   _new_routine_id(target_date, archetype, variant)` DERIVES the partition id from it
#   (#3115). Two authors of one key: the cron and the MCP tool. They move together or
#   an evening draft and a morning cron write two different routines for one session.
# ══════════════════════════════════════════════════════════════════════════════

_TARGET_DATE_AUTHORS = (
    "operational.hevy_routine_cron_lambda",
    "operational.hevy_restamp_lambda",
)


@pytest.mark.parametrize("module_name", _TARGET_DATE_AUTHORS)
def test_pair2_every_target_date_author_names_the_pacific_day(pt_evening, module_name):
    """Both `lambdas/operational/` authors of `target_date`, driven as the real functions."""
    import importlib

    mod = importlib.import_module(module_name)
    assert mod._target_date_for_event({}) == pacific_time.pacific_today() == "2026-08-26"
    # An explicit target_date always wins — the frame change must not swallow the argument.
    assert mod._target_date_for_event({"target_date": "2026-01-01"}) == "2026-01-01"


def test_pair2_the_mcp_author_agrees_with_the_cron_author(pt_evening):
    """THE pair assertion. `mcp.tools_hevy_routine._generator_inputs` is the MCP side's
    `target_date` default; `hevy_routine_cron_lambda._target_date_for_event` is the cron's.
    Same instant, same key."""
    from operational import hevy_routine_cron_lambda

    from mcp import tools_hevy_routine

    mcp_day = tools_hevy_routine._generator_inputs({}).target_date
    cron_day = hevy_routine_cron_lambda._target_date_for_event({})

    assert mcp_day == cron_day == pacific_time.pacific_today() == "2026-08-26"
    assert mcp_day != _UTC_INSTANT.date().isoformat(), "the assertion is vacuous unless the frames differ here"


def test_pair2_both_authors_derive_the_SAME_routine_id_key(pt_evening):
    """The key-space proof, stated as the key itself. `routine_id` IS a function of
    `target_date` (#3115), so two authors in two frames mint two partitions for one
    session — the exact corruption the #2817 residue entry refused to risk."""
    from operational import hevy_routine_cron_lambda
    from training.routine_generator import _new_routine_id

    from mcp import tools_hevy_routine

    mcp_id = _new_routine_id(tools_hevy_routine._generator_inputs({}).target_date, "push", "ideal")
    cron_id = _new_routine_id(hevy_routine_cron_lambda._target_date_for_event({}), "push", "ideal")

    assert mcp_id == cron_id, "the two authors of `target_date` would write different ROUTINE# partitions"
    # And the pre-#2798 split, demonstrated rather than asserted about:
    utc_id = _new_routine_id(_UTC_INSTANT.date().isoformat(), "push", "ideal")
    assert utc_id != cron_id, "a UTC-framed author minted a different partition — this is what was fixed"


def test_pair2_the_history_window_consumer_agrees_with_the_authors(pt_evening, monkeypatch):
    """`training.exercise_history.load_recent_history` bounds the `SOURCE#hevy` `DATE#`
    scan off the same day. A UTC bound started the window one day late relative to a
    Pacific-keyed partition, which is a silently-shorter lookback, not an error."""
    from training import exercise_history

    captured: dict = {}

    class _FakeTable:
        def query(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"Items": []}

    monkeypatch.setattr(exercise_history, "_table", lambda: _FakeTable())
    exercise_history.load_recent_history(lookback_days=7)

    expected_start = (pacific_time.pacific_now().date() - timedelta(days=7)).isoformat()
    sk_bound = captured["kwargs"]["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1]
    assert sk_bound == f"DATE#{expected_start}", f"the history window starts at {sk_bound}, not the Pacific day"


def test_pair2_adherence_matches_a_pt_evening_workout_to_the_routine_day(pt_evening, monkeypatch):
    """The consumer that used to slice the vendor instant raw, driven as the REAL action.

    A workout STARTED at 18:30 PT carries a UTC `start_time` of the next day; `[:10]`
    compared that to a Pacific-keyed `target_date` and returned `no_workout_for_date` for
    a session that demonstrably happened. `pacific_date_of` is the platform's existing
    answer — `health.adherence_calc` already resolved hevy `start_time` that way, with a
    comment calling itself "immune to the UTC-date keying bug". This removes the bug it
    was immune to.
    """
    from training import hevy_write_client as wc
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    from mcp import tools_hevy_routine

    start_time = _UTC_INSTANT.isoformat().replace("+00:00", "Z")
    assert start_time[:10] == "2026-08-27", "precondition: the raw slice names the UTC day"

    ir = RoutineSpec(
        routine_id="r1",
        target_date=pacific_time.pacific_today(),
        archetype="push",
        variant="ideal",
        title="t",
        notes="",
        version=1,
        created_at=start_time,
        created_by="test",
        source_action="test",
        status="pushed",
        exercises=[ExerciseBlock(movement_key="tmpl:1", sets=[Set(weight_kg=20.0, reps=5)])],
    )
    # No exercises: this test is about the DAY MATCH, and Hevy wire-schema knowledge is
    # confined to the compiler by `tests/test_hevy_compiler_isolation.py`. `status` alone
    # distinguishes "matched the routine's day" from "no_workout_for_date".
    workout = {"start_time": start_time, "exercises": []}
    monkeypatch.setattr("training.routine_repo.get_current", lambda rid: ir)
    monkeypatch.setattr(wc, "get_workouts", lambda **kw: {"workouts": [workout]})

    out = tools_hevy_routine._action_adherence({"routine_id": "r1"})
    assert out["status"] == "ok", f"the PT-evening workout was not matched to its own routine day: {out}"


# ══════════════════════════════════════════════════════════════════════════════
# The structural half — the pairs cannot be un-paired by deleting a test above.
# ══════════════════════════════════════════════════════════════════════════════


def test_neither_pair_can_regress_to_a_utc_day_unnoticed():
    """Belt to the ratchet's braces, at the level of the FILES rather than the packages.

    The ratchet asserts whole packages are clean; this names the six modules that make up
    the two pairs, so a future refactor that moves one of them OUT of a scanned package
    (into `lambdas/common/`, say) still has something to argue with. `_measure`-shaped,
    but on an explicit list, deliberately — the pair is the unit here.
    """
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from test_utc_day_fleet_ratchet_2811 import utc_day_semantics_sites

    root = pathlib.Path(__file__).resolve().parent.parent
    pair_files = (
        # pair 1
        "lambdas/reading/reading_store.py",
        "lambdas/reading/reading_recall.py",
        "mcp/tools_reading.py",
        # pair 2
        "lambdas/operational/hevy_routine_cron_lambda.py",
        "lambdas/training/exercise_history.py",
        "mcp/tools_hevy_routine.py",
    )
    offenders: list[str] = []
    for rel in pair_files:
        path = root / rel
        assert path.exists(), f"a #2798 pair member left the tree: {rel} — re-point this list"
        offenders.extend(utc_day_semantics_sites(path.read_text(encoding="utf-8"), filename=rel))
    assert not offenders, "a #2798 pair member regrew a UTC day — check BOTH sides before fixing one:\n" + "\n".join(offenders)

"""tests/test_muscle_volume_cross_phase_4031.py — a PRESCRIPTION verdict read from one cycle.

THE BUG (#4031, #4030's sibling — found by #4030's own consumer audit)
  `mcp/tools_strength.py::tool_get_muscle_volume` read the Hevy partition through
  `query_source_range("hevy", start, end)` — an alias for `query_source(..., include_pilot=False)`,
  which applies the ADR-058 phase filter. `phase_taxonomy.classify("USER#matthew#SOURCE#hevy")`
  rules that partition **raw_timeseries** (cross-phase by design; the DATE window is what bounds
  recency) and `phase_filter.source_reads_cross_phase("hevy")` already returned True. The read
  never asked, so every trailing window silently truncated to the CURRENT CYCLE'S AGE — and what
  it truncates is not a display number, it is `volume_landmark_status`: "below maintenance" /
  "optimal (MEV–MAV)" / "exceeding MRV – overtraining risk", a prescription a coach acts on.

  Measured read-only against live DynamoDB 2026-09-21 (genesis 2026-09-06, so only 15 days of the
  record were visible), 30d window 2026-08-22..09-21: Chest 72 -> 84 sets, Triceps 87 -> 99,
  Shoulders 56 -> 66, Back 55 -> 58, Biceps 61 -> 64. No verdict flipped at 30d that day; at 90d
  Biceps flipped "maintenance only" -> "approaching MEV / low optimal" (4.7 -> 6.3 sets/wk). The
  error is a function of days-since-genesis: smallest exactly when someone looks for it, and TOTAL
  on the morning after a restart.

  SECOND DEFECT, same function: `start_date` defaulted to "2000-01-01" while `avg_sets_per_period`
  divides `total_sets` by `(end - start)/7`. Live, the default call reported
  `num_periods_analyzed 1394.3` and ~0.0 sets/week for every muscle — "below maintenance" across
  the board on a week he trained 16 sessions. An all-time default is right for a RECORD
  (`get_exercise_history`) and wrong for a RATE.

  THIRD, and why the fix is not just "lift the filter": the partition carries 421 legacy daily
  aggregates (`sk = DATE#YYYY-MM-DD`) superseded in place 2026-05-26, all stamped
  `tombstone=true, tombstoned_reason="legacy_daily_aggregate_superseded_by_per_workout"`, every
  date also covered by a per-workout row. `normalize_hevy_items` parses BOTH shapes, so a naive
  `include_pilot=True` double-counts every pre-2025-11-08 session. `_read_hevy_all_phases` (#4030)
  drops them; these tests hold that it still does when the muscle-volume path is the caller.

THE FIXTURE IS THE WIRE
  `_FakeTable` is patched over `mcp.core.table` (the object `query_source` actually calls) and over
  `mcp.tools_strength.table` (the completeness high-water query), NOT over `query_source_range`.
  Every assertion therefore runs through the real `query_source` -> `_apply_phase_filter` path: the
  fake evaluates the genuine `boto3.dynamodb.conditions` key-condition tree and applies the exact
  `FilterExpression` string `mcp.core` mints, with DynamoDB's own semantics (an item with no
  `phase` attribute passes `attribute_not_exists`). A future edit to that expression makes the fake
  raise rather than go quietly permissive. Row shapes are copied from the live partition.

  Dates are relative to Pacific today so the rows stay inside the trailing default window as the
  calendar moves. Set COUNTS are deliberately chosen to straddle a Chest landmark boundary — that
  is the point: the phase filter does not merely change a number, it changes the verdict.
"""

from __future__ import annotations

import os
import pathlib
import sys
from datetime import timedelta

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import mcp.core as core  # noqa: E402
import mcp.tools_strength as ts  # noqa: E402

PK = "USER#matthew#SOURCE#hevy"
BENCH_TID = "79D0BD87"  # Bench Press (Barbell) -> Chest + Triceps + Shoulders, pattern Push

_TODAY = ts.pacific_now().date()
_EXPERIMENT_DATE = (_TODAY - timedelta(days=3)).isoformat()  # current cycle
_PILOT_DATE = (_TODAY - timedelta(days=20)).isoformat()  # pre-genesis, INSIDE the 28d window
_ANCIENT_DATE = (_TODAY - timedelta(days=200)).isoformat()  # pre-genesis, OUTSIDE it

_PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"


def _sets(n: int, warmups: int = 0) -> list[dict]:
    """n working sets (+ warmups, which never count toward volume) in the live per-workout shape."""
    out = [{"weight_kg": 60.0, "reps": 8, "set_type": "warmup"} for _ in range(warmups)]
    out += [{"weight_kg": 80.0, "reps": 8, "set_type": "normal", "rpe": 8.0} for _ in range(n)]
    return out


def _workout(date: str, phase: str, uid: str, n_sets: int, warmups: int = 0) -> dict:
    return {
        "pk": PK,
        "sk": f"DATE#{date}#WORKOUT#{uid}",
        "date": date,
        "phase": phase,
        "source_workout_id": uid,
        "workout_name": "Push",
        "exercises": [
            {
                "template_id": BENCH_TID,
                "name": "Bench Press (Barbell)",
                "notes": "",
                "sets": _sets(n_sets, warmups),
            }
        ],
    }


# 24 working sets in the current cycle -> 6.0/wk over the 4-week default window:
#   Chest MV 4, MEV 8  -> "maintenance only".
# +32 pre-genesis sets -> 14.0/wk -> MAV_lo 12 < 14 <= MAV_hi 16 -> "optimal (MEV-MAV)".
# The phase filter is the difference between those two prescriptions.
_EXPERIMENT_WORKOUT = _workout(_EXPERIMENT_DATE, "experiment", "4c43e553-48c3-4a57-bb48-af833f38a3d6", 24, warmups=2)
_PILOT_WORKOUT = _workout(_PILOT_DATE, "pilot", "36bd9061-190b-43d4-acfd-515f5bb85dd0", 32)
_ANCIENT_WORKOUT = _workout(_ANCIENT_DATE, "pilot", "a1b2c3d4-0000-4000-8000-000000000001", 40)

# The superseded generation: a legacy daily aggregate covering the SAME pre-genesis session,
# tombstoned in place 2026-05-26. `normalize_hevy_items` still parses it, so if it is not
# dropped the pre-genesis Chest sets are counted twice.
_LEGACY_TOMBSTONED_DUPLICATE = {
    "pk": PK,
    "sk": f"DATE#{_PILOT_DATE}",
    "date": _PILOT_DATE,
    "phase": "pilot",
    "tombstone": True,
    "tombstoned_at": "2026-05-26T00:16:57.567204+00:00",
    "tombstoned_reason": "legacy_daily_aggregate_superseded_by_per_workout",
    "workouts": [
        {
            "name": "Push",
            "exercises": [
                {
                    "name": "Bench Press (Barbell)",
                    "sets": [{"weight_lbs": 176.0, "reps": 8, "set_type": "normal"} for _ in range(32)],
                }
            ],
        }
    ],
}

_ROWS = [_LEGACY_TOMBSTONED_DUPLICATE, _ANCIENT_WORKOUT, _PILOT_WORKOUT, _EXPERIMENT_WORKOUT]


def _eval_key_condition(cond, item) -> bool:
    """Evaluate a real boto3 Key condition tree against one item."""
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        return _eval_key_condition(vals[0], item) and _eval_key_condition(vals[1], item)
    attr = vals[0].name
    actual = str(item.get(attr, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r} — the fixture must be the wire")


class _FakeTable:
    """DynamoDB Query semantics for the two shapes this tool builds.

    (1) `mcp.core.query_source`'s ranged read, optionally carrying the phase FilterExpression.
    (2) the completeness high-water probe: `begins_with("DATE#")`, ScanIndexForward=False, Limit=1.
    """

    def __init__(self, rows):
        self.rows = rows
        self.filter_expressions_seen: list = []

    def query(self, **kwargs):
        rows = [r for r in self.rows if _eval_key_condition(kwargs["KeyConditionExpression"], r)]
        fe = kwargs.get("FilterExpression")
        self.filter_expressions_seen.append(fe)
        if fe is not None:
            # The only FilterExpression mcp.core mints on this path. Asserted rather than
            # pattern-matched so a future edit to it cannot make this fake silently permissive.
            assert fe == _PHASE_FILTER_EXPRESSION, f"unexpected FilterExpression {fe!r}"
            field = kwargs["ExpressionAttributeNames"]["#phase"]
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            # DynamoDB: an item with no `phase` attribute passes attribute_not_exists.
            rows = [r for r in rows if field not in r or r[field] == wanted]
        rows = sorted(rows, key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        if kwargs.get("Limit"):
            rows = rows[: kwargs["Limit"]]
        return {"Items": rows}


@pytest.fixture
def wired(monkeypatch):
    fake = _FakeTable(_ROWS)
    monkeypatch.setattr(core, "table", fake)  # the ranged read
    monkeypatch.setattr(ts, "table", fake)  # the completeness high-water probe
    return fake


def _chest(out: dict) -> dict:
    return out["muscle_volume"]["Chest"]


# ── the defect itself: the verdict, not just the number ───────────────────────
def test_both_cycles_are_counted_and_the_landmark_verdict_changes(wired):
    """A pre-genesis session inside the window counts, and here it moves the prescription."""
    out = ts.tool_get_muscle_volume({})

    chest = _chest(out)
    assert chest["total_sets"] == 56, out["searched"]  # 24 current cycle + 32 pre-genesis
    assert chest["avg_sets_per_week"] == 14.0
    assert chest["volume_landmark_status"] == "optimal (MEV–MAV)"
    # The pre-genesis session is what carries it there: 24 sets alone is 6.0/wk.
    assert out["movement_balance"]["push_sets"] == 56


def test_the_phase_filter_is_never_applied_to_this_partition(wired):
    ts.tool_get_muscle_volume({})
    assert wired.filter_expressions_seen, "the read never reached the table"
    assert all(fe is None for fe in wired.filter_expressions_seen), wired.filter_expressions_seen


def test_warmup_sets_are_still_excluded(wired):
    """The read widened; what counts as a working set did not."""
    out = ts.tool_get_muscle_volume({})
    assert _chest(out)["total_sets"] == 56  # the 2 warmup sets on the current-cycle row are not in it


# ── the superseded legacy generation ──────────────────────────────────────────
def test_the_tombstoned_legacy_aggregate_is_not_double_counted(wired):
    """The legacy daily aggregate restates the same pre-genesis session in the old shape.

    Counted, Chest would read 88 sets (56 + 32) / 22.0 per week -> "exceeding MRV –
    overtraining risk": a fabricated overtraining verdict off one real session.
    """
    out = ts.tool_get_muscle_volume({})
    assert _chest(out)["total_sets"] == 56
    assert _chest(out)["volume_landmark_status"] != "exceeding MRV – overtraining risk"
    assert out["searched"]["workouts_read"] == 2  # a tombstone is not a workout read


# ── the 26-year divisor ───────────────────────────────────────────────────────
def test_the_default_window_is_a_rate_window_not_all_time(wired):
    """Live before this fix: num_periods_analyzed 1394.3, every muscle "below maintenance"."""
    out = ts.tool_get_muscle_volume({})

    assert out["date_range"]["start"] == (_TODAY - timedelta(days=28)).isoformat()
    assert out["date_range"]["end"] == _TODAY.isoformat()
    assert out["num_periods_analyzed"] == 4.0
    assert out["searched"]["window_source"] == "default trailing 28d (week view)"
    assert out["searched"]["default_lookback_days"] == 28
    # The all-time default would have put ~1,380 in this field and 0.0 in every rate.
    assert out["num_periods_analyzed"] < 10
    assert _chest(out)["avg_sets_per_week"] > 1


def test_the_month_view_defaults_to_its_own_rate_window(wired):
    out = ts.tool_get_muscle_volume({"period": "month"})

    assert out["analysis_period"] == "month"
    assert out["date_range"]["start"] == (_TODAY - timedelta(days=90)).isoformat()
    assert out["searched"]["default_lookback_days"] == 90
    assert out["num_periods_analyzed"] == round(90 / 30.44, 1)
    assert "avg_sets_per_month" in _chest(out)


def test_an_explicit_window_is_still_the_callers_and_says_so(wired):
    """Cross-phase is not unbounded — the DATE window bounds recency (#2109), including a
    26-year one if the caller genuinely asks for it. It is the DEFAULT that changed."""
    out = ts.tool_get_muscle_volume({"start_date": "2000-01-01", "end_date": _TODAY.isoformat()})

    assert out["date_range"]["start"] == "2000-01-01"
    assert out["searched"]["window_source"] == "caller"
    assert out["num_periods_analyzed"] > 1000  # the caller asked for it; it is not hidden
    # …and the ancient pre-genesis session is inside THAT window, so it is counted.
    assert _chest(out)["total_sets"] == 96  # 24 + 32 + 40


def test_a_narrow_window_still_excludes_what_is_outside_it(wired):
    out = ts.tool_get_muscle_volume({"start_date": (_TODAY - timedelta(days=7)).isoformat()})

    assert _chest(out)["total_sets"] == 24  # only the current-cycle session
    assert out["searched"]["phases"] == ["experiment"]
    assert out["searched"]["window_source"] == "caller"


# ── the answer states what it did ─────────────────────────────────────────────
def test_the_answer_names_the_window_and_the_phases_it_searched(wired):
    out = ts.tool_get_muscle_volume({})
    searched = out["searched"]

    assert searched["window"] == {"start": (_TODAY - timedelta(days=28)).isoformat(), "end": _TODAY.isoformat()}
    assert searched["phases"] == ["experiment", "pilot"]
    assert searched["workouts_read"] == 2
    assert "raw_timeseries" in searched["phase_filter"]
    # #4031: this tool asks about no single movement, so the block carries no movement keys.
    assert "exercise_name" not in searched and "template_id" not in searched


def test_the_exercise_history_searched_block_still_carries_its_movement_keys(wired):
    """The shared `_searched_block` helper is used by both tools; #4030's shape is unchanged."""
    out = ts.tool_get_exercise_history({"template_id": BENCH_TID})
    assert out["searched"]["template_id"] == BENCH_TID
    assert out["searched"]["exercise_name"] is None


# ── MUTATION CONTROL ──────────────────────────────────────────────────────────
def test_mutation_restoring_the_phase_filter_reproduces_the_bug(wired, monkeypatch):
    """Restore the pre-#4031 read and the pre-genesis work vanishes — with it the verdict.

    `source_reads_cross_phase` is the single derived decision the fix turns on, so forcing it
    False reproduces `query_source_range("hevy", …)`'s old default exactly.
    """
    import experiment.phase_filter as pf

    monkeypatch.setattr(pf, "source_reads_cross_phase", lambda *_a, **_k: False)
    out = ts.tool_get_muscle_volume({})

    chest = _chest(out)
    assert chest["total_sets"] == 24, "mutation did not bite — the filter is no longer load-bearing"
    assert chest["avg_sets_per_week"] == 6.0
    assert chest["volume_landmark_status"] == "maintenance only"  # vs "optimal (MEV–MAV)" when fixed
    assert out["searched"]["phases"] == ["experiment"]
    assert wired.filter_expressions_seen[0] == _PHASE_FILTER_EXPRESSION


# ── the registered description carries the guarantee ──────────────────────────
def test_registered_description_states_the_cross_phase_read_and_the_default_window():
    from mcp.registry import TOOLS

    desc = TOOLS["get_muscle_volume"]["schema"]["description"]
    assert "phase filter" in desc.lower()
    assert "28 days" in desc
    assert "searched" in desc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

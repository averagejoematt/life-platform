"""tests/test_exercise_history_cross_phase_4030.py — an all-time tool that saw one cycle.

THE BUG (#4030)
  `tool_get_exercise_history` defaults `start_date` to 2000-01-01 and called
  `query_source_range("hevy", start, end)` — an alias for `query_source(..., include_pilot=False)`,
  which applies the ADR-058 phase filter. The restart stamps every pre-genesis row `phase=pilot`
  (ADR-077), so the tool whose whole purpose is the complete record answered from the CURRENT
  CYCLE ONLY. Measured read-only against live DynamoDB 2026-09-21: 15 of 499 Hevy workouts
  visible (`{'pilot': 484, 'experiment': 15}`), 26 of 557 distinct movements; the owner's
  2026-06-21 Romanian Deadlift (template `2B4B7310`, 83.91 kg x 8 x 3) was absent and the tool
  reported `date_range 2026-09-09..2026-09-17, n_sessions 3` with a `total_1rm_gain` of -31.2 lb
  computed over eight days of a five-year record. `phase_taxonomy.classify` rules
  `USER#matthew#SOURCE#hevy` **raw_timeseries** — cross-phase by design — and
  `phase_filter.source_reads_cross_phase("hevy")` already returned True. The read never asked.

  Second half of the same fix: lifting the filter alone DOUBLE-COUNTS. The partition carries 421
  legacy daily aggregates (`sk = DATE#YYYY-MM-DD`) superseded in place on 2026-05-26 — all 421
  stamped `tombstone=true, tombstoned_reason="legacy_daily_aggregate_superseded_by_per_workout"`,
  every one of their dates also covered by a per-workout row. `normalize_hevy_items` parses both
  shapes, so a naive bypass returned `exercise_name="squat"` 486 sessions against 250 real ones.

THE FIXTURE IS THE WIRE
  `_FakeTable` is patched into `mcp.core` (NOT over `query_source_range`), so every assertion
  below runs through the real `query_source` → `_apply_phase_filter` path. The fake parses the
  actual `boto3.dynamodb.conditions` key condition and applies the real FilterExpression string
  `mcp.core` builds, with DynamoDB's own semantics (an item with no `phase` attribute passes).
  Row shapes are copied from the live partition read on 2026-09-21, never invented.
"""

from __future__ import annotations

import os
import pathlib
import sys

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
TID = "2B4B7310"  # Romanian Deadlift (Barbell) — the live specimen from the issue

# ── the wire shape, copied from the live partition ────────────────────────────
# One movement performed in two cycles. The archive row is stamped `phase=pilot` exactly as
# the restart tagger stamps it; the current row is `phase=experiment`.
_PILOT_SESSION = {
    "pk": PK,
    "sk": "DATE#2026-06-21#WORKOUT#36bd9061-190b-43d4-acfd-515f5bb85dd0",
    "date": "2026-06-21",
    "phase": "pilot",
    "source_workout_id": "36bd9061-190b-43d4-acfd-515f5bb85dd0",
    "workout_name": "Pull",
    "exercises": [
        {
            "template_id": TID,
            "name": "Romanian Deadlift (Barbell)",
            "notes": "",
            "sets": [
                {"weight_kg": 83.91468824559335, "reps": 8, "set_type": "normal", "rpe": 7.5},
                {"weight_kg": 83.91468824559335, "reps": 8, "set_type": "normal", "rpe": 8.0},
            ],
        }
    ],
}
_EXPERIMENT_SESSION = {
    "pk": PK,
    "sk": "DATE#2026-09-17#WORKOUT#4c43e553-48c3-4a57-bb48-af833f38a3d6",
    "date": "2026-09-17",
    "phase": "experiment",
    "source_workout_id": "4c43e553-48c3-4a57-bb48-af833f38a3d6",
    "workout_name": "Pull",
    "exercises": [
        {
            "template_id": TID,
            "name": "Romanian Deadlift (Barbell)",
            "notes": "felt light",
            "sets": [{"weight_kg": 79.37866488, "reps": 8, "set_type": "normal", "rpe": 7.0}],
        }
    ],
}
# The superseded generation: a legacy daily aggregate covering the SAME 2026-06-21 session.
# Tombstoned 2026-05-26 in the live store; `normalize_hevy_items` still parses it.
_LEGACY_TOMBSTONED_DUPLICATE = {
    "pk": PK,
    "sk": "DATE#2026-06-21",
    "date": "2026-06-21",
    "phase": "pilot",
    "tombstone": True,
    "tombstoned_at": "2026-05-26T00:16:57.567204+00:00",
    "tombstoned_reason": "legacy_daily_aggregate_superseded_by_per_workout",
    "workouts": [
        {
            "title": "Pull",
            "exercises": [
                {
                    "name": "Romanian Deadlift (Barbell)",
                    "sets": [
                        {"weight_lbs": 185.0, "reps": 8, "set_type": "normal"},
                        {"weight_lbs": 185.0, "reps": 8, "set_type": "normal"},
                    ],
                }
            ],
        }
    ],
}

_ROWS = [_LEGACY_TOMBSTONED_DUPLICATE, _PILOT_SESSION, _EXPERIMENT_SESSION]

_PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"


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
    """DynamoDB Query semantics for exactly the shape `mcp.core.query_source` builds."""

    def __init__(self, rows):
        self.rows = rows
        self.filter_expressions_seen: list = []

    def query(self, **kwargs):
        rows = [r for r in self.rows if _eval_key_condition(kwargs["KeyConditionExpression"], r)]
        fe = kwargs.get("FilterExpression")
        self.filter_expressions_seen.append(fe)
        if fe is not None:
            # The only FilterExpression mcp.core mints on this path. Asserted rather than
            # pattern-matched so a future edit to the expression cannot make this fake
            # silently permissive.
            assert fe == _PHASE_FILTER_EXPRESSION, f"unexpected FilterExpression {fe!r}"
            field = kwargs["ExpressionAttributeNames"]["#phase"]
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            # DynamoDB: an item with no `phase` attribute passes attribute_not_exists.
            rows = [r for r in rows if field not in r or r[field] == wanted]
        return {"Items": rows}


@pytest.fixture
def wired(monkeypatch):
    fake = _FakeTable(_ROWS)
    monkeypatch.setattr(core, "table", fake)
    return fake


# ── the specimen from the issue ────────────────────────────────────────────────
def test_both_cycles_are_returned_for_one_template(wired):
    """One movement performed in two cycles → BOTH sessions, pilot and experiment."""
    out = ts.tool_get_exercise_history({"template_id": TID})

    assert "error" not in out, out
    assert out["n_sessions"] == 2, out.get("searched")
    assert [s["date"] for s in out["sessions"]] == ["2026-06-21", "2026-09-17"]
    assert out["date_range"] == {"start": "2026-06-21", "end": "2026-09-17"}
    # The pre-genesis row is the one the bug dropped; name it explicitly.
    assert any(s["date"] == "2026-06-21" for s in out["sessions"]), "the pre-genesis (phase=pilot) session is missing"


def test_the_answer_names_the_window_and_the_phases_it_searched(wired):
    out = ts.tool_get_exercise_history({"template_id": TID})
    searched = out["searched"]

    assert searched["window"] == {"start": "2000-01-01", "end": ts.pacific_now().date().isoformat()}
    assert searched["phases"] == ["experiment", "pilot"]
    assert searched["workouts_read"] == 2  # the tombstoned duplicate is not a workout read
    assert "raw_timeseries" in searched["phase_filter"]


def test_the_phase_filter_is_never_applied_to_this_partition(wired):
    ts.tool_get_exercise_history({"template_id": TID})
    assert wired.filter_expressions_seen, "the read never reached the table"
    assert all(fe is None for fe in wired.filter_expressions_seen), wired.filter_expressions_seen


def test_the_superseded_legacy_generation_is_not_double_counted(wired):
    """The tombstoned daily aggregate covers the same 2026-06-21 session in the old shape."""
    out = ts.tool_get_exercise_history({"template_id": TID})
    assert [s["date"] for s in out["sessions"]].count("2026-06-21") == 1

    # …and it is invisible to the fuzzy-name path too, which is where it actually bit
    # (the legacy shape carries no template_id, so only a name match can reach it).
    fuzzy = ts.tool_get_exercise_history({"exercise_name": "romanian deadlift"})
    assert "ambiguous" not in fuzzy, fuzzy
    assert fuzzy["n_sessions"] == 2
    assert [s["date"] for s in fuzzy["sessions"]] == ["2026-06-21", "2026-09-17"]


# ── the empty answer ───────────────────────────────────────────────────────────
def test_an_empty_result_states_the_window_and_the_phases_searched(wired):
    """An empty answer must be unmistakable for "never done" — in the machine-readable
    `searched` block AND in the `error` sentence, which may be all a reader sees."""
    out = ts.tool_get_exercise_history({"template_id": "DEADBEEF", "start_date": "2021-01-01", "end_date": "2026-09-21"})

    assert out["n_sessions"] == 0
    assert out["searched"]["window"] == {"start": "2021-01-01", "end": "2026-09-21"}
    assert out["searched"]["phases"] == ["experiment", "pilot"]
    assert out["searched"]["workouts_read"] == 2

    msg = out["error"]
    assert "2021-01-01" in msg and "2026-09-21" in msg, msg
    assert "pilot" in msg and "experiment" in msg, msg
    assert "No phase filter was applied" in msg, msg


def test_an_empty_window_still_names_the_window_it_searched(wired):
    """Zero rows read at all: the phases list is honestly empty and says so."""
    out = ts.tool_get_exercise_history({"template_id": TID, "start_date": "2019-01-01", "end_date": "2019-12-31"})

    assert out["n_sessions"] == 0
    assert out["searched"]["window"] == {"start": "2019-01-01", "end": "2019-12-31"}
    assert out["searched"]["phases"] == []
    assert out["searched"]["workouts_read"] == 0
    assert "2019-01-01" in out["error"] and "none (no workouts in this window)" in out["error"], out["error"]


# ── start_date / end_date are still honoured ───────────────────────────────────
def test_start_and_end_date_still_bound_the_answer(wired):
    """Cross-phase is not unbounded: the DATE window is what bounds recency (#2109)."""
    out = ts.tool_get_exercise_history({"template_id": TID, "start_date": "2026-01-01", "end_date": "2026-07-01"})
    assert out["n_sessions"] == 1
    assert [s["date"] for s in out["sessions"]] == ["2026-06-21"]
    assert out["searched"]["window"] == {"start": "2026-01-01", "end": "2026-07-01"}

    out2 = ts.tool_get_exercise_history({"template_id": TID, "start_date": "2026-09-01"})
    assert [s["date"] for s in out2["sessions"]] == ["2026-09-17"]


# ── MUTATION CONTROL ───────────────────────────────────────────────────────────
def test_mutation_restoring_the_phase_filter_reproduces_the_bug(wired, monkeypatch):
    """Restore the pre-#4030 read and the archive vanishes — the proof that the phase
    filter, not the fixture, is what these tests are holding.

    `source_reads_cross_phase` is the single derived decision the fix turns on, so forcing
    it False reproduces `query_source_range("hevy", …)`'s old default exactly.
    """
    import experiment.phase_filter as pf

    monkeypatch.setattr(pf, "source_reads_cross_phase", lambda *_a, **_k: False)
    out = ts.tool_get_exercise_history({"template_id": TID})

    assert out["n_sessions"] == 1, "mutation did not bite — the filter is no longer load-bearing"
    assert [s["date"] for s in out["sessions"]] == ["2026-09-17"]
    assert not any(fe is None for fe in wired.filter_expressions_seen[-1:])


# ── the registered description carries the guarantee (acceptance box 5) ────────
def test_registered_description_states_the_cross_phase_all_time_guarantee():
    from mcp.registry import TOOLS

    desc = TOOLS["get_exercise_history"]["schema"]["description"]
    assert "phase" in desc.lower()
    assert "searched" in desc
    assert "never done" in desc.lower()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

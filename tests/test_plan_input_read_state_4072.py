"""tests/test_plan_input_read_state_4072.py — a failed read is not an unknown one.

THE DEFECT (#4072)
  From 8 coaching sessions 2026-09-14 -> 09-22, `plan_next_session` returned null/unknown for
  recovery, volume and the protein tripwire on 09-15/16/17/18 with every source fresh, and
  `readiness_floor` read `unknown — "no recovery series"` with Whoop fresh. Two causes, decoded:

  1. `readiness_floor` had NO PRODUCER. Nothing in stage 1 (or stage 2) ever passed
     `readiness_low_streak_days` to the engine, so the row was `unknown` on every call, on
     every day — and its detail, "no recovery series", was a claim about data the engine had
     never looked at. Live read 2026-09-22 (read-only): the whoop partition carries a daily
     `recovery_score` row for every day 2026-08-25..2026-09-22.
  2. The 09-15..18 recovery / volume / protein nulls were readers keyed on names the live
     tools never returned (`score` vs `readiness_score`, `daily_rows` vs `daily_breakdown`,
     ...) — fixed by #3934 on 09-19; re-read live 2026-09-22 against 09-16 they return
     green 71.7 / 18 muscles / protein 5-of-7. But the ENGINE could not tell that shape
     drift, or a raise swallowed by `_safe`, from an empty window: all three printed
     `unknown`. So the drift was invisible for four days.

WHAT IS PINNED HERE
  * every engine input carries `measured` / `absent` / `read_failed` (+ error class) /
    `not_read` on `constraint_block.inputs`;
  * a RAISING reader -> `read_failed` in the output, never `unknown`;
  * an EMPTY window -> `absent` (and the tripwire `unknown`, with the absence as its reason);
  * REAL data -> `measured`, and `readiness_floor` evaluates (clear / tripped) from Whoop;
  * a succeeded read with none of its known keys -> `read_failed (InputShapeError)`.

THE FIXTURE IS THE WIRE
  `_FakeTable` is patched over `mcp.core.table`, so the Whoop read runs through the real
  `query_source_cross_phase` -> `query_source` -> `_apply_phase_filter` path. The rows are
  the live partition's values (read-only, 2026-09-22), including the `DATE#<day>#WORKOUT#`
  rows that share the prefix and carry no recovery score, and the pre-genesis `phase=pilot`
  rows the default phase filter hides.
"""

from __future__ import annotations

import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import plan_engine  # noqa: E402

import mcp.core as core  # noqa: E402
import mcp.tools_plan as tp  # noqa: E402
import mcp.tools_training_notes as tn  # noqa: E402

WHOOP_PK = "USER#matthew#SOURCE#whoop"
TODAY = "2026-09-22"

# Live whoop daily recovery_score, 2026-08-25..2026-09-22 (read-only query, 2026-09-22).
# Genesis is 2026-09-06: every earlier row is stamped phase=pilot.
_LIVE_RECOVERY = {
    "2026-08-25": 72, "2026-08-26": 52, "2026-08-27": 49, "2026-08-28": 34, "2026-08-29": 19,
    "2026-08-30": 54, "2026-08-31": 45, "2026-09-01": 75, "2026-09-02": 69, "2026-09-03": 67,
    "2026-09-04": 66, "2026-09-05": 85, "2026-09-06": 48, "2026-09-07": 76, "2026-09-08": 67,
    "2026-09-09": 64, "2026-09-10": 44, "2026-09-11": 24, "2026-09-12": 59, "2026-09-13": 73,
    "2026-09-14": 63, "2026-09-15": 82, "2026-09-16": 92, "2026-09-17": 94, "2026-09-18": 84,
    "2026-09-19": 98, "2026-09-20": 97, "2026-09-21": 90, "2026-09-22": 78,
}  # fmt: skip


def _whoop_rows(recovery=None):
    rows = []
    for day, score in (recovery if recovery is not None else _LIVE_RECOVERY).items():
        phase = "pilot" if day < "2026-09-06" else "experiment"
        rows.append({"pk": WHOOP_PK, "sk": f"DATE#{day}", "date": day, "phase": phase, "recovery_score": score, "source": "whoop"})
        # the same partition carries per-workout rows under the day prefix, with no recovery score
        rows.append({"pk": WHOOP_PK, "sk": f"DATE#{day}#WORKOUT#w-{day}", "date": day, "phase": phase, "sport_name": "walking"})
    return rows


def _eval_key_condition(cond, item) -> bool:
    expr = cond.get_expression()
    op, vals = expr["operator"], expr["values"]
    if op == "AND":
        return _eval_key_condition(vals[0], item) and _eval_key_condition(vals[1], item)
    actual = str(item.get(vals[0].name, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r} — the fixture must be the wire")


class _FakeTable:
    def __init__(self, rows, raise_on_pk=None):
        self.rows, self.raise_on_pk = rows, raise_on_pk

    def query(self, **kwargs):
        cond = kwargs["KeyConditionExpression"]
        pk = cond.get_expression()["values"][0].get_expression()["values"][1]
        if self.raise_on_pk and self.raise_on_pk in str(pk):
            raise RuntimeError("DDB down")
        rows = [r for r in self.rows if _eval_key_condition(cond, r)]
        if kwargs.get("FilterExpression") is not None:
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            rows = [r for r in rows if "phase" not in r or r["phase"] == wanted]
        return {"Items": rows}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(tp, "pacific_today", lambda: TODAY)


def _wire(monkeypatch, rows, raise_on_pk=None):
    fake = _FakeTable(rows, raise_on_pk=raise_on_pk)
    monkeypatch.setattr(core, "table", fake)
    monkeypatch.setattr(tn, "table", fake)
    return fake


def _stage1(target_date=TODAY, **overrides):
    """Stage 1 with every reader other than the whoop streak stubbed to a live shape."""
    readers = {
        "mcp.tools_benchmark.tool_get_benchmark": {"return_value": {"applicable": False, "reason": "no band"}},
        "mcp.tools_health.tool_get_readiness_score": {"return_value": {"readiness_score": 76.5, "label": "green"}},
        "mcp.tools_training.tool_get_acwr_status": {"return_value": {"zone": "safe"}},
        "mcp.tools_strength.tool_get_muscle_volume": {"return_value": {"muscle_volume": {"Back": {"avg_sets_per_week": 16.2}}}},
        "mcp.tools_plan._protein_days_7d": {"return_value": (6, 7)},
        "mcp.tools_plan._walking_volume_last_7d": {"return_value": None},
        "mcp.tools_plan._rotation_window": {"return_value": (None, None)},
        "mcp.tools_plan._pain_dismissals": {"return_value": []},
        "mcp.tools_plan._gather_performed_evidence": {"return_value": None},
        "mcp.tools_plan._nutrition_critics_block": {"return_value": {"verdicts": []}},
        "training.training_notes.training_notes_health": {
            "return_value": {"checked": True, "degraded": 0, "records_found": 4, "extractor_dark": False}
        },
    }
    readers.update(overrides)
    with ExitStack() as st:
        for target, kw in readers.items():
            st.enter_context(patch(target, **kw))
        return tp.tool_plan_next_session({"target_date": target_date})


def _row(out, tid):
    return next(t for t in out["constraint_block"]["tripwires"] if t["id"] == tid)


# ══════════════════════════════════════════════════════════════════════════════
# 1. readiness_floor reads the Whoop recovery series that exists
# ══════════════════════════════════════════════════════════════════════════════
class TestReadinessFloorReadsWhoop:
    def test_real_data_is_measured_and_the_tripwire_evaluates(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows())
        out = _stage1()
        row = _row(out, "readiness_floor")
        assert row["state"] == "clear", row  # 09-22 = 78, above 50
        assert row["observed"] == "0 consecutive days below 50"
        inp = out["constraint_block"]["inputs"]["readiness_low_streak_days"]
        assert inp["state"] == "measured" and inp["latest_day"] == TODAY and inp["source"] == "whoop"
        assert inp["n_days"] == 15, "14-day lookback inclusive of both ends; WORKOUT rows are not days"
        assert "no recovery series" not in str(row)

    def test_the_streak_is_counted_across_the_genesis_phase_boundary(self, monkeypatch):
        """The live 2026-08-27..29 run (49, 34, 19) is entirely phase=pilot. A phase-filtered
        read sees NO rows there and reports the series absent — the cross-phase read sees 3."""
        _wire(monkeypatch, _whoop_rows())
        streak, st = tp._readiness_low_streak("2026-08-29")
        assert streak == 3 and st["state"] == "measured" and st["phases_read"] == ["pilot"]

    def test_the_tripwire_can_trip_on_the_series(self, monkeypatch):
        """NEGATIVE CONTROL — five consecutive days under 50 trips it (synthetic values)."""
        low = {f"2026-09-{d:02d}": 40 for d in range(18, 23)}
        _wire(monkeypatch, _whoop_rows(low))
        row = _row(_stage1(), "readiness_floor")
        assert row["state"] == "tripped" and row["observed"] == "5 consecutive days below 50"

    def test_a_missing_day_breaks_the_streak_it_is_not_a_low_day(self, monkeypatch):
        low = {"2026-09-18": 40, "2026-09-19": 40, "2026-09-21": 40, "2026-09-22": 40}  # 09-20 unmeasured
        _wire(monkeypatch, _whoop_rows(low))
        streak, _ = tp._readiness_low_streak(TODAY)
        assert streak == 2

    def test_an_empty_window_is_absent_not_failed(self, monkeypatch):
        _wire(monkeypatch, [])
        out = _stage1()
        row = _row(out, "readiness_floor")
        assert row["state"] == "unknown"
        assert row["input_state"]["state"] == "absent"
        assert row["detail"].startswith("absent: no Whoop daily recovery_score row")
        assert out["constraint_block"]["inputs"]["readiness_low_streak_days"]["state"] == "absent"

    def test_a_writer_shape_drift_is_read_failed_not_absent(self, monkeypatch):
        """The #2847 seam: whoop_lambda writes `recovery_score`, this reads it. Rename the field
        on the writer side and the read must FAIL by name — an absent reading would be the
        09-15..18 class again (a fresh source reported as no data)."""
        rows = [
            {**{k: v for k, v in r.items() if k != "recovery_score"}, "recovery": r["recovery_score"]} if "recovery_score" in r else r
            for r in _whoop_rows()
        ]
        _wire(monkeypatch, rows)
        out = _stage1()
        row = _row(out, "readiness_floor")
        assert row["state"] == "read_failed" and "InputShapeError" in row["detail"], row

    def test_a_raising_whoop_read_is_read_failed_not_unknown(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows(), raise_on_pk=WHOOP_PK)
        out = _stage1()
        row = _row(out, "readiness_floor")
        assert row["state"] == "read_failed", row
        assert "RuntimeError: DDB down" in row["detail"]
        assert "readiness_floor" in out["constraint_block"]["failed_read_tripwires"]
        assert out["constraint_block"]["inputs"]["readiness_low_streak_days"]["error"] == "RuntimeError: DDB down"
        assert any("FAILED to read" in h and "readiness_low_streak_days" in h for h in out["constraint_block"]["honesty"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. every stage-1 input: raising -> read_failed, empty -> absent, real -> measured
# ══════════════════════════════════════════════════════════════════════════════
class TestEveryInputStatesItsRead:
    def test_real_data_reads_measured(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows())
        inputs = _stage1()["constraint_block"]["inputs"]
        for name in ("recovery_tier", "acwr_flag", "muscle_volume", "protein_days_missed_7d", "readiness_low_streak_days"):
            assert inputs[name]["state"] == "measured", (name, inputs[name])
        assert inputs["weight_stall_days"]["state"] == "not_read", "an unwired input is named, never implied"
        assert inputs["anchor_lift_drop_pct"]["state"] == "not_read"

    @pytest.mark.parametrize(
        "target, name, tripwire",
        [
            ("mcp.tools_health.tool_get_readiness_score", "recovery_tier", None),
            ("mcp.tools_training.tool_get_acwr_status", "acwr_flag", None),
            ("mcp.tools_strength.tool_get_muscle_volume", "muscle_volume", None),
            ("mcp.tools_plan._protein_days_7d", "protein_days_missed_7d", "protein_floor_missed"),
        ],
    )
    def test_a_raising_reader_is_read_failed_in_the_output(self, monkeypatch, target, name, tripwire):
        _wire(monkeypatch, _whoop_rows())
        out = _stage1(**{target: {"side_effect": TimeoutError("read timed out")}})
        inp = out["constraint_block"]["inputs"][name]
        assert inp["state"] == "read_failed" and inp["error"] == "TimeoutError: read timed out", inp
        if tripwire:
            row = _row(out, tripwire)
            assert row["state"] == "read_failed" and "TimeoutError" in row["detail"]
            assert tripwire not in [t["id"] for t in out["constraint_block"]["tripwires"] if t["state"] == "unknown"]

    def test_the_protein_tripwire_distinguishes_absent_from_failed(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows())
        absent = _stage1(**{"mcp.tools_plan._protein_days_7d": {"return_value": (None, None)}})
        row = _row(absent, "protein_floor_missed")
        assert row["state"] == "unknown" and row["input_state"]["state"] == "absent"

    def test_a_wrong_shape_is_read_failed_not_absent(self, monkeypatch):
        """The 09-15..18 class: the tool answered, under a key the planner did not read."""
        _wire(monkeypatch, _whoop_rows())
        out = _stage1(**{"mcp.tools_health.tool_get_readiness_score": {"return_value": {"readiness": 71.7, "label": "green"}}})
        inp = out["constraint_block"]["inputs"]["recovery_tier"]
        assert inp["state"] == "read_failed" and inp["error"].startswith("InputShapeError"), inp

    def test_an_empty_answer_is_absent(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows())
        out = _stage1(
            **{
                "mcp.tools_health.tool_get_readiness_score": {"return_value": {"readiness_score": None}},
                "mcp.tools_strength.tool_get_muscle_volume": {"return_value": {"muscle_volume": {}}},
            }
        )
        inputs = out["constraint_block"]["inputs"]
        assert inputs["recovery_tier"]["state"] == "absent"
        assert inputs["muscle_volume"]["state"] == "absent"

    def test_a_tool_error_dict_is_read_failed_unless_it_says_no_data(self, monkeypatch):
        _wire(monkeypatch, _whoop_rows())
        broken = _stage1(**{"mcp.tools_training.tool_get_acwr_status": {"return_value": {"error": "Could not parse date"}}})
        assert broken["constraint_block"]["inputs"]["acwr_flag"]["state"] == "read_failed"
        empty = _stage1(**{"mcp.tools_training.tool_get_acwr_status": {"return_value": {"error": "No Whoop data in range"}}})
        assert empty["constraint_block"]["inputs"]["acwr_flag"]["state"] == "absent"

    def test_protein_reader_raises_on_a_shape_change(self):
        with patch("mcp.tools_nutrition.tool_get_nutrition", return_value={"summary": {"protein_g": 190}}):
            with pytest.raises(tp.InputShapeError):
                tp._protein_days_7d("2026-09-20")


# ══════════════════════════════════════════════════════════════════════════════
# 3. the pure engine: an input status turns a None into read_failed, not unknown
# ══════════════════════════════════════════════════════════════════════════════
class TestTheEngine:
    def test_gather_records_a_raise_as_read_failed_and_an_empty_return_as_absent(self):
        def _boom():
            raise ConnectionError("reset by peer")

        kw = plan_engine.gather({"protein_days_missed_7d": _boom, "muscle_volume": lambda: {}, "readiness_low_streak_days": lambda: 2})
        block = plan_engine.constraint_block(date=TODAY, **kw)
        states = {t["id"]: t["state"] for t in block["tripwires"]}
        assert states["protein_floor_missed"] == "read_failed"
        assert states["readiness_floor"] == "clear"
        assert block["inputs"]["muscle_volume"]["state"] == "absent"
        assert block["inputs"]["protein_days_missed_7d"]["error"] == "ConnectionError: reset by peer"

    def test_a_failed_read_never_emits_unknown(self):
        failed = plan_engine.input_status(plan_engine.READ_FAILED, error="TimeoutError: x")
        block = plan_engine.constraint_block(
            date=TODAY,
            input_status={k: failed for k in plan_engine.ENGINE_INPUTS},
        )
        unknown = [t["id"] for t in block["tripwires"] if t["state"] == "unknown"]
        assert unknown == [], f"a failed read surfaced as unknown: {unknown}"
        assert block["walking"]["state"] == "read_failed"

    def test_a_pure_caller_without_status_keeps_the_old_contract(self):
        """Back-compat: no status stated -> `unknown` with `not_supplied`, never `absent`."""
        block = plan_engine.constraint_block(date=TODAY)
        row = next(t for t in block["tripwires"] if t["id"] == "readiness_floor")
        assert row["state"] == "unknown"
        assert block["inputs"]["readiness_low_streak_days"]["state"] == "not_supplied"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

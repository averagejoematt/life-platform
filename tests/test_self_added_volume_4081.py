"""tests/test_self_added_volume_4081.py — the self_added_volume tripwire is evaluated, from the record.

THE DEFECT (#4081)
  The v0.3 redline `self_added_volume` ("training above the prescription two weeks running")
  shipped `evaluated_by_engine: False`. The engine named it in `unevaluated_tripwires` and
  never looked — while cycle 17's Hevy record showed 4 sets performed against 3 prescribed on
  most movements, week after week, against a subtract-only program.

WHAT IS PINNED HERE
  * FIRE — two consecutive complete Mon–Sun weeks above the committed routine's sets trips the
    row, and the row carries the set-level evidence (day, movement, prescribed → performed).
  * NO-FIRE — one week above, the week before at prescription, reads `clear` with run 1.
  * the in-progress week is reported, never counted toward the run;
  * a window with no session, or whose deciding week held only unmatched sessions, is
    `unknown` — never `clear`; a raising read is `read_failed`;
  * the counts are `health.adherence_calc`'s (the `adherence.movements` block stored on each
    row) — the module never counts `exercises[].sets` itself;
  * MUTATION CONTROLS — the fire fixture with week 1 flattened to prescription stops firing,
    and raising the row's `threshold_weeks` to 3 stops it too (the engine reads the row, not a
    literal).

THE FIXTURE IS THE WIRE
  Rows are the live `USER#matthew#SOURCE#hevy` shape (read-only, 2026-09-22): `DATE#<day>#WORKOUT#<uid>`
  sort keys, Decimal counts, `adherence.status == "matched"`, `tmpl:<id>` movement keys that
  resolve through the row's own exercises. The stage-1 test runs the real `_prescription_window`
  → `query_source_range` → fake-table path.
"""

from __future__ import annotations

import copy
import os
import pathlib
import sys
from decimal import Decimal

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import owner_redlines, plan_engine, self_added_volume  # noqa: E402

HEVY_PK = "USER#matthew#SOURCE#hevy"
TODAY = "2026-09-22"  # a Tuesday: the week of 09-21 is in progress; 09-07 and 09-14 are complete
THRESHOLD = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "self_added_volume")["threshold_weeks"]


def _session(day: str, movements: list[tuple[str, int, int, float | None]], extra: list[str] | None = None, status="matched") -> dict:
    """One live-shaped Hevy row. `movements` = (movement_key, programmed_sets, performed_sets, max_rpe)."""
    exercises = []
    for key, _prog, perf, rpe in movements:
        tid = key[5:] if key.startswith("tmpl:") else key.upper()
        exercises.append(
            {
                "name": {"tmpl:7E3BC8B6": "Hammer Curl (Dumbbell)", "tmpl:BE640BA0": "Face Pull"}.get(key, key),
                "template_id": tid,
                "sets": [{"type": "normal", "reps": Decimal("10"), "rpe": Decimal(str(rpe)) if rpe else None}] * perf,
            }
        )
    adherence: dict = {"status": status, "workout_pacific_date": day}
    if status == "matched":
        adherence.update(
            {
                "match_method": "hevy_routine_id",
                "matched_routine_id": f"r-{day}",
                "movements": [
                    {
                        "movement_key": key,
                        "programmed_sets": Decimal(prog),
                        "performed_sets": Decimal(perf),
                        "pct": Decimal("100"),
                        "intensity": {"max_rpe": Decimal(str(rpe)) if rpe else None},
                    }
                    for key, prog, perf, rpe in movements
                ],
                "extra": extra or [],
            }
        )
    return {
        "pk": HEVY_PK,
        "sk": f"DATE#{day}#WORKOUT#w-{day}",
        "date": day,
        "phase": "experiment",
        "source": "hevy",
        "title": f"Foundation - {day}",
        "exercises": exercises,
        "adherence": adherence,
    }


# Live 2026-09-12 and 2026-09-20 pull days (the 4-vs-3 pattern), and the 09-14 / 09-22 days.
_PULL_0912 = [("lat_pulldown", 3, 4, None), ("one_arm_db_row", 3, 4, None), ("tmpl:BE640BA0", 3, 4, None), ("tmpl:7E3BC8B6", 3, 4, None)]
_PUSH_0914 = [("barbell_bench_press", 6, 7, None), ("db_shoulder_press", 3, 4, None), ("treadmill", 1, 1, None)]
_PULL_0920 = [("lat_pulldown", 3, 4, 8.5), ("tmpl:BE640BA0", 2, 3, 9.5), ("tmpl:7E3BC8B6", 2, 4, 9.5), ("cycling", 1, 1, None)]
_LEGS_0922 = [("tmpl:2B4B7310", 7, 7, 8.0), ("tmpl:11A123F3", 2, 4, 8.0)]


def _fire_rows() -> list[dict]:
    return [
        _session("2026-09-12", _PULL_0912),
        _session("2026-09-14", _PUSH_0914),
        _session("2026-09-20", _PULL_0920, extra=["243710DE"]),
        _session("2026-09-22", _LEGS_0922),
    ]


def _at_prescription(movs):
    return [(k, p, p, r) for k, p, _perf, r in movs]


def _no_fire_rows() -> list[dict]:
    """Only the week of 09-14 is above; the week of 09-07 trained exactly as prescribed."""
    rows = _fire_rows()
    rows[0] = _session("2026-09-12", _at_prescription(_PULL_0912))
    return rows


def _block(rows, **kw):
    return plan_engine.constraint_block(date=TODAY, hevy_workouts_prescription_window=rows, **kw)


def _row(block):
    return next(t for t in block["tripwires"] if t["id"] == "self_added_volume")


# ══ 1. the redline is evaluated ══════════════════════════════════════════════════════════
def test_the_redline_is_marked_evaluated_and_leaves_the_unevaluated_list():
    tw = {t["id"]: t for t in owner_redlines.TRIPWIRES}["self_added_volume"]
    assert tw["evaluated_by_engine"] is True
    assert "self_added_volume" not in owner_redlines.unevaluated_tripwires()
    block = _block(_fire_rows())
    assert "self_added_volume" not in block["unevaluated_tripwires"]
    line = next((h for h in block["honesty"] if "NOT evaluated by this engine" in h), "")
    assert "self_added_volume" not in line


# ══ 2. FIRE ══════════════════════════════════════════════════════════════════════════════
def test_two_complete_weeks_above_the_prescription_trip_the_row():
    row = _row(_block(_fire_rows()))
    assert row["state"] == "tripped"
    assert row["action_if_tripped"].startswith("read as an anxiety tell")
    ev = row["evidence"]
    assert ev["run_weeks"] == 2 and ev["threshold_weeks"] == THRESHOLD
    weeks = {w["week_start"]: w for w in ev["weeks"]}
    assert weeks["2026-09-07"]["verdict"] == "above" and weeks["2026-09-07"]["net_sets"] == 4
    assert weeks["2026-09-14"]["verdict"] == "above" and weeks["2026-09-14"]["added_sets"] == 2 + 1 + 1 + 2
    # set-level evidence: which day, which movement, prescribed -> performed, the RPE it finished at
    hammer = next(a for a in weeks["2026-09-14"]["added"] if a["date"] == "2026-09-20" and a["movement"] == "Hammer Curl (Dumbbell)")
    assert (hammer["programmed_sets"], hammer["performed_sets"], hammer["max_rpe"]) == (2, 4, 9.5)
    assert "2026-09-07" in row["detail"] and "+4 net" in row["detail"]


def test_the_in_progress_week_is_reported_but_never_counted():
    rows = [_session("2026-09-14", _PUSH_0914), _session("2026-09-22", _LEGS_0922)]
    row = _row(_block(rows))
    assert row["state"] == "clear", "the week of 09-07 had no session, so it is not above; 09-21's week is in progress"
    cur = row["evidence"]["weeks"][-1]
    assert cur["week_start"] == "2026-09-21" and cur["complete"] is False and cur["verdict"] == "above"
    assert row["evidence"]["run_weeks"] == 1
    assert "in progress" in row["detail"]


# ══ 3. NO-FIRE ═══════════════════════════════════════════════════════════════════════════
def test_one_week_above_is_clear_with_the_run_stated():
    row = _row(_block(_no_fire_rows()))
    assert row["state"] == "clear"
    assert row["evidence"]["run_weeks"] == 1
    wk = next(w for w in row["evidence"]["weeks"] if w["week_start"] == "2026-09-07")
    assert wk["verdict"] == "at_or_below" and wk["net_sets"] == 0 and wk["added"] == []


def test_a_set_skipped_elsewhere_nets_against_a_set_added():
    rows = _no_fire_rows()
    rows[1] = _session("2026-09-14", [("barbell_bench_press", 6, 7, None), ("db_shoulder_press", 3, 2, None)])
    rows[2] = _session("2026-09-20", _at_prescription(_PULL_0920))
    ev = self_added_volume.evaluate(rows, TODAY, THRESHOLD)
    wk = next(w for w in ev["weeks"] if w["week_start"] == "2026-09-14")
    assert wk["net_sets"] == 0 and wk["added_sets"] == 1 and wk["verdict"] == "at_or_below"


# ══ 4. unknown is not clear ══════════════════════════════════════════════════════════════
def test_an_empty_window_is_unknown_never_clear():
    row = _row(_block([]))
    assert row["state"] == "unknown" and "no Hevy session" in row["detail"]


def test_a_deciding_week_of_unmatched_sessions_is_unknown():
    rows = _fire_rows()
    rows[0] = _session("2026-09-12", [], status="ad_hoc")
    row = _row(_block(rows))
    assert row["state"] == "unknown"
    wk = next(w for w in row["evidence"]["weeks"] if w["week_start"] == "2026-09-07")
    assert wk["verdict"] == "unassessable" and wk["unmatched"][0]["status"] == "ad_hoc"


def test_no_rows_supplied_is_unknown_and_a_failed_read_is_read_failed():
    assert _row(plan_engine.constraint_block(date=TODAY))["state"] == "unknown"
    failed = plan_engine.input_status(plan_engine.READ_FAILED, error="TimeoutError: ddb")
    row = _row(plan_engine.constraint_block(date=TODAY, input_status={"hevy_workouts_prescription_window": failed}))
    assert row["state"] == "read_failed" and "TimeoutError" in row["detail"]


def test_a_tombstoned_row_is_not_evidence():
    rows = _fire_rows()
    rows[0]["tombstone"] = True
    assert self_added_volume.evaluate(rows, TODAY, THRESHOLD)["state"] == "clear"


# ══ 5. the counts are adherence's, never re-counted ══════════════════════════════════════
def test_the_module_reads_adherence_counts_not_the_logged_set_list():
    """A row whose `exercises[].sets` shows 10 sets but whose stored adherence says 3 of 3 is AT
    prescription: the per-movement count is `health.adherence_calc`'s, stored at ingest."""
    rows = _no_fire_rows()
    rows[0]["exercises"][0]["sets"] = rows[0]["exercises"][0]["sets"] * 10
    assert self_added_volume.evaluate(rows, TODAY, THRESHOLD)["state"] == "clear"


def test_the_stored_block_is_what_adherence_calc_writes():
    """The keys this module reads are the ones `calculate_adherence` returns — pinned by source,
    so a rename on the writer reds here instead of silently reading zero."""
    src = (REPO / "lambdas/health/adherence_calc.py").read_text()
    for key in ('"movement_key"', '"programmed_sets"', '"performed_sets"', '"movements"', '"extra"', '"status": "matched"'):
        assert key in src, key


# ══ 6. mutation controls ═════════════════════════════════════════════════════════════════
def test_mutation_flattening_week_one_stops_the_fire():
    assert self_added_volume.evaluate(_fire_rows(), TODAY, THRESHOLD)["state"] == "tripped"
    assert self_added_volume.evaluate(_no_fire_rows(), TODAY, THRESHOLD)["state"] == "clear"


def test_mutation_the_engine_reads_the_rows_threshold_not_a_literal(monkeypatch):
    patched = copy.deepcopy(owner_redlines.TRIPWIRES)
    next(t for t in patched if t["id"] == "self_added_volume")["threshold_weeks"] = 3
    monkeypatch.setattr(owner_redlines, "TRIPWIRES", patched)
    row = _row(_block(_fire_rows()))
    assert row["state"] != "tripped", "a threshold of 3 weeks must not fire on a 2-week run"


# ══ 7. stage 1 reads the partition through the real path ═════════════════════════════════
def test_stage_1_reads_the_hevy_partition_and_reports_the_row(monkeypatch):
    import test_plan_input_read_state_4072 as h

    import mcp.tools_plan as tp

    monkeypatch.setattr(tp, "pacific_today", lambda: TODAY)
    rows = _fire_rows() + [_session("2026-08-20", _PULL_0912)]  # outside the window: never read
    h._wire(monkeypatch, rows + h._whoop_rows())
    out = h._stage1(TODAY)
    block = out["constraint_block"]
    row = h._row(out, "self_added_volume")
    assert row["state"] == "tripped" and row["input_state"]["state"] == "measured"
    assert block["inputs"]["hevy_workouts_prescription_window"]["state"] == "measured"
    assert row["evidence"]["window"] == {"start": "2026-08-31", "end": TODAY}


def test_stage_1_names_a_raising_read_as_read_failed(monkeypatch):
    import test_plan_input_read_state_4072 as h

    import mcp.tools_plan as tp

    monkeypatch.setattr(tp, "pacific_today", lambda: TODAY)
    h._wire(monkeypatch, h._whoop_rows(), raise_on_pk="SOURCE#hevy")
    row = h._row(h._stage1(TODAY), "self_added_volume")
    assert row["state"] == "read_failed"


# ══ 8. the critic reads the same run ═════════════════════════════════════════════════════
def test_the_nutrition_critic_input_is_the_same_evaluation(monkeypatch):
    import mcp.nutrition_critics_inputs as nci

    monkeypatch.setattr(nci, "query_source", lambda source, start, end: _fire_rows())
    assert nci._above_prescription_weeks(TODAY) == (2, False)
    monkeypatch.setattr(nci, "query_source", lambda source, start, end: [])
    assert nci._above_prescription_weeks(TODAY) == (None, False), "an empty window is unknown to the critic, not 0"

    def boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(nci, "query_source", boom)
    assert nci._above_prescription_weeks(TODAY) == (None, True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

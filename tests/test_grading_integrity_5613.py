"""tests/test_grading_integrity_5613.py — owner integrity items 1 and 7 (2026-11-02, epic #5607).

1. **The fact-checker reads a stub food record as missing.** The coach quality gate's served-fact check
   (`coach_input_facts.served_fact_findings`) judged cited protein figures against a series built from
   UNFILTERED MacroFactor rows, so a summary-only stub (entries_count 0, no food_log, a pre-filled 80 kcal /
   15 g) counted as 15 g eaten: "the last 3 logged days averaged 15 g" passed. The fixture is the REAL window
   for 2026-11-02 (10-04 → 10-30 rows; 10-28/29/30 are the stubs; 10-20 is a real low day, 779 kcal / 98 g
   with 12 entries), read read-only from DynamoDB; each food_log entry is a numbered placeholder so the count
   is real and no food is named.

7. **Versioned rules never silently rewrite history** (`coach.grade_corrections` THE INVARIANTS): a settled
   grade changes only through `apply_correction`; a version stamp is only written beside the text that
   version produced (the restate path records a `basis="restate"` correction instead of a bare stamp); and
   re-grade selection excludes any row with a correction history, keyed on structure, not wording.
   The structural half (no other writer) is `tests/test_settled_grade_writers_5613.py`.

No assertion here reads the clock: every function under test takes the day it reasons about.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import regrade_predictions as regrade  # noqa: E402
from coach import (
    coach_input_facts as cif,  # noqa: E402
    grade_corrections as gc,  # noqa: E402
)
from coach.grading_quality import is_zero_entry_day  # noqa: E402
from health import nutrition_logging as nl  # noqa: E402

TODAY = "2026-11-02"
STUBS = ("2026-10-28", "2026-10-29", "2026-10-30")
FIXTURE = os.path.join(_REPO, "tests", "fixtures", "macrofactor_window_2026_11_02_5613.json")


def _real_rows() -> list:
    rows = json.load(open(FIXTURE, encoding="utf-8"))["rows"]
    # The shape `fetch_macrofactor_window` returns: boto3 Decimals.
    return [{k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]


def _facts(series: list, rows: list) -> dict:
    return {"nutrition": cif.nutrition_record(rows, TODAY), "protein_series": series}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the fact-checker
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_the_fixture_is_the_real_window_shape():
    rows = _real_rows()
    by_day = {r["date"]: r for r in rows}
    assert len(rows) == 27 and min(by_day) == "2026-10-04" and max(by_day) == "2026-10-30"
    for d in STUBS:
        r = by_day[d]
        assert (r["entries_count"], r["food_log"], float(r["total_calories_kcal"]), float(r["total_protein_g"])) == (0, [], 80.0, 15.0)
        assert is_zero_entry_day(r)
    low = by_day["2026-10-20"]
    assert (low["entries_count"], len(low["food_log"]), float(low["total_calories_kcal"]), float(low["total_protein_g"])) == (
        12,
        12,
        779.0,
        98.0,
    )
    assert not is_zero_entry_day(low), "a real low day is a log"


def test_the_fact_checkers_series_before_and_after_on_the_real_rows():
    rows = _real_rows()
    before = nl.protein_series(rows)  # what served_run_facts handed the gate before #5613
    after = cif.logged_protein_series(rows)
    assert len(before) == 27 and [(d, float(g)) for d, g in before[-3:]] == [(d, 15.0) for d in STUBS]
    assert len(after) == 24 and not [d for d, _g in after if d in STUBS]
    assert ("2026-10-20", Decimal("98")) in after, "a real low day stays a reading"
    assert [(d, float(g)) for d, g in after[-3:]] == [("2026-10-25", 158.0), ("2026-10-26", 126.0), ("2026-10-27", 111.0)]
    assert nl.protein_window(before)["mean"] == 127.8 and nl.protein_window(after)["mean"] == 141.9
    # The gate's series now agrees with the logging record the coach was handed (#5603): one window, one n.
    rec = cif.nutrition_record(rows, TODAY)
    assert (rec["protein_avg_g"], rec["protein_avg_days"], rec["days_logged"]) == (141.9, 24, 24)


def test_served_run_facts_hands_the_gate_the_logged_series(monkeypatch):
    rows = _real_rows()
    monkeypatch.setattr(cif, "morning_note_fact", lambda table, today: {"state": "absent"})
    monkeypatch.setattr(cif._cf, "clinical_context_block", lambda table, published=True: "")
    monkeypatch.setattr(cif, "nutrition_charter_context", lambda data, today: None)
    monkeypatch.setattr(cif, "_plan_facts", lambda: None)
    facts = cif.served_run_facts({"date": "2026-11-01", "macrofactor_window": rows}, table=None, today=TODAY)
    assert facts["protein_series"] == cif.logged_protein_series(rows)
    assert facts["nutrition"]["protein_avg_days"] == len(facts["protein_series"]) == 24


def test_a_stub_average_is_a_contradiction_now_and_passed_before():
    rows = _real_rows()
    line = "Over the last 3 logged days protein averaged 15 g."
    assert cif.served_fact_findings(line, _facts(nl.protein_series(rows), rows), TODAY) == [], "the defect: it passed"
    found = cif.served_fact_findings(line, _facts(cif.logged_protein_series(rows), rows), TODAY)
    assert [(f["metric"], f["cited"], f["canonical"]) for f in found] == [("protein_g", 15.0, 131.7)]


def test_this_month_is_the_served_window_and_128_contradicts_the_served_141_9():
    rows = _real_rows()
    facts = _facts(cif.logged_protein_series(rows), rows)
    found = cif.served_fact_findings("Protein averaged 128 g this month.", facts, TODAY)
    assert [(f["cited"], f["canonical"]) for f in found] == [(128.0, 141.9)]
    assert cif.served_fact_findings("Protein averaged 142 g this month.", facts, TODAY) == []
    assert cif.served_fact_findings("Protein averaged 142 g over the last 24 logged days.", facts, TODAY) == []
    assert cif._named_windows("the past month") == [nl.WINDOW_DAYS] and cif._named_windows("last month") == []


def test_a_real_low_day_is_still_judged_as_a_reading():
    """10-20 (779 kcal / 98 g, 12 entries) stays IN the window — the filter drops stubs, never low days: the
    seven logged days ending 10-21 are 10-15 → 10-21 with 10-20 counted, averaging 122.3 g."""
    rows = [r for r in _real_rows() if r["date"] <= "2026-10-21"]
    facts = _facts(cif.logged_protein_series(rows), rows)
    last7 = facts["protein_series"][-7:]
    assert [d for d, _g in last7] == [f"2026-10-{d}" for d in range(15, 22)] and ("2026-10-20", Decimal("98")) in last7
    win = nl.protein_window(facts["protein_series"], 7)
    assert win["n"] == 7 and win["mean"] == 122.3
    assert cif.served_fact_findings("Protein averaged 122 g over the last 7 logged days.", facts, "2026-10-22") == []


def test_the_moves_sheet_serves_the_logged_series(monkeypatch):
    from coach import coach_moves_sheet as cms

    class _Empty:
        def query(self, **_k):
            return {"Items": []}

        def get_item(self, **_k):
            return {}

    rows = _real_rows()
    monkeypatch.setattr(cif, "fetch_macrofactor_window", lambda table, today: rows)
    inputs = cms.read_inputs(_Empty(), TODAY, [], {})
    assert inputs["protein_series"] == cif.logged_protein_series(rows) and inputs["nutrition"]["days_logged"] == 24


def test_the_domain_pack_never_names_a_stub_as_the_most_recent_log(monkeypatch):
    from coach import coach_domain_facts as cdf

    rows = _real_rows()
    monkeypatch.setattr(cdf, "_query_source", lambda table, source, start, end: list(rows) if source == "macrofactor" else [])
    lines = cdf._nutrition_pack(SimpleNamespace(get_item=lambda **_k: {}), TODAY)
    assert "Most recent food log: 2026-10-27 (1080 kcal)." in lines, lines


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7. versioned rules never silently rewrite history
# ══════════════════════════════════════════════════════════════════════════════════════════


class ConditionFailed(Exception):
    pass


class Table:
    """Keyed fake: SET (plain / list_append(if_not_exists) / if_not_exists) and `a = :v` /
    `attribute_not_exists(a)` conditions joined by AND."""

    def __init__(self, *rows):
        self.items = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.writes: list = []

    def put_item(self, Item=None, **_k):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        self.writes.append(("put", Item["sk"]))

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        for clause in (kw.get("ConditionExpression") or "").split(" AND "):
            clause = clause.strip()
            if clause.startswith("attribute_not_exists("):
                if names.get(clause[21:-1], clause[21:-1]) in item:
                    raise ConditionFailed(clause)
            elif " = " in clause:
                lhs, rhs = (x.strip() for x in clause.split(" = ", 1))
                if item.get(names.get(lhs, lhs)) != values.get(rhs):
                    raise ConditionFailed(clause)
        depth, cur, parts = 0, "", []
        for ch in UpdateExpression.split("SET", 1)[-1]:
            depth += (ch == "(") - (ch == ")")
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for a in parts:
            lhs, rhs = (x.strip() for x in a.split("=", 1))
            attr = names.get(lhs, lhs)
            if rhs.startswith("list_append(if_not_exists("):
                base, empty, appended = rhs[len("list_append(if_not_exists(") : -1].replace(")", "").replace(" ", "").split(",")
                item[attr] = list(item.get(base, values[empty])) + list(values[appended])
            elif rhs.startswith("if_not_exists("):
                base, default = rhs[len("if_not_exists(") : -1].replace(" ", "").split(",")
                item.setdefault(attr, values[default])
            else:
                item[attr] = values[rhs]
        self.writes.append(("update", Key["sk"]))


NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
NOTES_1_0 = json.dumps({"reason": "1.0 read the 15 g stub", "algo_version": "1.0"})
NOTES_1_1 = json.dumps({"reason": "1.1: the stub day is missing", "algo_version": "1.1", "quality_flags": ["logging_gap"]})


def _row(**over):
    base = {
        "pk": "COACH#mind_coach",
        "sk": "PREDICTION#pred_20261015_protein_recovery",
        "prediction_id": "pred_20261015_protein_recovery",
        "coach_id": "mind_coach",
        "status": "refuted",
        "outcome": "refuted",
        "outcome_date": "2026-10-29",
        "outcome_notes": NOTES_1_0,
        "created_date": "2026-10-15",
        "evaluation": {"type": "directional", "metric": "total_protein_g", "condition": "up", "evaluation_window_days": 14},
    }
    base.update(over)
    return base


def test_is_settled_names_the_decided_rows_and_leaves_the_provisional_ones():
    assert not gc.is_settled(_row(status="pending", outcome=None, outcome_notes=None))
    assert gc.is_settled(_row())
    assert not gc.is_settled(_row(status="inconclusive", outcome_notes=json.dumps({"algo_version": "1.0", "grading_open": True})))
    assert not gc.is_settled(_row(status="inconclusive", outcome_notes=json.dumps({"reason": "#813 duplicate grader"})))
    assert gc.is_settled(_row(status="inconclusive", outcome_notes=json.dumps({"algo_version": "1.0"})))
    corrected_provisional = _row(
        status="inconclusive", outcome_notes=json.dumps({"algo_version": "1.1", "grading_open": True}), corrections=[{"reason": "r"}]
    )
    assert gc.is_settled(corrected_provisional), "a corrected row is the ledger's, even when its corrected notes read provisional"


def test_the_graders_write_refuses_a_settled_row_and_a_row_that_moved_since_the_read():
    t = Table(_row())
    ev = {"prediction_id": "x", "status": "confirmed", "evaluated_date": TODAY}
    with pytest.raises(gc.SettledGradeError):
        gc.write_first_grade(t, _row(), ev, outcome_notes=NOTES_1_1, evaluator_version="1.1")
    assert t.writes == []
    pending = _row(status="pending", outcome=None, outcome_notes=None)
    t = Table(dict(pending, status="refuted"))  # corrected between the grader's read and its write
    with pytest.raises(ConditionFailed):
        gc.write_first_grade(t, pending, ev, outcome_notes=NOTES_1_1, evaluator_version="1.1")
    t = Table(pending)
    assert gc.write_first_grade(t, pending, ev, outcome_notes=NOTES_1_1, evaluator_version="1.1")
    stored = t.items[(pending["pk"], pending["sk"])]
    assert stored["status"] == "confirmed" and gc.grade_text_version(stored) == stored["evaluator_version"] == "1.1"


def test_the_evaluators_write_back_is_refused_on_a_settled_row_and_moves_nothing(monkeypatch):
    from coach import coach_prediction_evaluator as cpe

    t = Table(_row())
    monkeypatch.setattr(cpe, "table", t)
    assert cpe._update_prediction_status(_row(), {"prediction_id": "x", "status": "confirmed", "evaluated_date": TODAY}) is False
    assert t.items[(_row()["pk"], _row()["sk"])]["status"] == "refuted" and t.writes == []


def test_a_restate_keeps_the_verdict_and_moves_text_flags_and_version_together():
    row = _row(quality_flags=None)
    t = Table(row)
    corrected = {"status": "refuted", "outcome_date": row["outcome_date"], "outcome_notes": NOTES_1_1, "quality_flags": ["logging_gap"]}
    e = gc.apply_correction(t, row, corrected, reason="#5533 (c) restate", evaluator_version="1.1", now=NOW, basis=gc.RESTATE)
    stored = t.items[(row["pk"], row["sk"])]
    assert (e["basis"], e["verdict_changed"], e["original_status"], e["corrected_status"]) == ("restate", False, "refuted", "refuted")
    assert stored["status"] == "refuted" and stored["outcome_date"] == "2026-10-29", "the verdict and its date stand"
    assert gc.grade_text_version(stored) == stored["evaluator_version"] == "1.1", "the stamp sits beside the text that version wrote"
    assert stored["original_grade"]["outcome_notes"] == NOTES_1_0 and stored["quality_flags"] == ["logging_gap"]
    with pytest.raises(ValueError):
        gc.apply_correction(t, row, dict(corrected, status="confirmed"), reason="r", evaluator_version="1.1", basis=gc.RESTATE)
    with pytest.raises(ValueError):
        gc.apply_correction(t, row, corrected, reason="r", evaluator_version="1.1", basis=gc.RULING)  # a ruling names who ruled


def test_the_regrade_restate_path_never_writes_a_bare_version_stamp():
    """The 2026-11-01 run stamped 1.1 beside 1.0 text on nine rows. The restate path now records a correction
    whose text, flags and version are the fixed grader's together — and skips a row whose text 1.1 wrote."""
    stale, current = _row(), _row(sk="PREDICTION#p_current", prediction_id="p_current", outcome_notes=NOTES_1_1, evaluator_version="1.1")
    t = Table(stale, current)
    after = {"status": "refuted", "outcome_date": TODAY, "outcome_notes": NOTES_1_1, "quality_flags": ["logging_gap"], "baseline": None}
    entries = [
        {"pk": r["pk"], "sk": r["sk"], "action": regrade.RESTATE, "row": r, "after": dict(after), "reasons": [regrade.FOOD]}
        for r in (stale, current)
    ]
    done, _item = regrade.apply(t, entries, SimpleNamespace(ALGO_VERSION="1.1"), today=TODAY, summ={"issue": "#5533"}, now=NOW)
    assert done[regrade.RESTATE] == 1 and done["failed"] == 0
    s = t.items[(stale["pk"], stale["sk"])]
    assert gc.grade_text_version(s) == s["evaluator_version"] == "1.1" and s["corrections"][0]["basis"] == "restate"
    assert s["outcome_date"] == "2026-10-29" and s["original_grade"]["outcome_notes"] == NOTES_1_0
    assert t.items[(current["pk"], current["sk"])] == current, "text the current version wrote has nothing to restate"
    for (_pk, _sk), r in t.items.items():
        if _sk.startswith("PREDICTION#") and r.get("evaluator_version"):
            assert gc.grade_text_version(r) == r["evaluator_version"], _sk


def test_selection_excludes_a_ruled_row_whatever_its_wording_or_version():
    """A rule bump must never re-grade an owner ruling: selection keys on the correction history's presence."""
    zero = {"2026-10-29"}
    ruled = _row(
        status="expired",
        corrections=[{"reason": "owner ruling 2026-11-02: not gradable as worded", "evaluator_version": "1.1", "basis": "ruling"}],
        original_grade={"status": "refuted", "snapshot_at": "2026-11-03T02:47:32Z"},
    )
    plain = _row()
    for version in ("1.1", "1.2"):
        assert regrade.reasons_for(ruled, today=TODAY, zero_days=zero, retired_ids=(), evaluator_version=version) == []
        assert regrade.reasons_for(plain, today=TODAY, zero_days=zero, retired_ids=(), evaluator_version=version) == [regrade.FOOD]
    snapshot_only = _row(original_grade={"status": "refuted", "snapshot_at": "x"})
    assert gc.has_correction_history(snapshot_only) and not gc.has_correction_history(plain)
    assert regrade.reasons_for(snapshot_only, today=TODAY, zero_days=zero, retired_ids=(), evaluator_version="1.2") == []


def test_every_entry_carries_structured_provenance():
    row = _row()
    t = Table(row)
    e = gc.apply_correction(
        t,
        row,
        {"status": "expired", "outcome_date": TODAY, "outcome_notes": NOTES_1_1},
        reason="owner ruling",
        evaluator_version="1.1",
        now=NOW,
        basis=gc.RULING,
        ruled_by="owner",
    )
    assert (e["basis"], e["ruled_by"], e["verdict_changed"]) == ("ruling", "owner", True)
    assert set(gc.ENTRY_FIELDS) <= set(e)
    ledger = t.items[(row["pk"], f"CORRECTION#{row['prediction_id']}#{e['corrected_at']}")]
    assert ledger["basis"] == "ruling" and ledger["ruled_by"] == "owner"


def test_the_plan_names_a_row_the_current_version_already_wrote_current_not_restate():
    after = {"status": "refuted"}
    assert regrade._plan_action(_row(), "refuted", after, "1.1") == regrade.RESTATE
    assert regrade._plan_action(_row(outcome_notes=NOTES_1_1), "refuted", after, "1.1") == regrade.CURRENT
    assert regrade._plan_action(_row(outcome_notes=NOTES_1_1), "refuted", {"status": "confirmed"}, "1.1") == regrade.REGRADE

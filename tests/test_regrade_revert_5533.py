"""tests/test_regrade_revert_5533.py — the re-grade is reversible to the exact pre-change state, on the record
(owner ask, 2026-11-01): apply → revert restores every snapshotted field and removes the ones that did not
exist; the audit trail reads correction → reversal; running either step twice is safe.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import revert_regrade as revert  # noqa: E402
from coach import grade_corrections as gc  # noqa: E402


class ConditionFailed(Exception):
    pass


class Table:
    """A keyed fake honouring SET (plain, list_append(if_not_exists(..)), if_not_exists(..)), REMOVE, and the
    conditions the code under test writes (`#x = :v`, `attribute_not_exists(x)`, joined by AND)."""

    def __init__(self):
        self.items: dict = {}
        self.writes: list = []

    def seed(self, *rows):
        for r in rows:
            self.items[(r["pk"], r["sk"])] = dict(r)

    def put_item(self, Item=None, **_):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        self.writes.append(("put", Item["sk"]))

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, ConditionExpression=None, **_
    ):
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        for clause in (ConditionExpression or "").split(" AND "):
            clause = clause.strip()
            if not clause:
                continue
            if clause.startswith("attribute_not_exists("):
                if names.get(clause[21:-1], clause[21:-1]) in item:
                    raise ConditionFailed(clause)
            elif " = " in clause:
                lhs, rhs = (x.strip() for x in clause.split(" = ", 1))
                if item.get(names.get(lhs, lhs)) != values.get(rhs):
                    raise ConditionFailed(clause)
        expr = UpdateExpression.strip()
        set_part, remove_part = expr, ""
        if expr.startswith("REMOVE "):
            set_part, remove_part = "", expr[len("REMOVE ") :]
        elif " REMOVE " in expr:
            set_part, remove_part = expr.split(" REMOVE ", 1)
        if set_part.startswith("SET "):
            depth, cur, parts = 0, "", []
            for ch in set_part[4:]:
                depth += ch == "("
                depth -= ch == ")"
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
            for part in parts:
                lhs, rhs = (x.strip() for x in part.split("=", 1))
                key = names.get(lhs, lhs)
                if rhs.startswith("list_append(if_not_exists("):
                    inner = rhs[len("list_append(if_not_exists(") : -1]
                    _f, default, appended = (x.strip() for x in inner.replace(")", "").split(","))
                    item[key] = list(item.get(key, values[default])) + list(values[appended])
                elif rhs.startswith("if_not_exists("):
                    _f, default = (x.strip() for x in rhs[len("if_not_exists(") : -1].split(","))
                    item.setdefault(key, values[default])
                else:
                    item[key] = values[rhs]
        for name in [x.strip() for x in remove_part.split(",") if x.strip()]:
            item.pop(names.get(name, name), None)
        self.writes.append(("update", Key["sk"]))


def _row(**over):
    base = {
        "pk": "COACH#sleep_coach",
        "sk": "PREDICTION#pred_20261002_recovery_running_average",
        "prediction_id": "pred_20261002_recovery_running_average",
        "coach_id": "sleep_coach",
        "claim_natural": "Recovery running average shows downward movement over the last seven days.",
        "status": "confirmed",
        "outcome": "confirmed",
        "outcome_date": "2026-10-16",
        "outcome_notes": "recovery went up — the call was for it to go up",
        "baseline": {"rule": "nothing_changes", "right": False},
        "created_date": "2026-10-02",
    }
    base.update(over)
    return base


T0 = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)
CORRECTED = {
    "status": "refuted",
    "outcome_date": "2026-10-16",
    "outcome_notes": "re-baselined after the HR regime marker",
    "quality_flags": [],
    "baseline": {"rule": "nothing_changes", "right": True},
}


def _apply(table, row):
    return gc.apply_correction(table, row, CORRECTED, reason="#5533 — hr_regime", evaluator_version="1.1", now=T0)


def test_apply_then_revert_restores_the_exact_pre_change_row_and_keeps_the_trail():
    t = Table()
    row = _row()
    t.seed(row)
    before = {k: row.get(k) for k in gc.ORIGINAL_FIELDS}
    _apply(t, row)
    corrected = t.items[(row["pk"], row["sk"])]
    assert corrected["status"] == "refuted" and corrected["evaluator_version"] == "1.1" and corrected["quality_flags"] == []
    assert corrected["original_grade"]["status"] == "confirmed" and "quality_flags" not in corrected["original_grade"]
    e = gc.revert_correction(t, dict(corrected), reason="owner-authorised restore", now=T1)
    assert (
        e
        and e["reverts"] is True
        and e["corrected_status"] == "confirmed"
        and e["restores_snapshot_at"] == corrected["original_grade"]["snapshot_at"]
    )
    after = t.items[(row["pk"], row["sk"])]
    assert {k: after.get(k) for k in gc.ORIGINAL_FIELDS} == before, "every snapshotted field is back; the two the snapshot lacked are gone"
    assert "quality_flags" not in after and "evaluator_version" not in after
    assert after["original_grade"] == corrected["original_grade"], "the proof of the first grade is never removed"
    assert [x.get("reverts", False) for x in after["corrections"]] == [False, True], "the trail reads correction → reversal"
    ledger = sorted(sk for (_pk, sk) in t.items if sk.startswith("CORRECTION#pred_"))
    assert len(ledger) == 2 and t.writes[0][0] == "put" and t.writes[2][0] == "put", "the ledger row is written before the row, both times"


def test_running_the_revert_twice_is_a_no_op_and_the_correction_cannot_silently_reapply():
    t = Table()
    row = _row()
    t.seed(row)
    _apply(t, row)
    corrected = dict(t.items[(row["pk"], row["sk"])])
    assert gc.revert_correction(t, corrected, reason="r", now=T1)
    restored = dict(t.items[(row["pk"], row["sk"])])
    assert gc.reverted_already(restored)
    n = len(t.writes)
    assert gc.revert_correction(t, restored, reason="r", now=T1) is None and len(t.writes) == n, "a second revert writes nothing"
    # a second correction run: the planner's own idempotence still sees the #5533 entry → not selected
    assert gc.already_corrected(restored, evaluator_version="1.1", reason_prefix="#5533")
    # and a stale re-apply against the live row is refused by the condition, not written
    with pytest.raises(ConditionFailed):
        gc.apply_correction(t, corrected, CORRECTED, reason="#5533 — hr_regime", evaluator_version="1.1", now=T1)


def test_a_first_grade_reverts_to_pending_and_a_restate_unstamps_once():
    t = Table()
    pending = _row(
        sk="PREDICTION#pred_20260906_sealed",
        prediction_id="pred_20260906_sealed",
        status="pending",
        outcome=None,
        outcome_date=None,
        outcome_notes=None,
        baseline=None,
    )
    pending = {k: v for k, v in pending.items() if v is not None}
    t.seed(pending)
    # the evaluator's own write path graded it (simulated), then the ledger entry with update_grade=False
    t.items[(pending["pk"], pending["sk"])].update(
        status="confirmed", outcome="confirmed", outcome_date="2026-10-31", outcome_notes="graded by the evaluator"
    )
    gc.apply_correction(
        t,
        pending,
        {"status": "confirmed", "outcome_date": "2026-10-31", "outcome_notes": "graded"},
        reason="#5533 — retired",
        evaluator_version="1.1",
        now=T0,
        update_grade=False,
    )
    graded = dict(t.items[(pending["pk"], pending["sk"])])
    assert graded["status"] == "confirmed" and graded["original_grade"]["status"] == "pending"
    assert gc.revert_correction(t, graded, reason="r", now=T1)
    back = t.items[(pending["pk"], pending["sk"])]
    assert back["status"] == "pending" and all(k not in back for k in ("outcome", "outcome_date", "outcome_notes", "baseline"))
    # restate: stamped once, un-stamped once
    stamped = _row(sk="PREDICTION#pred_x", prediction_id="pred_x")
    t.seed(stamped)
    assert gc.stamp_quality(t, stamped, ["logging_gap"], evaluator_version="1.1")
    live = dict(t.items[(stamped["pk"], stamped["sk"])])
    assert gc.unstamp_quality(t, live, evaluator_version="1.1") is True
    live2 = t.items[(stamped["pk"], stamped["sk"])]
    assert "quality_flags" not in live2 and "evaluator_version" not in live2
    assert gc.unstamp_quality(t, dict(live2), evaluator_version="1.1") is False


def test_the_script_selects_exactly_the_touched_rows_and_nothing_after_a_revert():
    t = Table()
    a, b, c = _row(), _row(sk="PREDICTION#pred_b", prediction_id="pred_b"), _row(sk="PREDICTION#pred_c", prediction_id="pred_c")
    t.seed(a, b, c)
    _apply(t, a)
    gc.stamp_quality(t, b, ["low_power"], evaluator_version="1.1")
    rows = {
        "COACH#sleep_coach": [dict(v) for (pk, _sk), v in t.items.items() if pk == "COACH#sleep_coach" and _sk.startswith("PREDICTION#")]
    }
    plan = revert.select(rows)
    assert sorted((e["sk"], e["action"]) for e in plan) == [
        ("PREDICTION#pred_20261002_recovery_running_average", "revert"),
        ("PREDICTION#pred_b", "unstamp"),
    ]
    assert "dry run" in revert.report(plan) or "revert" in revert.report(plan)
    done = revert.apply(t, plan, now=T1)
    assert done == {"revert": 1, "unstamp": 1, "skipped": 0, "failed": 0}
    assert any(sk.startswith(gc.SUMMARY_PREFIX) for (_pk, sk) in t.items), "the revert run leaves its own summary row"
    rows2 = {
        "COACH#sleep_coach": [dict(v) for (pk, _sk), v in t.items.items() if pk == "COACH#sleep_coach" and _sk.startswith("PREDICTION#")]
    }
    assert revert.select(rows2) == [], "a second run selects nothing"
    assert t.items[(c["pk"], c["sk"])] == c, "an untouched row is untouched"

"""tests/test_evaluation_hold_5607.py — the owner's targeted, logged evaluation hold (#5607, ruling 2026-11-03, item 2).

"Prevent further suspect grading first. Authorize a targeted, logged evaluation hold on the identified pending
calls while their rulings are reviewed ... Leave unaffected evaluation running."

Pinned here, offline, on a frozen clock (the evaluator harness of
``tests/test_coach_prediction_evaluator_behavior.py``, reused — its autouse ``env`` fixture cuts every AWS edge):

  * the evaluator skips a held row before any grading or expiry logic — no write, ``stats["held"]`` counts it —
    while an unheld row in the SAME batch is still graded;
  * a held row past its 2x window is NOT expired, and a held qualitative row is NOT retired;
  * ``grade_corrections.write_first_grade`` refuses a held row and is conditional on it carrying no hold;
  * ``scripts/evaluation_hold.py``: the dry run writes nothing; ``--apply`` writes the audit row FIRST, then one
    conditional update touching only ``evaluation_hold`` (exact expressions); release stashes the released hold;
  * ``/api/ledger_export`` flags a held item (``grading_held``, a plain reason) and keeps its status ``pending``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timezone

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_coach_prediction_evaluator_behavior as beh  # noqa: E402
from coach import evaluation_hold, grade_corrections  # noqa: E402

TODAY, days_before, ev, learning_rows, prediction, seed_metric = (
    beh.TODAY,
    beh.days_before,
    beh.ev,
    beh.learning_rows,
    beh.prediction,
    beh.seed_metric,
)
# Loaded by PATH: a bare `import evaluation_hold` resolves to lambdas/coach/evaluation_hold.py whenever another
# test has put lambdas/coach on sys.path first (suite order).
_spec = importlib.util.spec_from_file_location("evaluation_hold_script_5607", os.path.join(_REPO, "scripts", "evaluation_hold.py"))
hold_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hold_script)
env = beh.env  # the harness's autouse fixture: frozen clock, every AWS edge cut


@pytest.fixture
def tbl(env):
    return env.table


REASON = "Held for review under the owner's 2026-11-03 ruling: the call reads as an opinion or an untested condition."
HOLD = {"reason": REASON, "set_at": "2026-11-03T18:00:00Z", "set_by": "owner", "ruling_ref": "#5607"}


def _hrv_above_threshold(t):
    seed_metric(t, "whoop", "hrv", {days_before(n): 70 for n in range(0, 45)})


# ── the evaluator ─────────────────────────────────────────────────────────────────────────


def test_a_held_row_is_skipped_while_an_unheld_row_in_the_same_batch_is_graded(tbl):
    _hrv_above_threshold(tbl)
    held = prediction(pred_id="pred_held", created_date=days_before(20), evaluation_hold=HOLD)
    free = prediction(pred_id="pred_free", created_date=days_before(20))
    evaluations, stats = ev._evaluate_all([held, free], TODAY)

    assert stats["held"] == 1
    assert [e["prediction_id"] for e in evaluations] == ["pred_free"]
    written = {u["Key"]["sk"] for u in tbl.updates}
    assert "PREDICTION#pred_free" in written, "the unaffected call must still be graded"
    assert "PREDICTION#pred_held" not in written
    assert all(r.get("prediction_id") != "pred_held" for r in learning_rows(tbl))


def test_a_held_row_past_its_2x_window_is_not_expired(tbl):
    held = prediction(pred_id="pred_held", created_date=days_before(60), evaluation_hold=HOLD)
    free = prediction(pred_id="pred_free", created_date=days_before(60))
    evaluations, stats = ev._evaluate_all([held, free], TODAY)

    assert (stats["held"], stats["expired"]) == (1, 1)
    assert [e["prediction_id"] for e in evaluations] == ["pred_free"]
    assert {u["Key"]["sk"] for u in tbl.updates if u["Key"]["sk"].startswith("PREDICTION#")} == {"PREDICTION#pred_free"}


def test_the_hold_is_checked_before_the_window_and_the_grader(tbl, monkeypatch):
    """Not even the window arithmetic or a grader runs for a held row — a broken spec cannot error it either."""
    calls = []
    monkeypatch.setattr(ev, "_get_effective_window", lambda *a, **k: calls.append(a) or 14)
    held = prediction(pred_id="pred_held", created_date="not a date", evaluation_hold=HOLD)
    evaluations, stats = ev._evaluate_all([held], TODAY)
    assert (evaluations, stats["held"], stats["skipped_error"], calls) == ([], 1, 0, [])


def test_the_summary_log_line_names_the_held_count(tbl, monkeypatch):
    lines = []

    class _Rec:
        def info(self, msg, *a, **_k):
            lines.append(msg % a if a else msg)

        warning = error = info

    monkeypatch.setattr(ev, "logger", _Rec())
    ev._evaluate_all([prediction(pred_id="pred_held", evaluation_hold=HOLD)], TODAY)
    assert any("pred_held" in ln and REASON in ln for ln in lines), lines
    assert any(ln.startswith("Evaluation stats:") and ln.endswith("held=1") for ln in lines), lines


def test_a_held_qualitative_row_is_not_retired(tbl):
    q = {"type": "qualitative"}
    held = prediction(pred_id="pred_q_held", created_date=days_before(90), evaluation=q, evaluation_hold=HOLD)
    free = prediction(pred_id="pred_q_free", created_date=days_before(90), evaluation=q)
    assert ev._retire_ungradeable([held, free], TODAY) == 1
    assert {u["Key"]["sk"] for u in tbl.updates} == {"PREDICTION#pred_q_free"}


def test_a_malformed_hold_fails_closed():
    assert evaluation_hold.is_held({"evaluation_hold": "yes"})
    assert not evaluation_hold.is_held({"evaluation_hold": {}})
    assert not evaluation_hold.is_held({})


# ── the one first-grade write ─────────────────────────────────────────────────────────────


class _RecTable:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.calls = []

    def get_item(self, Key=None, **_):
        self.calls.append(("get_item", Key))
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, **kw):
        self.calls.append(("put_item", kw))
        return {}

    def update_item(self, **kw):
        self.calls.append(("update_item", kw))
        return {}

    def writes(self):
        return [c for c in self.calls if c[0] != "get_item"]


_EVAL = {"status": "confirmed", "evaluated_date": TODAY, "quality_flags": []}


def test_write_first_grade_refuses_a_held_row():
    t = _RecTable()
    row = {"pk": "COACH#labs_coach", "sk": "PREDICTION#p", "status": "pending", "evaluation_hold": HOLD}
    with pytest.raises(evaluation_hold.HeldGradeError):
        grade_corrections.write_first_grade(t, row, _EVAL, outcome_notes="{}", evaluator_version="1.1")
    assert t.calls == []


def test_write_first_grade_is_conditional_on_no_hold():
    """A hold set between the grader's read and its write still wins at DynamoDB."""
    t = _RecTable()
    grade_corrections.write_first_grade(
        t, {"pk": "COACH#labs_coach", "sk": "PREDICTION#p", "status": "pending"}, _EVAL, outcome_notes="{}", evaluator_version="1.1"
    )
    op, kw = t.calls[0]
    assert op == "update_item"
    assert kw["ConditionExpression"] == "attribute_not_exists(evaluation_hold) AND #status = :prior"
    # A row with no stored status still carries the hold condition.
    t2 = _RecTable()
    grade_corrections.write_first_grade(t2, {"pk": "COACH#x", "sk": "PREDICTION#q"}, _EVAL, outcome_notes="{}", evaluator_version="1.1")
    assert t2.calls[0][1]["ConditionExpression"] == "attribute_not_exists(evaluation_hold)"


# ── scripts/evaluation_hold.py ────────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 3, 18, 30, 0, tzinfo=timezone.utc)
AT = "2026-11-03T18:30:00Z"
PK, PID = "COACH#labs_coach", "pred_20261005_recovery_climb_from_september_10_trough"
SK = f"PREDICTION#{PID}"
ENTRY = {"coach_pk": PK, "prediction_id": PID, "reason": REASON, "issue": "#5607"}


def _pending():
    return {"pk": PK, "sk": SK, "status": "pending", "prediction_id": PID}


def test_the_dry_run_writes_nothing():
    t = _RecTable({(PK, SK): _pending()})
    out = io.StringIO()
    counts = hold_script.run("set", [ENTRY], t, apply=False, now=NOW, out=out)
    assert t.writes() == []
    assert [c[0] for c in t.calls] == ["get_item"]
    assert counts == {"written": 0, "skipped": 0, "refused": 0, "failed": 0}
    text = out.getvalue()
    assert "DRY RUN" in text and "put_item:" in text and "update_item:" in text


def test_apply_set_writes_the_audit_row_first_then_one_exact_conditional_update():
    t = _RecTable({(PK, SK): _pending()})
    counts = hold_script.run("set", [ENTRY], t, apply=True, now=NOW, out=io.StringIO())
    assert counts["written"] == 1
    (op1, put), (op2, upd) = t.writes()
    assert (op1, op2) == ("put_item", "update_item"), "audit first, so a failure between leaves a visible audit row"
    audit = put["Item"]
    assert (audit["pk"], audit["sk"]) == (PK, f"EVALHOLD#{PID}#{AT}")
    assert (audit["action"], audit["actor"], audit["prior_status"], audit["reason"]) == ("set", "owner", "pending", REASON)
    hold = {"reason": REASON, "set_at": AT, "set_by": "owner", "ruling_ref": "#5607", "issue": "#5607"}
    assert audit["hold"] == hold
    assert upd == {
        "Key": {"pk": PK, "sk": SK},
        "UpdateExpression": "SET evaluation_hold = :h",
        "ConditionExpression": "attribute_exists(sk) AND #s IN (:pending, :confirming) AND attribute_not_exists(evaluation_hold)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":h": hold, ":pending": "pending", ":confirming": "confirming"},
    }
    assert not any(f in upd["UpdateExpression"] for f in ("outcome", "status", "notes"))


def test_apply_release_removes_only_the_hold_and_stashes_it_in_the_audit_row():
    t = _RecTable({(PK, SK): {**_pending(), "evaluation_hold": HOLD}})
    hold_script.run("release", [{**ENTRY, "reason": "ruled on"}], t, apply=True, now=NOW, out=io.StringIO())
    (op1, put), (op2, upd) = t.writes()
    assert (op1, op2) == ("put_item", "update_item")
    assert (put["Item"]["action"], put["Item"]["released_hold"], put["Item"]["reason"]) == ("release", HOLD, "ruled on")
    assert upd == {
        "Key": {"pk": PK, "sk": SK},
        "UpdateExpression": "REMOVE evaluation_hold",
        "ConditionExpression": "attribute_exists(evaluation_hold)",
    }


@pytest.mark.parametrize(
    "action,row,verdict",
    [
        ("set", None, "no such"),
        ("set", {"status": "observation"}, "not pending/confirming"),  # reclassified: the set no-ops
        ("set", {"status": "pending", "evaluation_hold": HOLD}, "already held"),
        ("release", {"status": "pending"}, "not held"),
    ],
)
def test_a_row_not_in_a_holdable_state_is_skipped_with_no_write(action, row, verdict):
    t = _RecTable({(PK, SK): {"pk": PK, "sk": SK, **row}} if row else {})
    out = io.StringIO()
    counts = hold_script.run(action, [ENTRY], t, apply=True, now=NOW, out=out)
    assert t.writes() == [] and counts["skipped"] == 1
    assert verdict in out.getvalue()


def test_a_condition_refusal_is_counted_not_fatal():
    class _Refusing(_RecTable):
        def update_item(self, **kw):
            super().update_item(**kw)
            err = RuntimeError("cond")
            err.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise err

    t = _Refusing({(PK, SK): _pending()})
    counts = hold_script.run("set", [ENTRY], t, apply=True, now=NOW, out=io.StringIO())
    assert counts == {"written": 0, "skipped": 0, "refused": 1, "failed": 0}


def test_the_manifest_loads_and_a_missing_reason_is_refused(tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"holds": [{"coach_pk": PK, "prediction_id": PID, "reason": REASON}]}))
    args = hold_script.argparse.Namespace(manifest=str(m), coach_pk=None, prediction_id=None, reason="", issue=None)
    assert hold_script.load_entries(args)[0]["reason"] == REASON
    m.write_text(json.dumps([{"coach_pk": PK, "prediction_id": PID}]))
    with pytest.raises(SystemExit):
        hold_script.load_entries(args)


# ── /api/ledger_export ────────────────────────────────────────────────────────────────────


def test_ledger_export_flags_a_held_item_and_keeps_it_pending():
    from web import site_api_ledger_export as lx

    assert "evaluation_hold" in lx.PROJECTION
    base = {
        "pk": PK,
        "sk": SK,
        "prediction_id": PID,
        "coach_id": "labs_coach",
        "status": "pending",
        "created_date": "2026-10-05",
        "claim_natural": "Recovery climbs from the September 10 trough.",
        "evaluation": {"type": "directional", "metric": "recovery_score", "condition": "up"},
    }
    held = lx.export_item("labs", {**base, "evaluation_hold": HOLD})
    assert (held["status"], held["grading_held"], held["grading_held_reason"]) == ("pending", True, REASON)
    free = lx.export_item("labs", base)
    assert "grading_held" not in free and "grading_held_reason" not in free

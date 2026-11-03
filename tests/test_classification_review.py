"""tests/test_classification_review.py — a settled verdict disputed pending classification (owner rulings 2026-11-03).

"Glucose 09-15: ... add it to classification review immediately ... Preserve the existing verdict in the audit history,
but flag it as disputed pending classification. Do not silently re-grade it." and "Keep the original verdict preserved
but explicitly disputed and excluded from any claim that its outcome has been reliably verified, pending
classification."

Pinned here, offline:

  * GRADE WRITERS (the #5613 settled-grade guard, extended): ``write_first_grade``, ``revert_correction`` and every
    non-ruling ``apply_correction`` refuse a row under review, write NOTHING, and carry the absence condition; an
    owner ruling (``basis="ruling"``) is allowed and resolves the review (CLASSREVIEW# audit first, the entry names
    the review, the flag is REMOVEd); ``deploy/regrade_predictions.py`` and ``deploy/revert_regrade.py`` never select it
    — each with its negative control (the same row without the flag IS refused-free / selected).
  * THE SCRIPT: dry run writes nothing; ``--apply`` writes the audit (with the verdict as it stands) then one
    conditional update touching only ``classification_review``; an open call is refused; re-runs are idempotent.
  * COUNTING: out of ``decided_rows`` / ``record_from_rows`` / calibration pairs / ``/api/predictions`` buckets /
    ``record_bodies`` / the grading report, disclosed as ``under_review``; releasing the flag restores the count.
  * SERVING: ``/api/ledger_export`` keeps the stored status and adds the flag + public reason (the default when the
    words are held); the snapshot contract requires the flag and its reason together.
"""

from __future__ import annotations

import copy
import datetime as _dt
import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.join(_REPO, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coach import classification_review, coach_record, grade_corrections, latest_checked  # noqa: E402
from experiment import calibration_core  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


script = _load("classification_review_script", "scripts/classification_review.py")

GENESIS = "2026-09-06"
NOW = datetime(2026, 11, 3, 20, 0, 0, tzinfo=timezone.utc)
AT = "2026-11-03T20:00:00Z"
PK, PID = "COACH#glucose_coach", "pred_20260915_nocturnal_glucose_dips_will_trigger_cort"
SK = f"PREDICTION#{PID}"
REASON = (
    "Disputed under the owner's 2026-11-03 ruling: graded on recovery score, a proxy the call's frozen criteria did not "
    "establish for nocturnal glucose or cortisol; under classification review, verdict preserved."
)
REVIEW = {"reason": REASON, "set_at": AT, "set_by": "owner", "ruling_ref": "owner ruling 2026-11-03", "verdict": "refuted"}
NOTES = json.dumps({"reason": "[window] predicted up, metric flat", "algo_version": "1.1"})


def _row(**over) -> dict:
    """A settled, refuted directional call graded on recovery_score across the HR-regime marker (the 09-15 shape)."""
    row = {
        "pk": PK,
        "sk": SK,
        "prediction_id": PID,
        "coach_id": "glucose_coach",
        "status": "refuted",
        "outcome": "refuted",
        "outcome_date": "2026-11-03",
        "outcome_notes": NOTES,
        "evaluator_version": "1.1",
        "quality_flags": [],
        "created_date": "2026-09-15",
        "phase": "experiment",
        "confidence": 0.5,
        "claim_natural": "Nocturnal glucose dips will fragment slow-wave sleep.",
        "subdomain": "recovery",
        "gradeable_by": "deterministic",
        "evaluation": {"metric": "recovery_score", "type": "directional", "condition": "up", "evaluation_window_days": 49},
    }
    row.update(over)
    return row


def _reviewed(**over) -> dict:
    return _row(classification_review=dict(REVIEW), **over)


class _Rec:
    """Records every write; ``get_item`` serves the seeded rows."""

    def __init__(self, rows=None):
        self.calls: list = []
        self.rows = {(r["pk"], r["sk"]): r for r in rows or []}

    def put_item(self, **kw):
        self.calls.append(("put_item", kw))

    def update_item(self, **kw):
        self.calls.append(("update_item", kw))

    def get_item(self, Key):
        r = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(r)} if r else {}


_EVAL = {"status": "confirmed", "evaluated_date": "2026-11-03", "quality_flags": []}
_CORRECTED = {"status": "inconclusive", "outcome_date": "2026-11-03", "outcome_notes": "{}"}


# ── the module ──────────────────────────────────────────────────────────────────────────────


def test_the_flag_reads_fail_closed_and_the_calibration_attr_is_the_same_name():
    assert classification_review.is_under_review({"classification_review": "yes"})  # malformed → still under review
    assert not classification_review.is_under_review({"classification_review": {}})
    assert classification_review.review_reason({"classification_review": {}}) == classification_review.DEFAULT_READER_REASON
    assert calibration_core.CLASSIFICATION_REVIEW_ATTR == classification_review.ATTR
    assert coach_record._PROJECTION_NAMES["#cr"] == classification_review.ATTR


# ── grade writers ───────────────────────────────────────────────────────────────────────────


def test_the_scheduled_grader_refuses_a_reviewed_row_and_writes_nothing():
    t = _Rec()
    # A reviewed row is settled, so the #5613 refusal fires first; strip that to prove the review refusal stands alone.
    row = _reviewed(status="pending")
    with pytest.raises(classification_review.ClassificationReviewError):
        grade_corrections.write_first_grade(t, row, _EVAL, outcome_notes="{}", evaluator_version="1.1")
    assert t.calls == []
    # Negative control: the same row without the flag is written, conditional on the flag's absence.
    grade_corrections.write_first_grade(t, _row(status="pending"), _EVAL, outcome_notes="{}", evaluator_version="1.1")
    assert "attribute_not_exists(classification_review)" in t.calls[0][1]["ConditionExpression"]


@pytest.mark.parametrize("basis", [grade_corrections.REGRADE, grade_corrections.RESTATE, grade_corrections.FIRST_GRADE])
def test_every_automated_correction_basis_is_refused_on_a_reviewed_row(basis):
    t = _Rec()
    corrected = {**_CORRECTED, "status": "refuted"} if basis == grade_corrections.RESTATE else _CORRECTED
    with pytest.raises(classification_review.ClassificationReviewError):
        grade_corrections.apply_correction(t, _reviewed(), corrected, reason="re-run", evaluator_version="1.2", now=NOW, basis=basis)
    assert t.calls == [], "no ledger row, no update: the disputed verdict is not touched"


def test_an_unreviewed_correction_is_conditional_on_no_review_being_set_since_the_read():
    t = _Rec()
    grade_corrections.apply_correction(t, _row(), _CORRECTED, reason="re-run", evaluator_version="1.2", now=NOW)
    (op1, _), (op2, kw) = t.calls
    assert (op1, op2) == ("put_item", "update_item")
    assert kw["ConditionExpression"].endswith("AND attribute_not_exists(classification_review)")
    assert "REMOVE" not in kw["UpdateExpression"]
    # update_grade=False carries the same condition (it had none before)
    t2 = _Rec()
    grade_corrections.apply_correction(t2, _row(), _CORRECTED, reason="x", evaluator_version="1.2", now=NOW, update_grade=False)
    assert t2.calls[1][1]["ConditionExpression"] == "attribute_not_exists(classification_review)"


def test_an_owner_ruling_resolves_the_review_on_the_record():
    t = _Rec()
    e = grade_corrections.apply_correction(
        t,
        _reviewed(),
        _CORRECTED,
        reason="owner ruling: not gradeable on a proxy",
        evaluator_version="1.1",
        now=NOW,
        basis=grade_corrections.RULING,
        ruled_by="owner",
    )
    ops = [(op, kw.get("Item", {}).get("sk") or kw.get("Key", {}).get("sk")) for op, kw in t.calls]
    assert ops == [("put_item", f"CLASSREVIEW#{PID}#{AT}"), ("put_item", f"CORRECTION#{PID}#{AT}"), ("update_item", SK)]
    audit = t.calls[0][1]["Item"]
    assert audit["action"] == "resolved" and audit["resolved_review"] == REVIEW
    assert audit["prior_status"] == "refuted" and audit["ruled_status"] == "inconclusive"
    assert e["resolves_classification_review"] == REVIEW
    upd = t.calls[2][1]
    assert upd["UpdateExpression"].endswith(" REMOVE classification_review")
    assert "classification_review" not in upd["ConditionExpression"]
    # the original grade is still snapshotted — the verdict is preserved in the audit history
    assert upd["ExpressionAttributeValues"][":orig"]["status"] == "refuted"


def test_a_ruling_that_keeps_the_verdict_also_resolves_it():
    t = _Rec()
    e = grade_corrections.apply_correction(
        t,
        _reviewed(),
        {**_CORRECTED, "status": "refuted"},
        reason="verdict stands",
        evaluator_version="1.1",
        now=NOW,
        basis=grade_corrections.RULING,
        ruled_by="owner",
    )
    assert e["verdict_changed"] is False and "REMOVE classification_review" in t.calls[-1][1]["UpdateExpression"]


def test_a_revert_refuses_a_reviewed_row():
    og = {"status": "confirmed", "outcome_notes": "{}", "snapshot_at": "2026-11-01T00:00:00Z"}
    t = _Rec()
    with pytest.raises(classification_review.ClassificationReviewError):
        grade_corrections.revert_correction(t, _reviewed(original_grade=og, corrections=[{"reason": "#5533"}]), reason="r", now=NOW)
    assert t.calls == []
    grade_corrections.revert_correction(t, _row(original_grade=og, corrections=[{"reason": "#5533"}]), reason="r", now=NOW)
    assert t.calls[-1][1]["ConditionExpression"] == "#status = :prior AND attribute_not_exists(classification_review)"


def test_the_regrade_run_never_selects_a_reviewed_row():
    rp = _load("regrade_predictions_cr", "deploy/regrade_predictions.py")
    kw = {"today": "2026-11-03", "zero_days": set(), "retired_ids": (), "evaluator_version": "1.1"}
    assert rp.HR in rp.reasons_for(_row(), **kw), "negative control: the 09-15 shape IS an HR-regime selection"
    assert rp.reasons_for(_reviewed(), **kw) == []


def test_the_revert_run_never_selects_a_reviewed_row():
    rv = _load("revert_regrade_cr", "deploy/revert_regrade.py")
    corrected = {
        "original_grade": {"status": "confirmed", "snapshot_at": "2026-11-01T00:00:00Z"},
        "corrections": [{"evaluator_version": rv.EVALUATOR_VERSION, "reason": f"{rv.ISSUE} hr"}],
    }
    assert len(rv.select({PK: [_row(**corrected)]})) == 1, "negative control"
    assert rv.select({PK: [_reviewed(**corrected)]}) == []


def test_the_latest_checked_line_skips_a_disputed_verdict():
    class _Q:
        def __init__(self):
            self.kw = None

        def query(self, **kw):
            self.kw = kw
            return {"Items": []}

    q = _Q()
    latest_checked._query_rows(q, "glucose_coach")
    assert "attribute_not_exists(classification_review)" in q.kw["FilterExpression"]


# ── the script ──────────────────────────────────────────────────────────────────────────────


def _entry(**over):
    return {"coach_pk": PK, "prediction_id": PID, "reason": REASON, "ruling_ref": "owner ruling 2026-11-03", "issue": None, **over}


def test_the_dry_run_writes_nothing():
    t = _Rec([_row()])
    out = io.StringIO()
    counts = script.run("set", [_entry()], t, apply=False, now=NOW, out=out)
    assert t.calls == [] and counts == {"written": 0, "skipped": 0, "refused": 0, "failed": 0}
    assert "DRY RUN" in out.getvalue() and "-> write" in out.getvalue()


def test_apply_writes_the_audit_with_the_preserved_verdict_then_only_the_flag():
    t = _Rec([_row()])
    counts = script.run("set", [_entry()], t, apply=True, now=NOW, out=io.StringIO())
    assert counts["written"] == 1
    (op1, put), (op2, upd) = t.calls
    assert (op1, op2) == ("put_item", "update_item")
    audit = put["Item"]
    assert audit["sk"] == f"CLASSREVIEW#{PID}#{AT}" and audit["action"] == "set" and audit["actor"] == "owner"
    assert audit["verdict"] == {
        "status": "refuted",
        "outcome": "refuted",
        "outcome_date": "2026-11-03",
        "outcome_notes": NOTES,
        "evaluator_version": "1.1",
        "quality_flags": [],
    }
    assert upd == {
        "Key": {"pk": PK, "sk": SK},
        "UpdateExpression": "SET classification_review = :r",
        "ConditionExpression": "attribute_exists(sk) AND #s IN (:status) AND attribute_not_exists(classification_review)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":r": {**REVIEW}, ":status": "refuted"},
    }


def test_an_open_call_is_refused_and_a_second_run_is_idempotent():
    t = _Rec([_row(status="pending", outcome=None)])
    assert script.run("set", [_entry()], t, apply=True, now=NOW, out=io.StringIO())["skipped"] == 1 and t.calls == []
    t2 = _Rec([_reviewed()])
    assert script.run("set", [_entry()], t2, apply=True, now=NOW, out=io.StringIO())["skipped"] == 1 and t2.calls == []


def test_release_removes_only_the_flag_and_keeps_what_it_released():
    t = _Rec([_reviewed()])
    script.run("release", [_entry(reason="withdrawn")], t, apply=True, now=NOW, out=io.StringIO())
    (_, put), (_, upd) = t.calls
    assert put["Item"]["released_review"] == REVIEW
    assert upd["UpdateExpression"] == "REMOVE classification_review"
    assert upd["ConditionExpression"] == "attribute_exists(classification_review)"


def test_the_script_writes_no_grade_field():
    _, writes = script.plan_writes("set", _entry(), _row(), AT)
    expr = writes[1]["kwargs"]["UpdateExpression"]
    for f in ("status", "outcome", "outcome_notes", "evaluation", "claim_natural"):
        assert f not in expr


# ── counting ────────────────────────────────────────────────────────────────────────────────


def _partition(reviewed: bool):
    right = _row(sk="PREDICTION#a", prediction_id="a", status="confirmed", outcome="confirmed", confidence=0.7)
    wrong = _reviewed() if reviewed else _row()
    return [right, wrong]


def test_a_disputed_verdict_is_out_of_the_record_and_disclosed_beside_it():
    rows = _partition(reviewed=True)
    assert coach_record.record_from_rows(rows, genesis=GENESIS, as_of="2026-11-03")["n"] == 1
    assert [r["prediction_id"] for r in coach_record.decided_rows(rows, genesis=GENESIS)] == ["a"]
    assert [r["prediction_id"] for r in coach_record.under_review_rows(rows, genesis=GENESIS)] == [PID]
    assert len(calibration_core.pairs_from_prediction_records(rows)) == 1
    assert rows[1]["status"] == "refuted", "the stored verdict is untouched"


def test_releasing_the_review_restores_normal_counting():
    rows = _partition(reviewed=False)
    rec = coach_record.record_from_rows(rows, genesis=GENESIS, as_of="2026-11-03")
    assert (rec["confirmed"], rec["refuted"], rec["n"]) == (1, 1, 2)
    assert coach_record.under_review_rows(rows, genesis=GENESIS) == []
    assert len(calibration_core.pairs_from_prediction_records(rows)) == 2


def _g(rows_by_short):
    from web import site_api_coach_ledger as cl

    class _NoTable:
        def get_item(self, **_k):
            raise RuntimeError("no table")

        def query(self, **_k):
            raise RuntimeError("no table")

    return cl, {
        "table": _NoTable(),
        "EXPERIMENT_START": GENESIS,
        "_current_cycle": lambda: None,
        "_fetch_prediction_partition": lambda pk: rows_by_short.get(pk.split("#")[1].replace("_coach", ""), []),
        "_parallel_fetch": cl._parallel_fetch,
        "datetime": _dt.datetime,
    }


@pytest.mark.parametrize("reviewed", [True, False])
def test_api_predictions_buckets_a_disputed_verdict_apart_and_keeps_its_status(reviewed):
    cl, g = _g({"glucose": _partition(reviewed)})
    body = json.loads(cl.handle_predictions({"queryStringParameters": {"limit": "200"}}, _g=g)["body"])
    o, bc = body["overall"], body["by_coach"]["glucose"]
    if reviewed:
        assert (o["confirmed"], o["refuted"], o["decided"], o["under_review"], o["total"]) == (1, 0, 1, 1, 2)
        assert (bc["refuted"], bc["under_review"], bc["decided"]) == (0, 1, 1)
        assert bc["record"]["n"] == 1 and o["lifetime"]["under_review"] == 1
        (item,) = [p for p in body["predictions"] if p["status"] == "refuted"]
        assert item["classification_review"] is True and item["classification_review_reason"] == REASON
    else:  # release restores normal counting
        assert (o["confirmed"], o["refuted"], o["decided"], o["under_review"]) == (1, 1, 2, 0)
        assert all("classification_review" not in p for p in body["predictions"])


def test_record_bodies_discloses_and_excludes():
    cl, _ = _g({})
    out = cl.record_bodies({"glucose": _partition(True)}, "2026-11-03", GENESIS)["predictions"]["overall"]
    assert (out["confirmed"], out["refuted"], out["decided"], out["under_review"]) == (1, 0, 1, 1)
    out = cl.record_bodies({"glucose": _partition(False)}, "2026-11-03", GENESIS)["predictions"]["overall"]
    assert (out["refuted"], out["under_review"]) == (1, 0)


def test_the_projection_reads_the_flag():
    from web import site_api_coach_ledger as cl, site_api_ledger_export as le

    assert "classification_review" in cl._PREDICTION_PROJECTION_FIELDS and "classification_review" in le.PROJECTION


def test_the_grading_report_excludes_and_discloses():
    gr = _load("coach_grading_report_cr", "scripts/coach_grading_report.py")
    blk = gr.record_block([_partition(True)], genesis=GENESIS, as_of="2026-11-03", career=False)
    assert (blk["n"], blk["under_review"], blk["brier_pairs_n"]) == (1, 1, 1)
    assert blk["calls"]["under_review"] == 1 and blk["calls"]["refuted"] == 0 and blk["calls"]["decided"] == 1
    blk = gr.record_block([_partition(False)], genesis=GENESIS, as_of="2026-11-03", career=False)
    assert (blk["n"], blk["under_review"]) == (2, 0)


# ── serving ─────────────────────────────────────────────────────────────────────────────────


def test_the_ledger_item_keeps_the_stored_status_and_says_it_is_disputed(monkeypatch):
    from web import site_api_ledger_export as le

    monkeypatch.setattr(le, "_dossier_safe", lambda _t: True)
    item = le.export_item("glucose", _reviewed())
    assert item["status"] == "refuted"
    assert item["classification_review"] is True and item["classification_review_reason"] == REASON
    plain = le.export_item("glucose", _row())
    assert "classification_review" not in plain and plain["status"] == "refuted"
    monkeypatch.setattr(le, "_dossier_safe", lambda _t: False)  # words withheld → the stored reason does not travel
    assert le.export_item("glucose", _reviewed())["classification_review_reason"] == classification_review.DEFAULT_READER_REASON


def test_the_snapshot_contract_requires_the_flag_and_its_reason_together():
    import publish_snapshot_contract as c

    fixtures = json.load(open(os.path.join(_REPO, "www", "content", "fixtures", "predictions.json"), encoding="utf-8"))
    disputed = next(p for p in fixtures if p["classification_review"])
    c.validate(disputed, "prediction")
    with pytest.raises(c.SchemaError):
        c.validate({**disputed, "classification_review_reason": None}, "prediction")
    with pytest.raises(c.SchemaError):
        c.validate({k: v for k, v in disputed.items() if k != "classification_review"}, "prediction")

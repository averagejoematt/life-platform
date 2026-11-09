"""tests/test_verification_record.py — the append-only verification record (owner 2026-11-09, coach/verification_record.py).

The owner's spec: an auditable record per call — id, wording/criteria version, original and current verdict, the
ruleset version, the evidence and whether it was available, the instant, and whether the verdict was REPRODUCED,
CORRECTED or COULD NOT BE VERIFIED; "the stamp must distinguish an unchanged verdict from a genuinely validated
classification"; "do not rewrite historical timestamps or imply the calls were verified when originally graded".

Each property is asserted on the real module over a fake table that honours the two conditions the writer sends, and
each has a MUTATION CONTROL: the same check run against a deliberately broken variant must fail, so no test here can
pass vacuously. ``scripts/record_verification.py`` is driven over the same fake table with a fake evaluator: a dry run
writes nothing, ``--apply``'s path writes through the one writer. Every id here is synthetic.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import pytest  # noqa: E402
import record_verification as rv  # noqa: E402
from coach import verification_record as vr  # noqa: E402

PK = "COACH#sleep_coach"
PID = "pred_20260907_synthetic_recovery_call"
SK = f"PREDICTION#{PID}"
T1 = "2026-11-09T18:00:00Z"
T2 = "2026-11-10T18:00:00Z"
SPEC = {
    "type": "point",
    "condition": "within",
    "metric": "recovery_score",
    "evaluation_window_days": 1,
    "target_date": "2026-09-08",
    "threshold": 61.0,
    "tolerance": 17.9,
}


def _row(status="confirmed", **extra):
    row = {
        "pk": PK,
        "sk": SK,
        "prediction_id": PID,
        "coach_id": "sleep_coach",
        "claim_natural": "Synthetic: recovery climbs back to about 61 tomorrow.",
        "created_date": "2026-09-07",
        "created_at": "2026-09-07T17:01:20+00:00",
        "status": status,
        "outcome": status,
        "outcome_date": "2026-09-21",
        "outcome_notes": json.dumps({"reason": "synthetic", "algo_version": "1.0"}),
        "evaluator_version": "1.0",
        "evaluation": dict(SPEC),
    }
    row.update(extra)
    return row


class ConditionFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Applies the writer's two writes and honours their conditions; records every write."""

    def __init__(self, *rows):
        self.items = {(r["pk"], r["sk"]): copy.deepcopy(r) for r in rows}
        self.writes: list = []

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, **_kw):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise ConditionFailed(key)
        self.writes.append(("put", key))
        self.items[key] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ConditionExpression="", ExpressionAttributeValues=None, **_kw):
        key = (Key["pk"], Key["sk"])
        row = self.items.get(key)
        values = ExpressionAttributeValues or {}
        if "attribute_exists(sk)" in ConditionExpression and row is None:
            raise ConditionFailed(key)
        if "#s IN (:status)" in ConditionExpression and row.get("status") != values[":status"]:
            raise ConditionFailed(key)
        prior = (row or {}).get(vr.POINTER_ATTR)
        if f"{vr.POINTER_ATTR}.sk < :sk" in ConditionExpression and isinstance(prior, dict) and not prior["sk"] < values[":sk"]:
            raise ConditionFailed(key)
        assert UpdateExpression.startswith("SET "), UpdateExpression
        self.writes.append(("update", key))
        for clause in UpdateExpression[4:].split(","):
            attr, val = (s.strip() for s in clause.split("="))
            row[attr] = copy.deepcopy(values[val])


def _record(row, rerun, *, at=T1, classification=None, ruleset="1.1"):
    return vr.build_record(
        row,
        rerun,
        evidence_entries=[
            {"source": "whoop", "metric": "recovery_score", "dates": {"from": "2026-09-08", "to": "2026-09-08"}, "available": True}
        ],
        classification=classification if classification is not None else vr.classification_of({"proposed_classification": "keep"}),
        ruleset_version=ruleset,
        verified_at=at,
    )


def _verify(table, rerun_status="confirmed", *, at=T1, classification=None):
    row = table.get_item(Key={"pk": PK, "sk": SK})["Item"]
    rec = _record(row, {"status": rerun_status, "reason": "synthetic re-run"}, at=at, classification=classification)
    vr.write_verification(table, row, rec)
    return rec


def _verify_rows(table):
    return sorted(k[1] for k in table.items if k[1].startswith(vr.VERIFY_PREFIX))


# ── append-only ────────────────────────────────────────────────────────────────────────────────


def _appends(table) -> bool:
    _verify(table, at=T1)
    _verify(table, at=T2)
    rows = _verify_rows(table)
    pointer = table.items[(PK, SK)][vr.POINTER_ATTR]
    return rows == [f"VERIFY#{PID}#{T1}", f"VERIFY#{PID}#{T2}"] and pointer["sk"] == f"VERIFY#{PID}#{T2}"


def test_a_second_verification_appends_and_moves_the_pointer():
    table = FakeTable(_row())
    assert _appends(table)
    first = table.items[(PK, f"VERIFY#{PID}#{T1}")]
    assert first["verified_at"] == T1 and first["outcome"] == vr.REPRODUCED, "the first record is kept as written"
    assert [w[0] for w in table.writes] == ["put", "update", "put", "update"], "audit row first, then the pointer"


def test_an_existing_verification_row_is_never_overwritten_and_an_older_one_never_takes_the_pointer():
    table = FakeTable(_row())
    _verify(table, at=T2)
    with pytest.raises(ConditionFailed):
        _verify(table, at=T2)  # the same instant: the put is refused, nothing overwritten
    with pytest.raises(ConditionFailed):
        _verify(table, at=T1)  # an OLDER record lands as audit, but never displaces the newer pointer
    assert table.items[(PK, SK)][vr.POINTER_ATTR]["sk"] == f"VERIFY#{PID}#{T2}"


def test_mutation_control_an_upserting_writer_fails_the_append_check(monkeypatch):
    real = vr.build_record

    def upsert(*a, **k):  # the mutant keys the record on the call alone: every verification overwrites the last
        rec = real(*a, **k)
        rec["sk"] = f"{vr.VERIFY_PREFIX}{PID}"
        return rec

    monkeypatch.setattr(vr, "build_record", upsert)
    monkeypatch.setattr(
        vr, "plan_writes", lambda row, rec: [{"op": "put_item", "kwargs": {"Item": rec}}, {"op": "update_item", "kwargs": _ptr(row, rec)}]
    )
    assert not _appends(FakeTable(_row()))


def _ptr(row, rec):
    return {
        "Key": {"pk": row["pk"], "sk": row["sk"]},
        "UpdateExpression": f"SET {vr.POINTER_ATTR} = :lv",
        "ConditionExpression": "",
        "ExpressionAttributeValues": {":lv": vr.pointer_of(rec)},
    }


# ── reproduced ≠ validated ─────────────────────────────────────────────────────────────────────


def _reproduced_is_not_validated(build) -> bool:
    row = _row()
    rec = build(row, {"status": "confirmed"})
    return rec["outcome"] == vr.REPRODUCED and rec["verdict_unchanged"] is True and rec["classification_validated"] is False


def test_a_reproduced_call_is_reproduced_and_not_validated_without_a_classification_ruling():
    assert _reproduced_is_not_validated(_record)
    rec = _record(_row(), {"status": "confirmed"})
    assert rec["classification"] == {"value": "keep", "approved": False, "ruling_ref": None}, "a proposal is recorded as one"


def test_a_classification_ruling_validates_a_reproduced_call_and_nothing_else_does():
    ruling = vr.classification_of({"approved_classification": "keep", "classification_ruling_ref": "owner ruling 2026-11-09 (synthetic)"})
    assert _record(_row(), {"status": "confirmed"}, classification=ruling)["classification_validated"] is True
    # an approval with no ruling reference is not a ruling
    assert vr.classification_of({"approved_classification": "keep"})["approved"] is False
    # a ruling validates nothing the re-run could not reproduce
    assert _record(_row(), {"status": "refuted"}, classification=ruling)["classification_validated"] is False
    # nor a call whose verdict is under classification review
    disputed = _row(classification_review={"reason": "synthetic dispute"})
    assert _record(disputed, {"status": "confirmed"}, classification=ruling)["classification_validated"] is False


def test_mutation_control_validated_derived_from_an_unchanged_verdict_is_caught():
    def mutant(row, rerun, **k):
        rec = _record(row, rerun, **k)
        rec["classification_validated"] = rec["verdict_unchanged"]  # the conflation the owner ruled out
        return rec

    assert not _reproduced_is_not_validated(mutant)


def test_a_corrected_call_reproduces_the_correction_and_keeps_the_first_grade_on_record():
    row = _row(
        status="refuted", original_grade={"status": "confirmed", "outcome_date": "2026-09-21", "snapshot_at": "2026-11-01T00:00:00Z"}
    )
    row["corrections"] = [{"original_status": "confirmed", "corrected_status": "refuted"}]
    rec = _record(row, {"status": "refuted"})
    assert rec["outcome"] == vr.CORRECTED and rec["verdict_unchanged"] is False
    assert (rec["original_status"], rec["original_outcome_date"], rec["current_status"]) == ("confirmed", "2026-09-21", "refuted")


# ── could not verify ───────────────────────────────────────────────────────────────────────────


def _could_not_verify(outcome_fn) -> bool:
    return outcome_fn(_row(), None)[0] == vr.COULD_NOT_VERIFY and outcome_fn(_row(), {"status": "expired"})[0] == vr.COULD_NOT_VERIFY


def test_no_rerun_grade_or_a_disagreeing_rerun_could_not_be_verified():
    assert _could_not_verify(vr.outcome_of)
    rec = _record(_row(), {"status": "expired", "reason": "Expired: no reading"})
    assert rec["outcome"] == vr.COULD_NOT_VERIFY and rec["rerun_status"] == "expired" and rec["current_status"] == "confirmed"
    assert rec["classification_validated"] is False


def test_mutation_control_an_outcome_that_trusts_any_rerun_is_caught():
    assert not _could_not_verify(lambda row, rerun: (vr.REPRODUCED, "mutant"))


# ── the original fields are untouched ──────────────────────────────────────────────────────────


def _untouched(table) -> bool:
    before = copy.deepcopy(table.items[(PK, SK)])
    _verify(table, rerun_status="expired")  # a could-not-verify record must not move the grade either
    _verify(table, at=T2)
    after = table.items[(PK, SK)]
    return {k: v for k, v in after.items() if k != vr.POINTER_ATTR} == before and set(after) - set(before) == {vr.POINTER_ATTR}


def test_the_prediction_row_gains_only_the_pointer():
    table = FakeTable(_row())
    assert _untouched(table)
    assert table.items[(PK, SK)][vr.POINTER_ATTR] == {
        "sk": f"VERIFY#{PID}#{T2}",
        "outcome": vr.REPRODUCED,
        "verified_at": T2,
        "ruleset_version": "1.1",
        "classification_validated": False,
    }
    rec = table.items[(PK, f"VERIFY#{PID}#{T1}")]
    assert rec["current_outcome_date"] == "2026-09-21" and rec["verified_at"] == T1, "the grading day is copied, never restamped"


def test_mutation_control_a_writer_that_restamps_the_grade_is_caught(monkeypatch):
    real = vr.plan_writes

    def restamp(row, rec):
        put, upd = real(row, rec)
        upd["kwargs"]["UpdateExpression"] += ", outcome_date = :od"
        upd["kwargs"]["ExpressionAttributeValues"][":od"] = rec["verified_at"][:10]
        return [put, upd]

    monkeypatch.setattr(vr, "plan_writes", restamp)
    assert not _untouched(FakeTable(_row()))


def test_the_record_carries_the_spec_fields_and_hashes_not_words():
    rec = _record(_row(filing={"filing_rules_version": "1"}), {"status": "confirmed", "reason": "r"})
    for field in (
        "prediction_id",
        "claim_hash",
        "criteria_hash",
        "criteria_version",
        "original_status",
        "current_status",
        "ruleset_version",
        "classification",
        "evidence",
        "verified_at",
        "outcome",
        "classification_validated",
    ):
        assert field in rec, field
    assert rec["criteria_version"] == "1" and len(rec["claim_hash"]) == 64 and len(rec["criteria_hash"]) == 64
    assert "Synthetic: recovery" not in json.dumps(rec, default=str), "the words stay on the prediction row"
    assert vr.criteria_hash({"evaluation": {"threshold": 61}}) == vr.criteria_hash({"evaluation": {"threshold": 61.0}})


def test_served_reads_the_pointer_only_and_never_infers_from_versions():
    assert vr.served(_row(evaluator_version="1.1")) is None
    assert vr.served(_row(**{vr.POINTER_ATTR: {"outcome": "bogus"}})) is None
    lv = {"sk": "VERIFY#x#t", "outcome": "reproduced", "verified_at": T1, "ruleset_version": "1.1", "classification_validated": False}
    assert vr.served(_row(**{vr.POINTER_ATTR: lv})) == {k: lv[k] for k in vr.SERVED_FIELDS}


def test_evidence_lists_the_target_window_and_whether_readings_exist():
    row = _row()
    seen = {("whoop", "recovery_score")}

    def series(source, base, lo, hi):
        assert (source, base) in seen
        return [("2026-09-08", 67.0), ("2026-09-20", 50.0)]

    ev = vr.evidence(row, {"status": "confirmed"}, "2026-11-08", series)
    assert ev == [
        {
            "source": "whoop",
            "metric": "recovery_score",
            "dates": {"from": "2026-09-08", "to": "2026-09-08", "with_readings": ["2026-09-08"]},
            "available": True,
        }
    ]
    empty = vr.evidence(row, None, "2026-11-08", lambda *a: [])
    assert empty[0]["available"] is False


# ── scripts/record_verification.py ─────────────────────────────────────────────────────────────


class FakeEvaluator:
    ALGO_VERSION = "1.1"

    def __init__(self, status):
        self.status = status
        self.calls: list = []

    def _evaluate_all(self, rows, today, write=True):
        assert write is False, "the verifier never reaches the evaluator's write path"
        self.calls.append(today)
        return [{"prediction_id": r["prediction_id"], "status": self.status, "reason": "fake re-run"} for r in rows], {}

    def _fetch_range(self, source, lo, hi, include_pilot=False):
        return [{"date": "2026-09-08", "recovery_score": 67.0}]

    def _extract_metric_series(self, records, metric):
        return [(r["date"], r[metric]) for r in records if metric in r]


ENTRY = {"key": f"sleep_coach|{PID}", "prediction_id": PID, "proposed_classification": "keep"}


def test_the_script_is_a_dry_run_by_default_and_prints_the_writes():
    table = FakeTable(_row())
    out = io.StringIO()
    counts = rv.run(rv_entries([ENTRY]), table, ev=FakeEvaluator("confirmed"), today="2026-11-08", apply=False, out=out)
    assert table.writes == [], "a dry run writes nothing"
    assert counts["reproduced"] == 1 and counts["classification_validated"] == 0 and counts["written"] == 0
    text = out.getvalue()
    assert "DRY RUN" in text and "put_item" in text and "update_item" in text and f"VERIFY#{PID}#" in text


def test_the_script_apply_path_writes_through_the_one_writer():
    table = FakeTable(_row())
    counts = rv.run(rv_entries([ENTRY]), table, ev=FakeEvaluator("confirmed"), today="2026-11-08", apply=True, out=io.StringIO())
    assert counts["written"] == 1 and [w[0] for w in table.writes] == ["put", "update"]
    assert len(_verify_rows(table)) == 1 and table.items[(PK, SK)]["status"] == "confirmed"


def test_the_script_skips_an_open_call_and_marks_a_disagreement_could_not_verify():
    table = FakeTable(_row(), _row(status="pending", sk="PREDICTION#pred_open", prediction_id="pred_open"))
    entries = rv_entries([ENTRY, {"coach_pk": PK, "prediction_id": "pred_open"}])
    counts = rv.run(entries, table, ev=FakeEvaluator("refuted"), today="2026-11-08", apply=False, out=io.StringIO())
    assert counts["could_not_verify"] == 1 and counts["skipped"] == 1


def test_the_manifest_v3_shape_loads_and_an_unapproved_classification_validates_nothing(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"rows": [ENTRY, {"coach": "sleep", "prediction_id": "p2"}]}), encoding="utf-8")
    entries = rv.load_entries(str(path))
    assert [(e["coach_pk"], e["prediction_id"]) for e in entries] == [(PK, PID), (PK, "p2")]
    assert vr.classification_of(entries[0])["approved"] is False


def test_the_script_main_refuses_nothing_silently_and_defaults_to_dry_run(monkeypatch, tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps([ENTRY]), encoding="utf-8")
    table = FakeTable(_row())
    monkeypatch.setattr(rv, "_table", lambda: table)
    monkeypatch.setattr(rv, "_evaluator", lambda: FakeEvaluator("confirmed"))
    assert rv.main(["--manifest", str(path), "--today", "2026-11-08"]) == 0
    assert table.writes == []


def rv_entries(raw):
    return [{**r, "coach_pk": r.get("coach_pk") or f"COACH#{r['key'].split('|')[0]}"} for r in raw]

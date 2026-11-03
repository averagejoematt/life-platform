"""#5626 — the coach page's learning trail is read against the ledger's CURRENT verdicts.

The LEARNING# rows are written once, when a call is first graded; a grade correction rewrites the
PREDICTION# row only. ``/api/coach/<id>`` therefore served the first grade (the explorer's
``pred_20261015_if_october_5_6_protein_dropped_below_150`` as "confirmed … 98 → 15 g" after its 1 November
correction to refuted) and a call the ledger withholds by the journal-silence rule (#5131). The fix reads at
request time and NEVER writes a LEARNING# row (owner: a change must not silently rewrite history).
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_coach as api,  # noqa: E402
    trail_corrections,  # noqa: E402
)

PK = "COACH#explorer_coach"
CORRECTED = "pred_20261015_if_october_5_6_protein_dropped_below_150"
RETIRED = "pred_20261015_if_october_5_6_protein_stayed_above_150"
SILENCED = "pred_20261015_protein_recovery_would_lift_the_journali"
UNCHANGED = "pred_20261019_recovery_would_hold_or_climb_if_protein"
NO_ROW = "pred_20261001_a_prediction_with_no_stored_row"

_FIRST = (
    "total_protein_g 98 on 2026-10-15 -> 15 on 2026-10-29 (change -83, band ±46, window 2026-10-15..2026-10-29): trend=down, predicted=down"
)


def _learning(pid, date, status, reason, metric="total_protein_g"):
    return {
        "pk": PK,
        "sk": f"LEARNING#{date}#{pid.replace('_', '-')[:60]}-{status}",
        "date": date,
        "channel": "data",
        "status": status,
        "metric": metric,
        "reason": reason,
        "prediction_id": pid,
        "condition": "down",
    }


LEARNINGS = [
    _learning(
        UNCHANGED,
        "2026-11-02",
        "confirmed",
        "recovery_score 47 on 2026-10-19 -> 77 on 2026-11-02: trend=up, predicted=up",
        "recovery_score",
    ),
    _learning(CORRECTED, "2026-10-29", "confirmed", "[window] " + _FIRST),
    _learning(RETIRED, "2026-10-29", "refuted", "total_protein_g 98 on 2026-10-15 -> 15 on 2026-10-29: trend=down, predicted=up"),
    _learning(SILENCED, "2026-10-29", "refuted", "total_protein_g 98 on 2026-10-15 -> 15 on 2026-10-29: trend=down, predicted=up"),
    _learning(NO_ROW, "2026-10-14", "confirmed", "total_protein_g=155.00 on 2026-10-12 vs predicted 157 ±65.1"),
]


def _notes(reason, actual):
    return json.dumps({"reason": reason, "actual_value": actual})


def _pred(pid, status, claim, notes, metric="total_protein_g", **extra):
    return {
        "pk": PK,
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": "explorer_coach",
        "status": status,
        "created_date": "2026-10-15",
        "outcome_date": "2026-10-29",
        "claim_natural": claim,
        "outcome_notes": notes,
        "evaluation": {"type": "directional", "metric": metric, "condition": "down", "evaluation_window_days": 14},
        **extra,
    }


PREDICTIONS = {
    CORRECTED: _pred(
        CORRECTED,
        "refuted",
        "If October 5-6 protein dropped below 150 g, protein will keep falling.",
        _notes("[window] predicted down, metric flat — total_protein_g 98 on 2026-10-15 -> 111 on 2026-10-27", 0.13),
        corrections=[
            {
                "corrected_at": "2026-11-01T18:11:57Z",
                "original_status": "confirmed",
                "corrected_status": "refuted",
                "original_outcome_date": "2026-10-29",
                "corrected_outcome_date": "2026-11-01",
                "reason": "#5533 (c): a no-food-logged day was read as near-zero intake",
                "evaluator_version": "1.1",
            }
        ],
    ),
    RETIRED: _pred(
        RETIRED,
        "expired",
        "If October 5-6 protein stayed above 150 g, recovery will lift.",
        _notes("retired ungraded", None),
        corrections=[
            {
                "corrected_at": "2026-11-03T02:47:32Z",
                "original_status": "refuted",
                "corrected_status": "expired",
                "reason": "#5533 (c) + owner ruling 2026-11-02: retired ungraded",
                "evaluator_version": "1.1",
            }
        ],
    ),
    SILENCED: _pred(
        SILENCED,
        "refuted",
        "Protein recovery would lift the journaling silence by the weekend.",
        _notes("total_protein_g trend=down, predicted=up", -0.84),
    ),
    UNCHANGED: _pred(
        UNCHANGED,
        "confirmed",
        "Recovery would hold or climb if protein holds.",
        _notes("trend=up, predicted=up", 0.63),
        metric="recovery_score",
    ),
}


def _cond_parts(cond):
    expr = cond.get_expression()
    if expr.get("operator") == "AND":
        a, b = expr["values"]
        return a.get_expression()["values"][1], b.get_expression()["values"][1]
    return expr["values"][1], None


def _table(predictions=None, failing=()):
    preds = PREDICTIONS if predictions is None else predictions
    reads = []

    def _query(table, **kw):
        pk, sk = _cond_parts(kw["KeyConditionExpression"])
        if pk == PK and (sk or "").startswith("LEARNING#"):
            return {"Items": [dict(i) for i in LEARNINGS]}
        return {"Items": []}

    def _get(table, key, **kw):
        reads.append(dict(key))
        sk = str(key.get("sk") or "")
        if sk.startswith("PREDICTION#"):
            pid = sk[len("PREDICTION#") :]
            if pid in failing:
                raise RuntimeError("simulated GetItem failure")
            row = preds.get(pid) if key.get("pk") == PK else None
            return {"Item": dict(row)} if row else {}
        return {}

    t = FakeDdbTable(query_hook=_query, get_item_hook=_get)
    t.prediction_reads = reads
    return t


def _coach(monkeypatch, table):
    monkeypatch.setattr(api, "table", table)
    resp = api.handle_coach({"rawPath": "/api/coach/explorer_coach"})
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def _by_pid(entries):
    return {(e.get("evidence") or {}).get("prediction_id"): e for e in entries}


def test_dossier_learnings_serve_the_current_verdict_with_the_original_and_the_correction_time(monkeypatch):
    t = _table()
    body = _coach(monkeypatch, t)
    learn = _by_pid(body["dossier"]["learnings"])

    e = learn[CORRECTED]
    assert e["status"] == "refuted"  # the ledger's verdict, not the first grade
    gc = e["grade_correction"]
    assert gc["original_status"] == "confirmed"
    assert gc["corrected_status"] == "refuted"
    assert gc["corrected_at"] == "2026-11-01T18:11:57Z"  # the stored instant, verbatim
    assert gc["explanation"] and "no food logged" in gc["explanation"]  # web.correction_rules' words
    assert gc["original_reason"].startswith("total_protein_g 98") and "predicted=down" in gc["original_reason"]
    assert "predicted=down" not in (e["reason"] or "")  # the first grade's text is not served as the reason

    r = learn[RETIRED]
    assert r["status"] == "expired"
    assert r["grade_correction"]["original_status"] == "refuted"
    assert r["grade_correction"]["corrected_at"] == "2026-11-03T02:47:32Z"
    assert "retired ungraded" in r["grade_correction"]["explanation"]

    assert "grade_correction" not in learn[UNCHANGED] and learn[UNCHANGED]["status"] == "confirmed"
    assert learn[NO_ROW]["status"] == "confirmed"  # no stored row: nothing contradicts the trail

    assert body["dossier"]["learning_corrections"] == {"corrected": 2, "withheld": 1, "unverified": 0}


def test_a_journal_silenced_prediction_is_absent_from_both_trails(monkeypatch):
    body = _coach(monkeypatch, _table())
    assert SILENCED not in _by_pid(body["dossier"]["learnings"])
    assert SILENCED not in json.dumps(body)
    recent = body["report_card"]["track_record"]["recent"]
    assert len(recent) == 4  # five graded trail lines, one withheld


def test_report_card_recent_serves_the_corrected_verdict(monkeypatch):
    body = _coach(monkeypatch, _table())
    recent = body["report_card"]["track_record"]["recent"]
    corrected = [r for r in recent if r.get("grade_correction")]
    assert {r["status"] for r in corrected} == {"refuted", "expired"}
    first = next(r for r in corrected if r["status"] == "refuted")
    assert first["grade_correction"] == {
        "original_status": "confirmed",
        "original_reason": first["grade_correction"]["original_reason"],
        "corrected_status": "refuted",
        "corrected_at": "2026-11-01T18:11:57Z",
        "explanation": first["grade_correction"]["explanation"],
    }
    assert all("prediction_id" not in r for r in recent)  # the served shape keeps its keys


def test_the_learning_rows_are_never_written(monkeypatch):
    t = _table()
    _coach(monkeypatch, t)
    assert t.puts == [] and t.updates == [] and t.deletes == []
    src = open(os.path.join(_REPO, "lambdas", "web", "trail_corrections.py")).read()
    assert not re.search(r"\b(put_item|update_item|delete_item|batch_writer|batch_write_item|transact_write)", src)


def test_reads_are_bounded_get_items_of_the_referenced_predictions(monkeypatch):
    t = _table()
    _coach(monkeypatch, t)
    sks = [k["sk"] for k in t.prediction_reads if str(k.get("sk", "")).startswith("PREDICTION#")]
    assert set(sks) == {f"PREDICTION#{p}" for p in (CORRECTED, RETIRED, SILENCED, UNCHANGED, NO_ROW)}
    assert len(sks) <= 2 * len(set(sks))  # one read per prediction per trail (report card + dossier)


def test_a_failed_prediction_read_withholds_its_entry_rather_than_serving_the_first_grade(monkeypatch):
    body = _coach(monkeypatch, _table(failing={CORRECTED}))
    learn = _by_pid(body["dossier"]["learnings"])
    assert CORRECTED not in learn
    assert body["dossier"]["learning_corrections"]["unverified"] == 1


def test_reconcile_entry_is_pure_and_never_mutates_the_trail_entry():
    entry = {"status": "confirmed", "reason": _FIRST, "evidence": {"prediction_id": CORRECTED}}
    before = dict(entry)
    out = trail_corrections.reconcile_entry(entry, PREDICTIONS[CORRECTED], "explorer_coach")
    assert entry == before and out is not entry and out["status"] == "refuted"
    assert trail_corrections.reconcile_entry(entry, None, "explorer_coach") is entry
    assert trail_corrections.reconcile_entry(entry, PREDICTIONS[SILENCED], "explorer_coach") is None


def test_a_status_change_with_no_recorded_correction_invents_no_time():
    row = dict(PREDICTIONS[UNCHANGED], status="refuted")
    out = trail_corrections.reconcile_entry({"status": "confirmed", "reason": "x"}, row, "explorer_coach")
    assert out["grade_correction"]["corrected_at"] is None and out["grade_correction"]["explanation"] is None

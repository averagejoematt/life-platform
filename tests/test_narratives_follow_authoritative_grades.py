"""tests/test_narratives_follow_authoritative_grades.py — owner ruling 2026-11-03: corrected grades flow into coach summaries.

"Corrected authoritative grades must flow into coach-facing summaries and future narratives. A coach must not continue
claiming a prediction was wrong, right or measurable after its authoritative classification has changed. However:
Preserve original historical quotations verbatim. Add dated corrections rather than rewriting what was originally said.
Regenerate derived summaries from current authoritative records. Include provenance and an as-of timestamp. Do not let
generated narratives invent explanations for a correction."

The fixtures are SYNTHETIC (public repo): the shape of the 3 November defect — a stored read calling a call "wrong"
after the call was re-graded refuted → expired by rule #5611:m — with invented words about evening walks.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from coach import (  # noqa: E402
    authoritative_grades as ag,  # noqa: E402
    derived_text_guard,
    verdict_claims,
)

PID = "pred_20261015_protein_recovery_would_lift_the_evening_walks"
CLAIM = "Protein recovery would lift the evening walks"
STORED_READ = (
    "I predicted that restoring his protein intake would restore his evening walks, but protein climbed while the walks "
    "stayed flat — the mechanism was wrong, which means the barrier isn't metabolic."
)
RULE_5611_M = "#5611 (m) + owner ruling 2026-11-03: graded on protein, but the sentence's outcome is not what the stored criteria measured"


def _row(status="expired", corrected=True, created="2026-10-15"):
    row = {
        "pk": "COACH#mind_coach",
        "sk": f"PREDICTION#{PID}",
        "prediction_id": PID,
        "claim_natural": CLAIM,
        "status": status,
        "created_date": created,
        "evaluation": {"type": "directional", "metric": "total_protein_g"},
    }
    if corrected:
        row["corrections"] = [
            {
                "original_status": "refuted",
                "corrected_status": status,
                "corrected_at": "2026-11-03T18:55:07Z",
                "corrected_outcome_date": "2026-11-03",
                "original_outcome_date": "2026-10-29",
                "reason": RULE_5611_M,
                "evaluator_version": "1.1",
                "basis": "ruling",
            }
        ]
        row["original_grade"] = {"status": "refuted"}
    return row


def _correction_row(original="refuted", corrected="expired", at="2026-11-03T18:55:07Z", pid=PID, reason=RULE_5611_M):
    return {
        "sk": f"CORRECTION#{pid}#{at}",
        "prediction_id": pid,
        "original_status": original,
        "corrected_status": corrected,
        "corrected_at": at,
        "reason": reason,
    }


CALLS_NOW = [{"prediction_id": PID, "claim": CLAIM, "status": "expired", "said_on": "2026-10-15"}]
CALLS_ON_MAIN = [{"prediction_id": PID, "claim": CLAIM, "status": "refuted", "said_on": "2026-10-15"}]


# ── the validator ────────────────────────────────────────────────────────────────────────────────────


def test_the_mind_case_a_wrong_verdict_on_a_call_now_could_not_be_checked_is_a_finding():
    hits = verdict_claims.findings(STORED_READ, CALLS_NOW, as_of="2026-11-02")
    assert len(hits) == 1 and hits[0]["prediction_id"] == PID and hits[0]["asserted"] == "wrong"
    assert hits[0]["status_words"] == "could not be checked"


def test_negative_control_the_origin_main_grade_passes_the_same_text():
    """origin/main served this text because nothing compared it with the CURRENT grade: against the stale
    (pre-correction) grade it is consistent — so the instrument fails only because the grade changed."""
    assert verdict_claims.findings(STORED_READ, CALLS_ON_MAIN, as_of="2026-11-02") == []


def test_a_confirmed_call_corrected_to_refuted_makes_its_right_verdict_a_finding():
    calls = [
        {"prediction_id": "p_hrv", "claim": "HRV running average will keep edging upward", "status": "refuted", "said_on": "2026-10-01"}
    ]
    text = "My call that the HRV running average would keep edging upward was right, and I said so last week."
    assert verdict_claims.findings(text, calls, as_of="2026-10-20")[0]["asserted"] == "right"
    calls[0]["status"] = "confirmed"
    assert verdict_claims.findings(text, calls, as_of="2026-10-20") == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Marcus Webb is right that dinner underperforms.",  # a colleague's point, not a call's verdict
        "The clean sheet tells me I haven't been wrong yet.",  # negated
        "Two confirmed calls this quarter, zero refuted.",  # a tally
    ],
)
def test_not_a_verdict_on_a_call(sentence):
    assert verdict_claims.polarity(sentence) is None


def test_a_call_outside_the_lookback_is_not_a_candidate():
    old = [{"prediction_id": "p_old", "claim": CLAIM, "status": "expired", "said_on": "2026-06-01"}]
    assert verdict_claims.findings(STORED_READ, old, as_of="2026-11-02") == []


# ── generation inputs read the current grade ───────────────────────────────────────────────────────


def test_reconcile_puts_a_learning_row_at_its_current_grade_with_the_recorded_reason():
    rec = {"sk": "LEARNING#2026-10-29#x", "prediction_id": PID, "status": "refuted", "reason": "[window] trend=down predicted=up"}
    out, notes = ag.reconcile([rec], {PID: _row()})
    assert rec["status"] == "refuted", "the stored row is never mutated"
    assert out[0]["status"] == "expired"
    assert out[0]["grade_correction"]["original_status"] == "refuted"
    assert out[0]["reason"].startswith(
        "Re-graded on 3 November 2026 from refuted to expired. Recorded reason: The call was graded, but on criteria"
    )
    assert notes and notes[0]["explanation"].startswith("The call was graded, but on criteria that measured something other")


def test_an_unreadable_partition_withholds_graded_learning_rows_from_the_prompt():
    out, _ = ag.reconcile([{"prediction_id": PID, "status": "refuted"}, {"status": "confirmed"}], None)
    assert out == [{"status": "confirmed"}]


def test_the_prompt_contract_forbids_verdicts_and_invented_explanations():
    c = verdict_claims.PROMPT_CONTRACT
    assert "must not be described" in c and "word for word" in c and "Never explain why a correction happened" in c
    line = verdict_claims.correction_lines([{**ag.note_of(_row()), "claim": CLAIM}])[0]
    assert "re-graded from refuted (wrong) to expired (could not be checked)" in line and "Recorded reason: The call was graded" in line


# ── the writer: verdict check + provenance stamp ─────────────────────────────────────────────────────


class _Table:
    def __init__(self, brief=None):
        self.brief = brief

    def get_item(self, Key):
        if Key["sk"].startswith("BRIEF#") and self.brief is not None:
            return {"Item": {"brief": {"derived_from_predictions": self.brief}}}
        return {}


def test_the_writer_holds_contradicting_derived_prose_and_serves_a_records_summary(monkeypatch):
    monkeypatch.setattr(ag, "prediction_rows", lambda table, coach_id: {PID: _row()})
    item = {
        "content": "A dated narrative with no verdict in it.",
        "public_summary": STORED_READ,
        "observatory_summary": "fine",
        "created_at": "x",
    }
    derived_text_guard.guard_output_item(item, _Table(brief=[PID]), "mind_coach", "2026-11-04", now="2026-11-04T18:00:00+00:00")
    assert item["derived_prose_held"] is True and item["observatory_summary"] is None
    assert (
        item["public_summary"]
        == "My read of 4 November 2026 is withheld until it is rewritten: it described a call's grade differently from the ledger."
    )
    assert item["verdict_findings"][0]["prediction_id"] == PID
    assert item["derived_from"] == {
        "as_of": "2026-11-04T18:00:00+00:00",
        "predictions": [PID],
        "records": ["COACH#mind_coach/BRIEF#2026-11-04"],
    }


def test_the_writer_stamps_and_passes_a_clean_read(monkeypatch):
    monkeypatch.setattr(ag, "prediction_rows", lambda table, coach_id: {PID: _row()})
    item = {"content": "The walks are flat.", "public_summary": "The evening walks stayed flat this week, per the watch."}
    derived_text_guard.guard_output_item(item, _Table(brief=None), "mind_coach", "2026-11-04", now="2026-11-04T18:00:00+00:00")
    assert item["public_summary"].startswith("The evening walks") and "verdict_findings" not in item
    assert "predictions" not in item["derived_from"], "no brief: the calls are unknown, never an empty list"


# ── read time: a stored read a correction overtook ───────────────────────────────────────────────────


def _freshness(monkeypatch, corrections, public=False):
    from web import derived_summary_freshness as f, trail_corrections

    monkeypatch.setattr(ag, "verdict_corrections", lambda table, coach_id: corrections)
    monkeypatch.setattr(trail_corrections, "ledger_withholds", lambda coach_id, row: not public)

    class T:
        def get_item(self, Key):
            return {"Item": _row()}

    return f, T()


def test_the_dashboard_read_overtaken_by_a_correction_is_replaced_by_the_dated_records_summary(monkeypatch):
    f, table = _freshness(monkeypatch, [_correction_row()])
    entry = {"position_summary": STORED_READ}
    out = f.apply_to_entry(entry, table, "mind_coach", {"created_at": "2026-11-02T18:03:20+00:00", "public_summary": STORED_READ})
    assert "mechanism was wrong" not in out["position_summary"]
    assert out["position_summary"] == (
        "My read of 2 November 2026 is withheld until it is rewritten: on 3 November 2026 one of my calls was re-graded "
        "from wrong to could not be checked."
    )
    assert out["summary_state"] == "superseded_by_correction"
    assert out["derived_from"]["built_from"] == "ledger_records" and out["derived_from"]["superseded_read_as_of"].startswith("2026-11-02")
    (c,) = out["summary_corrections"]
    assert c["prediction_id"] is None, "a call the public ledger withholds is not named"
    assert c["explanation"].startswith("The call was graded, but on criteria that measured")


def test_a_read_newer_than_every_correction_is_current_with_its_as_of(monkeypatch):
    f, table = _freshness(monkeypatch, [_correction_row()], public=True)
    item = {"created_at": "2026-11-04T18:00:00+00:00", "derived_from": {"as_of": "2026-11-04T18:00:00+00:00", "predictions": [PID]}}
    out = f.apply_to_entry({"position_summary": "A new read."}, table, "mind_coach", item)
    assert out["position_summary"] == "A new read." and out["summary_state"] == "current"
    assert out["summary_as_of"] == "2026-11-04T18:00:00+00:00" and out["derived_from"]["predictions"] == [PID]


def test_a_cited_read_is_stale_only_for_its_own_calls(monkeypatch):
    f, table = _freshness(monkeypatch, [_correction_row(pid="pred_other")], public=True)
    item = {"created_at": "2026-11-02T18:00:00+00:00", "derived_from": {"as_of": "2026-11-02T18:00:00+00:00", "predictions": [PID]}}
    assert f.apply_to_entry({"position_summary": "A read."}, table, "mind_coach", item)["summary_state"] == "current"


def test_a_restate_never_supersedes_a_read():
    # verdict_corrections drops restates at the read; stale_corrections sees only verdict changes
    assert ag.stale_corrections({"created_at": "2026-11-01"}, []) == []


def test_an_unreadable_correction_ledger_withholds_the_read(monkeypatch):
    from web import derived_summary_freshness as f

    def boom(table, coach_id):
        raise RuntimeError("throttled")

    monkeypatch.setattr(ag, "verdict_corrections", boom)
    out = f.apply_to_entry({"position_summary": STORED_READ}, object(), "mind_coach", {"created_at": "2026-11-02"})
    assert out["position_summary"] == "" and out["summary_state"] == "unverified"


def test_a_dated_timeline_quote_keeps_its_words_and_gains_a_dated_correction(monkeypatch):
    from web import derived_summary_freshness as f, trail_corrections

    monkeypatch.setattr(ag, "prediction_rows", lambda table, coach_id: {PID: _row()})
    monkeypatch.setattr(trail_corrections, "ledger_withholds", lambda coach_id, row: False)

    class T:
        def get_item(self, Key):
            return {"Item": _row()}

    entries = [{"date": "2026-11-02", "summary": STORED_READ}]
    out = f.annotate_timeline(entries, T(), "mind_coach")
    assert out[0]["summary"] == STORED_READ, "verbatim — never rewritten"
    (c,) = out[0]["grade_corrections"]
    assert (c["original_status"], c["corrected_status"], c["corrected_at"]) == ("refuted", "expired", "2026-11-03T18:55:07Z")
    assert c["prediction_id"] == PID


# ── the Day page: a verbatim line keeps its words; a dated correction stands beside it ───────────────


def test_a_day_line_keeps_its_words_and_gains_the_recorded_correction():
    from publish_snapshot_corrections import annotate_coach_lines

    text = "I was wrong — my read that protein recovery would lift the evening walks didn't hold."
    days = [{"date": "2026-11-01", "coach_lines": [{"coach": "Nathan Reeves", "coach_id": "mind_coach", "text": text}]}]
    pred = {
        "id": f"mind-{PID}",
        "coach_id": "mind_coach",
        "coach_name": "Nathan Reeves",
        "claim": CLAIM,
        "status": "expired",
        "logged_date": "2026-10-15",
        "corrections": [
            {
                "original_status": "refuted",
                "corrected_status": "expired",
                "corrected_at": "2026-11-03T18:55:07Z",
                "explanation": "A registered explanation.",
            }
        ],
    }
    annotate_coach_lines(days, [pred])
    line = days[0]["coach_lines"][0]
    assert line["text"] == text
    assert line["corrections"] == [
        "Correction: Nathan Reeves's call of Thursday 15 October was re-graded on Tuesday 3 November from wrong to could not be checked. "
        "A registered explanation."
    ]
    annotate_coach_lines(days)  # no ledger handed in: the verdict check adds nothing (silence is never a correction)
    assert days[0]["coach_lines"][0]["corrections"] == []


def test_the_ledger_and_the_writers_share_one_status_rule():
    from web import site_api_ledger_export

    for row in (_row(), _row(status="observation"), {"status": "pending", "evaluation": {"type": "qualitative"}}, {"status": "weird"}):
        assert site_api_ledger_export.bucket_status(row) == ag.status_of(row)


def test_the_agreement_check_flags_an_unannotated_quote_and_passes_an_annotated_one():
    import check_coach_verdict_agreement as chk

    page = (
        '<figure class="voice"><figcaption class="who">Nathan Reeves · On a result</figcaption>'
        f'<blockquote data-verbatim="coach" data-said="2026-11-01">{STORED_READ}</blockquote></figure>'
    )
    calls = [{**CALLS_NOW[0], "coach": "mind"}]
    names = {"Nathan Reeves": "mind"}
    (f,) = chk.check_day_html("2026-11-01", page, calls, names)
    assert f["annotated"] is False
    annotated = page.replace("</figure>", '<p class="correction" role="note">Correction: …</p></figure>')
    assert chk.check_day_html("2026-11-01", annotated, calls, names)[0]["annotated"] is True
    payload = {"coaches": [{"coach_id": "mind", "position_summary": STORED_READ}]}
    assert chk.check_json("/api/coaching-dashboard", payload, calls, names)[0]["prediction_id"] == PID
    assert json.dumps(chk.check_json("/x", {"coaches": [{"coach_id": "mind", "position_summary": "Walks flat."}]}, calls, names)) == "[]"

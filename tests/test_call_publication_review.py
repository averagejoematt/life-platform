"""tests/test_call_publication_review.py — the owner's approved classifications and the review-only classification review
(owner rulings 2026-11-06). Every call here is SYNTHETIC.

Approved classifications (verbatim): "Mood, felt-sense and self-report calls remain private, including those referring
to a public morning note. Unnamed logging-gap predictions remain private where their meaning or evaluation could reveal
private activity. The fuel–cognition bet's private cognition component makes that combined prediction ineligible for
public release. A separately filed, independently evaluable nutrition prediction may remain public if it does not reveal
the private component. Thyroid predictions evaluated against public-eligible laboratory measurements may remain public;
requests to log symptoms remain private. New free-text observations remain private until explicitly reviewed."

The review (verbatim): "make it review-only. It may generate a proposed publication manifest; it must not automatically
approve or publish sensitive free text." The tests below prove the review cannot change publication: it reads only, it
writes only a private proposal outside the checkout, every proposed entry is unapproved, the registry and every
classification are byte-for-byte the same after it runs, and the owner's `approve` refuses what the rules hold private.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import prediction_publication_registry as S  # noqa: E402
from call_publication_fixtures import registered  # noqa: E402
from common import (
    prediction_publication as PP,  # noqa: E402
    prediction_publication_registry as REG,  # noqa: E402
)

PK = "COACH#nutrition_coach"
NEW = "2026-11-07T12:00:00+00:00"
LEGACY = "2026-10-20T12:00:00+00:00"
GRADEABLE = {"verdict": "gradeable"}


def _call(pid, claim, metric="total_protein_g", at=NEW, verdict="gradeable", **extra):
    row = {
        "pk": PK,
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "created_at": at,
        "claim_natural": claim,
        "evaluation": {"type": "directional", "metric": metric, "condition": "up"},
    }
    if verdict:
        row["filing"] = {"verdict": verdict}
    row.update(extra)
    return row


# ── 1. mood, felt sense, self-report (the public morning note included) ─────────────────────


@pytest.mark.parametrize(
    "claim",
    [
        "If his mood lifts, recovery will rise this week.",
        "Recovery will rise this week, matching how he feels on waking.",
        "Once morning notes resume, recovery will rise above 60.",
        "If the felt sense and recovery agree, recovery will hold above 60.",
        "Recovery will rise if the subjective rating does.",
        "After the next check-in, protein will climb above 150 g.",
    ],
)
def test_a_self_report_call_is_private_even_when_graded_on_a_public_metric(claim):
    assert PP.classify(PK, _call("pred_20261107_sr", claim)) == (PP.PRIVATE, "private_words")


# ── 2. unnamed logging gaps ─────────────────────────────────────────────────────────────────


def test_an_unnamed_logging_gap_is_private_and_a_named_public_log_is_not():
    assert PP.classify(PK, _call("pred_20261107_g1", "If logging resumes this week, recovery will rise.", "recovery_score")) == (
        PP.PRIVATE,
        "private_words",
    )
    assert not PP.row_is_public(PK, _call("pred_20261107_g2", "After the logging gap, recovery will rise.", "recovery_score"))
    assert PP.row_is_public(PK, _call("pred_20261107_g3", "Once meal logging resumes, protein will climb above 150 g."))


# ── 3. the fuel-cognition bet, and a separately filed nutrition call ─────────────────────────


def test_a_bet_is_private_as_a_whole_until_reviewed():
    """Neither side, the docket entry nor a docket learning is published before the owner reviews the bet."""
    side_a = {
        "pk": "COACH#mind_coach",
        "sk": "PREDICTION#docket-a__b-protein-x-2026-11-07",
        "prediction_id": "docket-a__b-protein-x-2026-11-07",
        "created_at": NEW,
        "source": "dispute_docket",
        "metric": "total_protein_g_7day_avg",
        "claim_natural": "A synthetic side about a private component.",
    }
    side_b = {**side_a, "pk": PK, "claim_natural": "Protein will reach 190 g by the deadline."}  # clean on its own
    entry = {"pk": PP.DOCKET_PK, "sk": "OPEN#a__b#protein", "opened_at": NEW, "criterion": {"metric": "total_protein_g_7day_avg"}}
    learning = {"pk": PK, "sk": "LEARNING#2026-11-08#docket-a__b-protein-x", "docket_ref": "OPEN#a__b#protein", "created_at": NEW}
    for row in (side_a, side_b, entry, learning):
        assert PP.classify(row["pk"], row) == (PP.PRIVATE, PP.UNREVIEWED_BET), row["sk"]


def test_a_separately_filed_nutrition_call_is_public_only_without_the_private_component():
    clean = _call("pred_20261107_n1", "Protein will climb above 150 g within two weeks.")
    assert PP.classify(PK, clean) == (PP.PUBLIC, "structured_public")
    reveals = _call("pred_20261107_n2", "Protein above 150 g will lift cognitive capacity.")
    assert PP.classify(PK, reveals) == (PP.PRIVATE, "private_words")


# ── 4. thyroid: lab-graded public after review; symptom logging private ────────────────────


def test_thyroid_lab_calls_wait_for_review_and_symptom_requests_stay_private():
    lab = _call("pred_20261107_t1", "The next panel's free T3 will sit inside the reference range.", metric=None, verdict="observation")
    assert PP.classify(PK, lab) == (PP.PRIVATE, "unclassified_subject")
    with registered([lab]):
        assert PP.row_is_public(PK, lab)  # explicitly reviewed and approved
    for words in (
        "Log fatigue on a 1-10 scale and walk after dinner.",
        "Report cold intolerance daily and keep steps up.",
        "Start a symptom log.",
    ):
        ask = {"pk": PK, "sk": "COMMITMENT#c_t", "created_at": NEW, "commitment_natural": words, "action_check": {"metric": "steps"}}
        assert not PP.row_is_public(PK, ask), words
    assert not PP.row_is_public(PK, _call("pred_20261107_t2", "Fatigue will emerge before the next panel.", "steps"))


# ── 5. new free-text observations ───────────────────────────────────────────────────────────


def test_a_new_free_text_observation_is_private_until_explicitly_reviewed():
    obs = _call("pred_20261107_o1", "A synthetic observation about the week.", metric=None, verdict="observation")
    assert PP.classify(PK, obs) == (PP.PRIVATE, "unclassified_subject")
    with registered([obs]):
        assert PP.classify(PK, obs) == (PP.PUBLIC, "registry")


# ── the review: review-only, private, approves nothing ──────────────────────────────────────


class _ReadOnlyTable:
    """Records every call; any write fails the test."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def query(self, **kw):
        self.calls.append("query")
        pk = kw["KeyConditionExpression"].get_expression()["values"][1]
        return {"Items": [r for r in self.rows if r["pk"] == pk]}

    def get_item(self, Key=None, **_kw):
        self.calls.append("get_item")
        return {"Item": next((r for r in self.rows if r["pk"] == Key["pk"] and r["sk"] == Key["sk"]), None)}

    def __getattr__(self, name):
        raise AssertionError(f"the review called {name} — it may only read")


def _rows():
    return [
        _call("pred_20261107_o1", "A synthetic observation about the week.", metric=None, verdict="observation"),
        _call("pred_20261107_w1", "If he journals, protein will climb.", pk="COACH#nutrition_coach"),
        _call("pred_20261107_p1", "Protein will climb above 150 g within two weeks."),
        _call("pred_20261020_legacy", "A synthetic legacy call.", at=LEGACY),
    ]


def _digest_file():
    return hashlib.sha256(S.TARGET.read_bytes()).hexdigest()


def test_the_review_reads_only_and_changes_no_classification(tmp_path):
    rows = _rows()
    table = _ReadOnlyTable(rows)
    before_file, before_set = _digest_file(), REG.PUBLIC_DIGESTS
    before = [PP.classify(r["pk"], r) for r in rows]
    out = tmp_path / "private" / "proposed.json"
    assert S.cmd_review(str(out), table=table) == 0
    assert set(table.calls) <= {"query", "get_item"}
    assert _digest_file() == before_file and REG.PUBLIC_DIGESTS is before_set
    assert [PP.classify(r["pk"], r) for r in rows] == before
    doc = json.loads(out.read_text())
    assert doc["status"].startswith("proposed") and (out.stat().st_mode & 0o777) == 0o600
    entries = doc["entries"]
    # Only what the rules leave to the owner is proposed: the free-text observation — not the journal-worded call
    # (held by rule), not the public call, not the legacy call the review already decided.
    assert [e["key"] for e in entries] == ["pred_20261107_o1"]
    assert all(e["approve"] is False for e in entries)


def test_the_review_refuses_to_write_inside_the_repository(tmp_path):
    table = _ReadOnlyTable(_rows())
    target = ROOT / "docs" / "reviews" / "proposed-call-review.json"
    assert S.cmd_review(str(target), table=table) == 2
    assert not target.exists() and table.calls == []
    with pytest.raises(ValueError):
        S.write_proposal([], ROOT / "x.json")


def test_approve_adds_only_what_the_owner_approved_and_refuses_what_the_rules_hold(tmp_path):
    entries = S.pending({PK: _rows()})
    target = tmp_path / "registry.py"
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"entries": entries}))
    assert S.cmd_approve(str(manifest), target=target) == 0 and not target.exists()  # nothing approved: no write
    manifest.write_text(json.dumps({"entries": [{**entries[0], "approve": True}]}))
    assert S.cmd_approve(str(manifest), target=target) == 0
    assert PP.digest(PK, "pred_20261107_o1") in target.read_text()
    held = {"pk": PK, "key": "pred_20261107_w1", "kind": "call", "reason": "private_words", "approve": True}
    manifest.write_text(json.dumps({"entries": [held]}))
    target.unlink()
    assert S.cmd_approve(str(manifest), target=target) == 2 and not target.exists()


def test_the_review_rides_the_existing_weekly_review_clock():
    """No schedule of its own: the obligation is on the weekly `fullreview-delta` calendar entry."""
    import operating_calendar as oc

    obligations = oc.CALENDAR["fullreview-delta"]["obligations"]
    assert any("prediction_publication_registry.py review" in o and "Approve nothing" in o for o in obligations)

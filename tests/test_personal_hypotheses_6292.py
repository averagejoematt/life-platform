"""tests/test_personal_hypotheses_6292.py — #6292: revisable, evidence-linked hypotheses about the person.

A second record kind in the research findings partition (`research/hypotheses.py`), one owner tool
(`manage_personal_hypothesis`), every write queue-only through the #6287 approval scope. Covered here, over one
in-memory table that honours the calls the code makes:
  * a direct mutating call writes nothing (every write action), enqueue -> discard writes nothing, enqueue -> approve
    writes exactly one row carrying the approval stamp; reads are direct; a read cannot be queued;
  * the record shape: >= 2 competing explanations, evidence with direction / explanation / evidence_kind / source_ref /
    date, confidence from a closed word list, no literature source needed — while a research finding still needs one;
  * the language tripwire: no diagnosis or condition named as a claim, no confidence as a number;
  * his rejection is his words, verbatim, final until he reopens; a rejected hypothesis is kept, shown as rejected and
    never re-proposed; a correction restates wording and keeps what it replaced;
  * the open cap, the "propose retirement" flag after 3 conversations with no new evidence (never auto-retired);
  * fold ignores a row without an approval stamp and an event the rules refuse;
  * the boundary: no coach / AI / web / email / content module can import the kind, the prompt seam is off and uncalled;
  * the scripted demonstration (scripts/demo_personal_hypothesis.py) passes in a subprocess.

All fixtures are synthetic and impersonal (the repo is public).
"""

# premerge-gate: sweeps lambdas/ and mcp/ (rglob + the import graph) for callers of the off prompt seam, site routes naming the kind, and import paths from coach/AI/web modules into it

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai import platform_memory as pm  # noqa: E402
from research import (
    findings as rf,  # noqa: E402
    hypotheses as ph,  # noqa: E402
)

import mcp.audit as mcp_audit  # noqa: E402
import mcp.tools_pending_writes as tpw  # noqa: E402
import mcp.tools_personal_hypotheses as tph  # noqa: E402
import mcp.tools_research_findings as trf  # noqa: E402

TOOL = "manage_personal_hypothesis"
TODAY = "2026-11-20"  # a fixed Pacific day — no assertion below reads the live clock
PART = ph.pk("matthew")


class ConditionalCheckFailedException(Exception):
    pass


class WireTable:
    def __init__(self):
        self.store: dict = {}
        self.calls: list = []

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        self.calls.append(("put_item", Item["pk"], Item["sk"]))
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression == "attribute_not_exists(sk)":
            if existing is not None:
                raise ConditionalCheckFailedException("attribute_not_exists(sk)")
        elif ConditionExpression == "#st = :expected":
            if existing is None or existing.get("status") != ExpressionAttributeValues[":expected"]:
                raise ConditionalCheckFailedException("status mismatch")
        else:
            raise AssertionError(f"unexpected condition {ConditionExpression!r}")
        self.store[key] = json.loads(json.dumps(Item, default=str))
        return {}

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExclusiveStartKey=None, **kwargs):
        if isinstance(KeyConditionExpression, str):
            eav = ExpressionAttributeValues
            rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and s.startswith(eav[":pfx"])]
        else:
            exp = KeyConditionExpression.get_expression()
            pk = exp["values"][0].get_expression()["values"][1]
            prefix = exp["values"][1].get_expression()["values"][1]
            rows = [v for (p, s), v in self.store.items() if p == pk and s.startswith(prefix)]
        return {"Items": sorted((dict(r) for r in rows), key=lambda r: r["sk"])}

    def part_rows(self, prefix=""):
        return [v for (p, s), v in self.store.items() if p == PART and s.startswith(prefix)]

    def part_writes(self):
        return [c for c in self.calls if c[0] == "put_item" and c[1] == PART]


@pytest.fixture
def wire(monkeypatch):
    t = WireTable()
    monkeypatch.setattr(tpw, "_table_ref", t)
    monkeypatch.setattr(tph, "_table_ref", t)
    monkeypatch.setattr(tph, "_user_id_ref", "matthew")
    monkeypatch.setattr(tph, "pacific_today", lambda: TODAY)
    monkeypatch.setattr(trf, "_table_ref", t)
    monkeypatch.setattr(trf, "_user_id_ref", "matthew")
    monkeypatch.setattr(trf, "pacific_today", lambda: TODAY)
    monkeypatch.setattr(mcp_audit, "record_mutation", lambda *a, **k: None)
    return t


def _propose(**over):
    a = {
        "action": "propose",
        "question": "Why does the fictional subject skip Thursday piano practice more than other days?",
        "dedupe_key": "thursday-piano-practice",
        "explanations": [
            {"label": "Late meetings", "statement": "Thursday work runs late, leaving less time and energy for practice."},
            {"label": "Piece dread", "statement": "The hardest piece is scheduled on Thursday and is the one avoided."},
        ],
        "distinguishing": "Whether practice slips on other late days, and whether moving the hard piece moves the skip.",
        "confidence": {"word": "too_early"},
        "questions_worth_asking": ["Does a late Tuesday look like a usual Thursday?"],
        "proposed_by": "reflect conversation (test)",
        "provenance": "synthetic test session",
        "wording_is": "session_summary",
    }
    a.update(over)
    return a


def _evidence(hid, **over):
    ev = {
        "direction": "supports",
        "explanations": ["a"],
        "evidence_kind": "self_report",
        "source_ref": "test-journal-0001",
        "date": "2025-spring",
        "statement": "Three of four skipped Thursdays followed a meeting that ran late.",
    }
    ev.update(over)
    return {"action": "add_evidence", "hypothesis_id": hid, "evidence": ev}


def _enqueue(args):
    return tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": TOOL, "target_args": args, "summary": "synthetic"})


def _approved(args):
    q = _enqueue(args)
    assert q.get("queued"), q
    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert res.get("approved") is True, res
    return res["target_result"]


def _new(wire, **over):
    return _approved(_propose(**over))["hypothesis_id"]


def _get(hid):
    return tph.tool_manage_personal_hypothesis({"action": "get", "hypothesis_id": hid})["hypothesis"]


def _refused_at_enqueue(args, needle):
    q = _enqueue(args)
    assert "error" in q and needle in q["error"], q
    return q


REJECT = {"view": "reject", "words": "Neither. It is the night the neighbour practises drums.", "words_are": "owner_verbatim"}


# ── enforcement: queue-only writes, direct reads ────────────────────────────────────────────────


def test_a_direct_mutating_call_writes_nothing_for_every_write_action(wire):
    hid = _new(wire)
    before = len(wire.part_writes())
    for action in tph.WRITE_ACTIONS:
        args = _propose(dedupe_key="another-question") if action == "propose" else {"action": action, "hypothesis_id": hid}
        res = tph.tool_manage_personal_hypothesis(args)
        assert "QUEUE-ONLY" in res.get("error", ""), (action, res)
        assert res["queue_tool"] == "manage_pending_writes"
    assert len(wire.part_writes()) == before, "a direct call wrote to the partition"


def test_an_approval_scope_for_another_tool_does_not_open_this_one(wire):
    from coach import pending_writes as pw

    with pw.approval_scope("20261120T000000Z-0000abcd", "write_platform_memory", "2026-11-20T00:00:00+00:00"):
        res = tph.tool_manage_personal_hypothesis(_propose())
    assert "QUEUE-ONLY" in res["error"] and not wire.part_rows()


def test_enqueue_then_approve_writes_exactly_one_stamped_head(wire):
    q = _enqueue(_propose())
    assert q["queued"] and not wire.part_rows(), "queued is not written"
    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert res["approved"] is True
    (head,) = wire.part_rows(ph.HEAD_PREFIX)
    assert head["record_type"] == "personal_hypothesis" and head["sk"] == ph.head_sk(head["hypothesis_id"])
    assert head["approved_via"]["pending_id"] == q["pending_id"] and head["approved_via"]["approved_at"]
    assert ph.valid_hypothesis_id(head["hypothesis_id"])


def test_enqueue_then_discard_writes_nothing(wire):
    q = _enqueue(_propose())
    out = tpw.tool_manage_pending_writes({"action": "discard", "pending_id": q["pending_id"], "reason": "not this"})
    assert out["discarded"] is True
    assert not wire.part_rows() and not wire.part_writes()


def test_reads_are_direct_and_cannot_be_queued(wire):
    hid = _new(wire)
    assert tph.tool_manage_personal_hypothesis({"action": "list"})["hypotheses"][0]["hypothesis_id"] == hid
    assert _get(hid)["hypothesis_id"] == hid
    for action in ("list", "get"):
        _refused_at_enqueue({"action": action, "hypothesis_id": hid}, "is a read")


def test_an_invalid_item_is_never_queued(wire):
    _refused_at_enqueue(_propose(explanations=[{"label": "Only one", "statement": "A single explanation is not a competing set."}]), "2-5")
    assert tpw.tool_manage_pending_writes({"action": "list"})["open_count"] == 0


# ── the record shape ────────────────────────────────────────────────────────────────────────────


def test_the_record_holds_question_rivals_evidence_distinguisher_confidence_asks_view_and_status(wire):
    hid = _new(wire)
    _approved({**_evidence(hid), "confidence": {"word": "leaning", "leaning_toward": "a"}})
    _approved(_evidence(hid, direction="counts_against", evidence_kind="owner_statement", source_ref="test-chat-0002", date="2025-05"))
    v = _get(hid)
    assert [e["key"] for e in v["explanations"]] == ["a", "b"]
    assert v["distinguishing"] and v["questions_worth_asking"] and v["status"] == "exploratory"
    assert v["confidence"] == {"word": "leaning", "leaning_toward": "a"} and "leaning" in v["confidence_in_words"]
    assert [(e["direction"], e["explanations"], e["evidence_kind"]) for e in v["evidence"]] == [
        ("supports", ["a"], "self_report"),
        ("counts_against", ["a"], "owner_statement"),
    ]
    assert v["evidence"][0]["date"] == "2025-spring" and v["evidence"][0]["date_precision"] == "season"
    assert v["evidence"][0]["source_ref"] == "test-journal-0001"


def test_no_literature_source_is_needed_for_a_hypothesis_and_a_finding_still_needs_one(wire):
    hid = _new(wire)
    assert "sources" not in wire.part_rows(ph.head_sk(hid))[0]
    res = trf.tool_manage_research_finding(
        {
            "action": "record",
            "question": "Does a fixed wake time improve sleep consistency in adults?",
            "dedupe_key": "fixed-wake-time",
            "sources": [],
            "evidence_summary": "Synthetic summary: trials suggest a modest effect.",
            "evidence_strength": "moderate",
            "applicability": {"text": "Adults.", "population_match": "partial"},
            "limitations": "Short trials.",
            "risk_tier": 2,
            "touches": ["sleep"],
            "clinical_review_required": False,
            "risk_rationale": "Synthetic: a reversible routine change.",
            "responsible_coach": "sleep_coach",
            "review_by": "2027-02-20",
            "origin": "prospective",
            "surfaced_by": "owner",
            "date": TODAY,
        }
    )
    assert "verified sources" in json.dumps(res) and not wire.part_rows(rf.HEAD_PREFIX)


def test_findings_and_hypotheses_share_the_partition_and_never_fold_into_each_other(wire):
    _new(wire)
    rows = [r for (p, _s), r in wire.store.items() if p == PART]
    assert rf.fold(rows) == [] and len(ph.fold(rows)) == 1
    assert rf.read_rows(wire, "matthew") == [], "the findings read prefix does not reach HYPOTHESIS# rows"


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"explanations": [{"label": "One", "statement": "Only a single explanation is offered here."}]}, "2-5"),
        ({"confidence": {"word": "70 percent"}}, "confidence is a word"),
        ({"confidence": {"word": "leaning"}}, "leaning_toward"),
        ({"confidence": {"word": "mixed", "leaning_toward": "a"}}, "leans toward nothing"),
        ({"wording_is": "model"}, "wording_is"),
        ({"dedupe_key": "Not A Slug"}, "dedupe_key"),
    ],
)
def test_the_proposal_fields_are_validated(wire, over, needle):
    _refused_at_enqueue(_propose(**over), needle)


def test_the_enums_in_the_schema_equal_the_registry():
    props = tph.MANAGE_HYPOTHESIS_INPUT["properties"]
    assert props["action"]["enum"] == list(tph.ACTIONS)
    assert props["view"]["enum"] == list(ph.OWNER_VIEWS)
    assert props["wording_is"]["enum"] == list(rf.WORDS_ARE)
    assert props["words_are"]["enum"] == list(ph.OWNER_VIEW_WORDS_ARE)
    assert props["status"]["enum"] == list(ph.SETTABLE_STATUSES) + list(tph.LIST_STATUSES)
    for kind in pm.EVIDENCE_KINDS:
        assert kind in props["evidence"]["description"], kind
    assert ph.EVIDENCE_KINDS is pm.EVIDENCE_KINDS, "the evidence vocabulary is #6287's, reused — not a copy"
    assert set(ph.STATUSES) == {"exploratory", "supported", "contradicted", "retired", "unresolved"}


# ── interpretation, not diagnosis ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "field, text",
    [
        ("question", "Is the subject's Thursday skipping a sign of an anxiety disorder?"),
        ("question", "Does the subject have ADHD that explains the missed Thursday sessions?"),
        ("distinguishing", "A formal diagnosis would settle which explanation holds for the subject."),
        ("question", "Which explanation is right, with a confidence of 80% for the first one?"),
    ],
)
def test_diagnostic_language_and_numeric_confidence_are_refused(wire, field, text):
    q = _enqueue(_propose(**{field: text}))
    assert "error" in q and ("diagnosis" in q["error"] or "as a number" in q["error"]), q


def test_an_explanation_or_evidence_statement_is_held_to_the_same_tripwire(wire):
    bad = _propose(explanations=[_propose()["explanations"][0], {"label": "A syndrome", "statement": "It is a syndrome he has."}])
    _refused_at_enqueue(bad, "diagnosis")
    hid = _new(wire)
    _refused_at_enqueue(_evidence(hid, statement="A clinician's diagnosis explains the Thursday pattern."), "diagnosis")
    _approved(_evidence(hid, statement="Skipped on 3 of 4 Thursdays, 75% of them after late meetings."))  # numbers are fine as evidence


# ── his view: confirm, correct, reject, not interested ───────────────────────────────────────────


def test_a_rejection_is_his_words_verbatim_and_final_until_he_reopens(wire):
    hid = _new(wire)
    _refused_at_enqueue({"action": "owner_view", "hypothesis_id": hid, **{**REJECT, "words_are": "owner_adopted_text"}}, "owner_verbatim")
    _refused_at_enqueue({"action": "owner_view", "hypothesis_id": hid, "view": "reject", "words_are": "owner_verbatim"}, "his words")
    _approved({"action": "owner_view", "hypothesis_id": hid, **REJECT})
    v = _get(hid)
    assert (
        v["closed_by_owner"]
        and not v["open"]
        and v["owner_view_words"] == REJECT["words"]
        and v["owner_view_words_are"] == "owner_verbatim"
    )
    for args in (
        _evidence(hid),
        {"action": "set_status", "hypothesis_id": hid, "status": "unresolved", "reason": "stalled for now"},
        {"action": "retire", "hypothesis_id": hid, "reason": "not useful any more"},
        {"action": "owner_view", "hypothesis_id": hid, "view": "confirm", "words": "Fine.", "words_are": "owner_verbatim"},
        {"action": "note_conversation", "hypothesis_id": hid, "session_ref": "test-session-0001"},
    ):
        _refused_at_enqueue(args, "until he reopens")


def test_a_rejected_hypothesis_is_kept_listed_as_rejected_and_never_re_proposed(wire):
    hid = _new(wire)
    _approved({"action": "owner_view", "hypothesis_id": hid, **REJECT})
    (row,) = tph.tool_manage_personal_hypothesis({"action": "list"})["hypotheses"]
    assert row["rejected"] is True and row["state_in_words"] == "closed by Matthew (reject)"
    assert tph.tool_manage_personal_hypothesis({"action": "list", "status": "closed"})["hypotheses"][0]["hypothesis_id"] == hid
    q = _refused_at_enqueue(_propose(question="Reworded: why are Thursday piano sessions the ones that get skipped?"), "only he can reopen")
    assert "Matthew" in q["error"]
    assert len(wire.part_rows(ph.head_sk(hid))) == 2  # the head and the rejection — nothing removed


def test_he_reopens_in_his_own_words_only(wire):
    hid = _new(wire)
    _approved({"action": "owner_view", "hypothesis_id": hid, **REJECT})
    _refused_at_enqueue(
        {"action": "reopen", "hypothesis_id": hid, "words": "Reopen it.", "words_are": "owner_adopted_text"}, "owner_verbatim"
    )
    _approved({"action": "reopen", "hypothesis_id": hid, "words": "Reopen it, the drums stopped.", "words_are": "owner_verbatim"})
    v = _get(hid)
    assert v["open"] and v["status"] == "exploratory" and v["owner_view"] == "reopened"
    _approved(_evidence(hid))
    _refused_at_enqueue({"action": "reopen", "hypothesis_id": hid, "words": "Again.", "words_are": "owner_verbatim"}, "is open")


def test_not_interested_closes_it_like_a_rejection(wire):
    hid = _new(wire)
    _approved(
        {
            "action": "owner_view",
            "hypothesis_id": hid,
            "view": "not_interested",
            "words": "Not worth my time.",
            "words_are": "owner_verbatim",
        }
    )
    v = _get(hid)
    assert v["closed_by_owner"] and not v["open"]
    _refused_at_enqueue(_evidence(hid), "until he reopens")


def test_a_correction_restates_wording_and_keeps_what_it_replaced(wire):
    hid = _new(wire)
    change = {"explanations": {"b": {"statement": "Dreading the hardest piece, not tiredness, is the reason for skipping."}}}
    _refused_at_enqueue(
        {
            "action": "owner_view",
            "hypothesis_id": hid,
            "view": "correct",
            "words": "Fix b.",
            "words_are": "session_summary",
            "changes": change,
        },
        "words_are",
    )
    _approved(
        {
            "action": "owner_view",
            "hypothesis_id": hid,
            "view": "correct",
            "words": "Fix b.",
            "words_are": "owner_verbatim",
            "changes": change,
        }
    )
    v = _get(hid)
    assert v["explanations"][1]["statement"].startswith("Dreading") and v["explanations"][1]["label"] == "Piece dread"
    (corr,) = v["corrections"]
    assert corr["previous"]["explanations"][1]["statement"].startswith("The hardest piece")
    assert v["open"], "a correction keeps the hypothesis open"
    _refused_at_enqueue(
        {
            "action": "owner_view",
            "hypothesis_id": hid,
            "view": "correct",
            "words": "Again.",
            "words_are": "owner_verbatim",
            "changes": change,
        },
        "changes nothing",
    )
    assert "corrected it" in " ".join(h["text"] for h in v["history"])


def test_a_confirmation_may_name_the_explanation_he_endorses(wire):
    hid = _new(wire)
    _refused_at_enqueue(
        {"action": "owner_view", "hypothesis_id": hid, "view": "confirm", "words": "Yes.", "words_are": "owner_verbatim", "endorses": "z"},
        "endorses",
    )
    _approved(
        {
            "action": "owner_view",
            "hypothesis_id": hid,
            "view": "confirm",
            "words": "Yes, b.",
            "words_are": "owner_verbatim",
            "endorses": "b",
        }
    )
    v = _get(hid)
    assert v["owner_view"] == "confirm" and v["endorses"] == "b" and v["status"] == "exploratory", "a confirmation never sets a status"


# ── status, retirement, the cap, the flag ───────────────────────────────────────────────────────


def test_supported_or_contradicted_names_its_explanation_and_needs_evidence_in_that_direction(wire):
    hid = _new(wire)
    st = {"action": "set_status", "hypothesis_id": hid, "status": "supported", "reason": "the late-meeting pattern held"}
    _refused_at_enqueue(st, "names the explanation")
    _refused_at_enqueue({**st, "explanation": "a"}, "needs at least one evidence item")
    _approved(_evidence(hid))
    _approved({**st, "explanation": "a"})
    v = _get(hid)
    assert v["status"] == "supported" and v["status_explanation"] == "a"
    _refused_at_enqueue({**st, "explanation": "a"}, "already supported")
    _refused_at_enqueue({"action": "set_status", "hypothesis_id": hid, "status": "retired", "reason": "done now"}, "must be one of")


def test_retire_needs_a_reason_and_a_retired_hypothesis_takes_nothing_until_reopened(wire):
    hid = _new(wire)
    _refused_at_enqueue({"action": "retire", "hypothesis_id": hid}, "reason")
    _approved({"action": "retire", "hypothesis_id": hid, "reason": "the schedule changed, the question no longer applies"})
    assert _get(hid)["status"] == "retired" and not _get(hid)["open"]
    _refused_at_enqueue(_evidence(hid), "retired")
    _refused_at_enqueue(_propose(), "is retired")


def test_the_open_cap_refuses_an_eighth_and_names_the_way_out(wire):
    for i in range(ph.OPEN_CAP):
        _new(wire, dedupe_key=f"question-{i}", question=f"Synthetic open question number {i} about the fictional subject?")
    q = _refused_at_enqueue(_propose(dedupe_key="question-8"), "retire or resolve one first")
    assert f"the cap is {ph.OPEN_CAP}" in q["error"]
    first = ph.hypothesis_id_for("question-0")
    _approved({"action": "retire", "hypothesis_id": first, "reason": "resolved in conversation, no longer open"})
    _new(wire, dedupe_key="question-8")
    _refused_at_enqueue({"action": "reopen", "hypothesis_id": first, "words": "Bring it back.", "words_are": "owner_verbatim"}, "cap")


def test_three_conversations_without_new_evidence_flag_retirement_and_never_retire(wire):
    hid = _new(wire)
    for i in range(ph.RETIRE_PROPOSAL_AFTER):
        listing = tph.tool_manage_personal_hypothesis({"action": "list"})
        assert listing["proposed_for_retirement"] == [], i
        _approved({"action": "note_conversation", "hypothesis_id": hid, "session_ref": f"test-session-000{i}"})
    _refused_at_enqueue({"action": "note_conversation", "hypothesis_id": hid, "session_ref": "test-session-0000"}, "already recorded")
    listing = tph.tool_manage_personal_hypothesis({"action": "list"})
    (row,) = listing["hypotheses"]
    assert row["flag"] == "propose retirement" and listing["proposed_for_retirement"] == [hid]
    assert row["status"] == "exploratory" and row["open"], "flagged, never auto-retired"
    _approved(_evidence(hid))
    (row,) = tph.tool_manage_personal_hypothesis({"action": "list"})["hypotheses"]
    assert row["flag"] is None and row["conversations_since_new_evidence"] == 0


def test_a_repeated_evidence_item_is_refused(wire):
    hid = _new(wire)
    _approved(_evidence(hid))
    _refused_at_enqueue(_evidence(hid), "already on the hypothesis")
    _refused_at_enqueue(_evidence(hid, explanations=["z"]), "explanations")
    _refused_at_enqueue(_evidence(hid, evidence_kind="hunch"), "evidence_kind")
    _refused_at_enqueue(_evidence(hid, date="2099-01-01"), "future")


# ── the fold: only approved, rule-abiding rows count ────────────────────────────────────────────


def test_fold_ignores_an_unstamped_head_and_an_event_the_rules_refuse(wire):
    hid = _new(wire)
    _approved({"action": "owner_view", "hypothesis_id": hid, **REJECT})
    # A forged head without an approval stamp, and a forged evidence event on the rejected hypothesis.
    forged_head = dict(wire.part_rows(ph.head_sk(hid))[0])
    forged_head.update({"hypothesis_id": ph.hypothesis_id_for("forged"), "sk": ph.head_sk(ph.hypothesis_id_for("forged"))})
    forged_head.pop("approved_via")
    wire.store[(PART, forged_head["sk"])] = forged_head
    ev = {
        "pk": PART,
        "sk": ph.event_sk(hid, "2099-01-01T00:00:00.000Z", ph.EV_EVIDENCE),
        "record_type": ph.RECORD_TYPE_EVENT,
        "hypothesis_id": hid,
        "kind": ph.EV_EVIDENCE,
        "recorded_at": "2099-01-01T00:00:00.000Z",
        "recorded_by": "owner",
        "approved_via": {"pending_id": "20990101T000000Z-0000abcd", "approved_at": "x"},
        "evidence": {**_evidence(hid)["evidence"], "date_precision": "season"},
    }
    wire.store[(PART, ev["sk"])] = ev
    views = tph.tool_manage_personal_hypothesis({"action": "list"})["hypotheses"]
    assert [v["hypothesis_id"] for v in views] == [hid]
    assert views[0]["invalid_events"] == 1 and _get(hid)["evidence"] == []


def test_the_tool_never_updates_or_deletes():
    src = (ROOT / "mcp" / "tools_personal_hypotheses.py").read_text(encoding="utf-8")
    assert 'put_item(Item=row, ConditionExpression="attribute_not_exists(sk)")' in src
    for verb in ("update_item", "delete_item", "batch_write"):
        assert verb not in src, verb


# ── wiring and the boundary ─────────────────────────────────────────────────────────────────────


def test_the_tool_is_registered_as_a_write_with_replay_semantics_and_a_queue_precheck():
    from mcp_registry_ast import registered_tool_names

    from mcp import audit, idempotency

    assert TOOL in registered_tool_names((ROOT / "mcp" / "registry.py").read_text(encoding="utf-8"))
    assert audit.is_write_tool(TOOL)
    assert TOOL in idempotency.REPLAY_SEMANTICS
    assert tpw._target_precheck_error(TOOL, {"action": "list"}) is not None


def test_the_kind_lives_in_the_owner_only_cross_phase_partition():
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert ph.pk("matthew") == rf.pk("matthew"), "no new partition"
    assert field_tiers.SOURCE_TIERS[rf.SOURCE] == field_tiers.TIER_OWNER_ONLY
    assert phase_taxonomy.SOURCE_CLASS[rf.SOURCE] == phase_taxonomy.CROSS_PHASE


def test_the_prompt_seam_is_off_returns_nothing_and_nothing_calls_it(wire):
    hid = _new(wire)
    _approved({"action": "owner_view", "hypothesis_id": hid, "view": "confirm", "words": "Yes.", "words_are": "owner_verbatim"})
    assert ph.PROMPT_SEAM_ENABLED is False
    assert ph.prompt_interpretations(ph.fold(wire.part_rows())) == []
    callers = []
    for tree_root in ("lambdas", "mcp", "scripts"):
        for p in (ROOT / tree_root).rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                f = getattr(n, "func", None)
                if isinstance(n, ast.Call) and (getattr(f, "attr", None) or getattr(f, "id", None)) == "prompt_interpretations":
                    callers.append(str(p.relative_to(ROOT)))
    assert callers == [], f"something calls the off seam: {callers}"


def test_no_public_or_coach_module_can_reach_the_kind():
    from test_research_findings_6208 import NO_READ_PACKAGES, _closure, _import_graph

    graph = _import_graph()
    roots = [m for m in graph if m.startswith(NO_READ_PACKAGES)]
    assert len(roots) > 50, "the roots were not found — vacuous guard"
    reached = _closure(graph, roots)
    kind_modules = {"research.hypotheses", "mcp.tools_personal_hypotheses"}
    assert not reached & kind_modules, f"a public or coach module can import the hypotheses: {sorted(reached & kind_modules)}"
    graph["coach.fake_prompt"] = {"research.hypotheses"}
    assert _closure(graph, ["coach.fake_prompt"]) & kind_modules, "the boundary sweep can fail"


def test_no_site_route_names_the_kind():
    hits = []
    for p in (ROOT / "lambdas" / "web").rglob("*.py"):
        src = p.read_text(encoding="utf-8", errors="replace")
        if any(s in src for s in ("PERSONAL_HYPOTHESIS#", "personal_hypothes", "research.hypotheses", "from research import")):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == [], hits


def test_the_kind_reads_no_inferred_psychological_label():
    from common.inferred_fields import INFERRED_PSYCH_LABEL_FIELDS, INFERRED_PSYCH_LABEL_KEYS

    for rel in ("lambdas/research/hypotheses.py", "mcp/tools_personal_hypotheses.py"):
        names = {n.value for n in ast.walk(ast.parse((ROOT / rel).read_text(encoding="utf-8"))) if isinstance(n, ast.Constant)}
        names |= {n.attr for n in ast.walk(ast.parse((ROOT / rel).read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}
        assert not names & (INFERRED_PSYCH_LABEL_FIELDS | INFERRED_PSYCH_LABEL_KEYS), rel


# ── the scripted demonstration ──────────────────────────────────────────────────────────────────


def test_the_demo_script_runs_the_full_path():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_personal_hypothesis.py")],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    for fragment in (
        "1. direct manage_personal_hypothesis(propose) — refused",
        "hypothesis rows after the direct call: 0",
        "hypothesis rows while queued: 0",
        "3. approved — one head row",
        "5. discarded True; hypothesis rows before 3, after 3",
        '"rejected": true',
        "7b. re-proposal at enqueue — refused",
        "only he can reopen it",
        "Reopened by Matthew, in his own words",
        "RESULT: PASS",
    ):
        assert fragment in out, fragment

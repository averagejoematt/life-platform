"""tests/test_research_findings_6208.py — the research findings store (#6208, epic #6206).

  * a finding with an unverified, unidentified or non-allow-listed source is refused, and nothing is stored;
  * the six rules: strong evidence needs a full text; a live dedupe key blocks a second finding and names it;
    the risk tier, what it touches and clinical review agree, and a tier-5 finding never reaches
    approved_for_experiment; the states and their reasons; the event kinds (a personal result is copied from an
    experiment analysis and never moves evidence_strength); an overdue review reads `stale`;
  * history is append-only — the head is written once, every write is a conditional put, nothing is updated;
  * simulated findings are out of every default list; retrospective and simulated rows carry their origin;
  * owner-only and cross-phase in the privacy and phase registries; one writer; no public module can reach it;
    no schedule and no ingestion path names it;
  * the laptop verifier, offline, with stubbed resolvers.
All content here is synthetic: no personal value appears in any fixture.
"""

# premerge-gate: sweeps the tracked tree (git ls-files) for writers and readers of the research findings store, and reads config/evidence_source_allowlist.json

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
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
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from research import findings as rf  # noqa: E402

import mcp.tools_research_findings as trf  # noqa: E402

PK = rf.pk("matthew")
TODAY = "2026-11-22"
EXP_PK = "USER#matthew#SOURCE#experiments"
REC_ID = "rec_20261120_sleep_coach_0a1b2c3d"
DECIDE = {"words_are": "owner_verbatim", "provenance": "owner ruling document, 2026-11-22"}


def _src(**kw):
    """A source as the verifier prints it: stamped over whatever id, title and day the case sets (pass
    verification=... to plant a hand-made block instead)."""
    s = {
        "id_kind": "pmid",
        "id": "12345678",
        "design": "meta_analysis",
        "review_depth": "abstract_only",
        "resolved_title": "A synthetic meta-analysis title used only in tests",
        "verified_on": "2026-11-20",
        "claim_supported_by": "abstract_read",
        "supports_note": "Synthetic note: the pooled estimate favours the intervention.",
    }
    s.update(kw)
    if "verification" not in kw:
        day = s["verified_on"] if isinstance(s.get("verified_on"), str) else "2026-11-20"
        fetched_at = f"{day}T12:00:00Z"
        s["verification"] = {
            "resolver": "pubmed",
            "resolved_title": s.get("resolved_title"),
            "first_author": "Doe J",
            "year": 2021,
            "fetched_at": fetched_at,
            "subject_overlap": {"shared_terms": ["synthetic", "wake"], "count": 2, "basis": "title", "low": False},
            "stamp": rf.verification_stamp(str(s.get("id_kind")), str(s.get("id")), str(s.get("resolved_title")), fetched_at),
        }
    return s


FULL = _src(
    id_kind="doi", id="10.1000/synthetic.2026.001", design="randomized_trial", review_depth="full_text", claim_supported_by="full_text_read"
)


# ── a small DynamoDB double: conditional puts and get/query only — it has NO update or delete, so any rewrite fails ──


class ConditionalCheckFailedException(Exception):
    pass


def _key_parts(cond) -> dict:
    out: dict = {}
    stack = [cond]
    while stack:
        expr = stack.pop().get_expression()
        if expr["operator"] == "AND":
            stack.extend(expr["values"])
        elif expr["operator"] == "=":
            out["pk"] = expr["values"][1]
        elif expr["operator"] == "begins_with":
            out["prefix"] = expr["values"][1]
    return out


class Table:
    def __init__(self, rows=()):
        self.store = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.puts: list = []

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        assert ConditionExpression == "attribute_not_exists(sk)", "every write to the store is a conditional create"
        key = (Item["pk"], Item["sk"])
        if key in self.store:
            raise ConditionalCheckFailedException("exists")
        self.store[key] = json.loads(json.dumps(Item))
        self.puts.append(dict(Item))
        return {}

    def query(self, **kw):
        parts = _key_parts(kw["KeyConditionExpression"])
        rows = [r for (p, s), r in self.store.items() if p == parts.get("pk") and s.startswith(parts.get("prefix", ""))]
        rows.sort(key=lambda r: r["sk"])
        return {"Items": [json.loads(json.dumps(r)) for r in rows]}


@pytest.fixture
def table(monkeypatch):
    t = Table(
        [
            {"pk": EXP_PK, "sk": "EXP#morning-walk_2026-10-01", "name": "synthetic", "analysis": {"verdict": "inconclusive"}},
            {"pk": EXP_PK, "sk": "EXP#no-analysis_2026-11-01", "name": "synthetic"},
            {"pk": "USER#matthew#SOURCE#coach_recommendations", "sk": f"REC#{REC_ID}", "rec_id": REC_ID},
        ]
    )
    monkeypatch.setattr(trf, "_table_ref", t)
    monkeypatch.setattr(trf, "_user_id_ref", "matthew")
    monkeypatch.setattr(trf, "pacific_today", lambda: TODAY)
    return t


def _args(**kw):
    a = {
        "action": "record",
        "question": "Does a fixed wake time improve sleep consistency in adults?",
        "dedupe_key": "fixed-wake-time-sleep-consistency",
        "sources": [_src()],
        "evidence_summary": "Synthetic summary: trials suggest a modest effect with wide uncertainty.",
        "evidence_strength": "moderate",
        "applicability": {"text": "Adult, non-shift-work samples.", "population_match": "partial"},
        "limitations": "Short trials; self-reported outcomes.",
        "risk_tier": 2,
        "touches": ["sleep"],
        "clinical_review_required": False,
        "risk_rationale": "Synthetic: a reversible change to a routine, nothing ingested or prescribed.",
        "responsible_coach": "sleep_coach",
        "review_by": "2027-02-20",
        "origin": "prospective",
        "surfaced_by": "owner",
        "date": "2026-11-21",
    }
    a.update(kw)
    return a


def _call(**kw):
    return trf.tool_manage_research_finding(_args(**kw))


def _record(table, **kw):
    res = _call(**kw)
    assert res.get("status") == "recorded", res
    return res["finding_id"]


def _do(action, fid, **kw):
    return trf.tool_manage_research_finding({"action": action, "finding_id": fid, **kw})


def _refused(res, needle):
    text = json.dumps(res)
    assert "recorded" != res.get("status") and needle in text, res


# ── the record and its sources ──────────────────────────────────────────────────────────────


def test_record_writes_one_head_with_a_valid_id_and_reads_newly_discovered(table):
    fid = _record(table)
    assert rf.valid_finding_id(fid) and fid.startswith("rf_20261121_")
    head = table.store[(PK, rf.head_sk(fid))]
    assert head["recorded_by"] == "owner" and head["origin"] == "prospective" and head["record_type"] == "research_finding"
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert view["state"] == rf.NEWLY_DISCOVERED and view["stale"] is False and view["sources"][0]["id"] == "12345678"


@pytest.mark.parametrize(
    "src, needle",
    [
        (_src(resolved_title=""), "unverified"),
        (_src(verified_on=None), "unverified"),
        (_src(verified_on="2026-12-01"), "future"),
        (_src(id="abc"), "malformed"),
        (_src(id_kind="doi", id="not-a-doi"), "malformed"),
        (_src(id_kind="url", id="https://example.org"), "id_kind"),
        (_src(id_kind="guideline_url", id="https://example.org/guide", design="clinical_guideline"), "not an allow-listed"),
        (_src(id_kind="guideline_url", id="http://www.nice.org.uk/guidance/x", design="clinical_guideline"), "https"),
        (_src(id_kind="guideline_url", id="https://www.youtube.com/watch?v=x", design="clinical_guideline"), "social media"),
        (_src(resolved_title="see https://medium.com/post"), "denied host"),
        (_src(pubtypes=["Journal Article", "Retracted Publication"]), "rejected publication type"),
        (_src(design="blog_post"), "design"),
        (_src(review_depth="skimmed"), "review_depth"),
        (_src(extra="x"), "unknown source fields"),
    ],
)
def test_an_unverifiable_or_off_list_source_is_refused_and_nothing_is_stored(table, src, needle):
    _refused(_call(sources=[src]), needle)
    assert not [p for p in table.puts if p["pk"] == PK]


def test_a_doi_or_an_allow_listed_guideline_needs_no_pmid(table):
    guideline = _src(id_kind="guideline_url", id="https://www.nice.org.uk/guidance/ng000", design="clinical_guideline")
    fid = _record(table, sources=[FULL, guideline])
    assert [s["id_kind"] for s in table.store[(PK, rf.head_sk(fid))]["sources"]] == ["doi", "guideline_url"]


def test_source_count_and_head_field_bounds(table):
    _refused(_call(sources=[]), "1-12")
    _refused(_call(sources=[_src(id=str(10000000 + i)) for i in range(13)]), "1-12")
    _refused(_call(sources=[_src(), _src()]), "listed twice")
    _refused(_call(question="too short"), "question")
    _refused(_call(limitations=""), "limitations")
    _refused(_call(responsible_coach="training_coach"), "responsible_coach")  # retired: cannot own new work
    _refused(_call(review_by="2026-11-21"), "review_by")
    _refused(_call(review_by="2027-11-22"), "review_by")
    _refused(_call(dedupe_key="Fixed Wake Time"), "dedupe_key")
    _refused(_call(origin="imagined"), "origin")
    _refused(_call(applicability={"text": "x", "population_match": "close"}), "population_match")
    assert not table.puts


# ── rule 1: an abstract cannot back strong evidence ───────────────────────────────────────────


def test_strong_evidence_needs_a_full_text_source(table):
    _refused(_call(evidence_strength="strong"), "full_text")
    fid = _record(table, evidence_strength="strong", sources=[_src(), FULL])
    assert table.store[(PK, rf.head_sk(fid))]["evidence_strength"] == "strong"


def test_a_correction_to_strong_is_held_to_the_same_rule(table):
    fid = _record(table)
    _refused(_do("correct", fid, field="evidence_strength", value="strong", reason="re-read"), "full_text")
    assert _do("add_source", fid, source=FULL)["status"] == "recorded"
    res = _do("correct", fid, field="evidence_strength", value="strong", reason="the full trial was read")
    assert res["finding"]["evidence_strength"] == "strong" and res["finding"]["corrections"][0]["previous"] == "moderate"


# ── rule 2: a live dedupe key blocks a second finding, and the refusal names it ──────────────────


def test_a_live_dedupe_key_is_refused_naming_the_finding_and_its_coach(table):
    fid = _record(table)
    res = _call(date="2026-11-22", question="Is a fixed wake time worth it for sleep regularity?")
    _refused(res, fid)
    assert "sleep_coach" in json.dumps(res)


def test_a_closed_finding_frees_its_dedupe_key(table):
    fid = _record(table)
    assert _do("set_state", fid, state="rejected", reason="the trials measured another population")["status"] == "recorded"
    assert _call(date="2026-11-22")["status"] == "recorded"


def test_a_simulated_finding_never_blocks_the_real_record(table):
    _record(table, origin="simulated")
    assert _call(date="2026-11-22")["status"] == "recorded"


def test_the_same_key_on_the_same_day_is_one_finding(table):
    fid = _record(table, origin="simulated")
    _do("set_state", fid, state="rejected", reason="rehearsal over")
    res = _call(origin="simulated")
    assert res["status"] == "duplicate" and res["finding_id"] == fid


# ── rule 3: the risk tier, what it touches, clinical review; tier 5 belongs to the clinician ─────────


@pytest.mark.parametrize(
    "kw, needle",
    [
        ({"risk_tier": 2, "touches": ["training"]}, "below what it touches"),
        ({"risk_tier": 3, "touches": ["supplements"], "clinical_review_required": True}, "below what it touches"),
        ({"risk_tier": 3, "touches": ["intake_target"], "clinical_review_required": False}, "clinical_review_required must be true"),
        ({"risk_tier": 4, "touches": ["electrolytes"], "clinical_review_required": False}, "clinical_review_required must be true"),
        ({"risk_tier": 5, "touches": ["medication"], "clinical_review_required": False}, "clinical_review_required must be true"),
        ({"risk_tier": 6}, "risk_tier must be"),
        ({"risk_tier": True}, "risk_tier must be"),
        ({"touches": []}, "touches"),
        ({"question": "Does a magnesium supplement before bed improve sleep onset?"}, "declare"),
    ],
)
def test_risk_tier_touches_and_clinical_review_must_agree(table, kw, needle):
    _refused(_call(**kw), needle)


def test_a_tier_3_training_change_needs_no_clinical_review_but_an_intake_target_does(table):
    assert _call(risk_tier=3, touches=["training"], dedupe_key="training-a")["status"] == "recorded"
    assert _call(risk_tier=3, touches=["intake_target"], clinical_review_required=True, dedupe_key="intake-a")["status"] == "recorded"


def test_a_tier_5_finding_never_reaches_an_experiment(table):
    fid = _record(table, risk_tier=5, touches=["medication"], clinical_review_required=True)
    assert _do("set_state", fid, state="discussed")["status"] == "recorded"
    _refused(_do("set_state", fid, state="approved_for_experiment"), "treating clinician")
    _refused(_do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01"), "treating clinician")
    view = {**trf.tool_manage_research_finding({"action": "list"})["findings"][0], "state": rf.APPROVED_FOR_EXPERIMENT}
    with pytest.raises(rf.FindingError, match="treating clinician"):  # even a view already past approval
        rf.build_finding_event(
            user_id="u",
            view={**view, "experiments": ["x_2026-01-01"]},
            kind="state_change",
            recorded_at=NOW(),
            today=TODAY,
            state="experiment_in_progress",
        )
    with pytest.raises(rf.FindingError, match="treating clinician"):  # a tier read back as a string is still tier 5
        rf.build_finding_event(
            user_id="u",
            view={**view, "state": "discussed", "risk_tier": "5"},
            kind="state_change",
            recorded_at=NOW(),
            today=TODAY,
            state="approved_for_experiment",
        )


def test_a_correction_can_only_tighten_risk(table):
    fid = _record(table, risk_tier=4, touches=["supplements"], clinical_review_required=True)
    _refused(_do("correct", fid, field="clinical_review_required", value=False, reason="x"), "lower-risk reading needs a new finding")
    _refused(_do("correct", fid, field="risk_tier", value=2, reason="x"), "lower-risk reading needs a new finding")
    _refused(_do("correct", fid, field="touches", value=["observation"], reason="x"), "lower-risk reading needs a new finding")
    assert (
        _do("correct", fid, field="touches", value=["supplements", "medication"], reason="it is prescribed").get("status") != "recorded"
    )  # tier 4 < 5
    assert _do("correct", fid, field="risk_tier", value=5, reason="prescribed")["status"] == "recorded"
    assert _do("correct", fid, field="touches", value=["supplements", "medication"], reason="it is prescribed")["status"] == "recorded"
    low = _record(table, dedupe_key="low-one")
    assert _do("correct", low, field="clinical_review_required", value=True, reason="ask first")["status"] == "recorded"


def test_the_probe_s_tier_5_to_tier_1_walk_is_refused_at_every_step(table):
    fid = _record(
        table,
        risk_tier=5,
        touches=["medication"],
        clinical_review_required=True,
        question="Would a beta blocker change resting heart rate trends?",
    )
    _refused(_do("correct", fid, field="touches", value=["observation"], reason="x"), "lower-risk reading needs a new finding")
    _refused(_do("correct", fid, field="risk_tier", value=1, reason="x"), "lower-risk reading needs a new finding")
    _refused(_do("correct", fid, field="clinical_review_required", value=False, reason="x"), "lower-risk reading needs a new finding")
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert (view["risk_tier"], view["touches"], view["clinical_review_required"]) == (5, ["medication"], True)


# ── rule 4: states, reasons, superseded ─────────────────────────────────────────────────────


@pytest.mark.parametrize("state", sorted(rf.REASON_REQUIRED_STATES))
def test_rejected_declined_and_superseded_need_a_reason(table, state):
    fid = _record(table)
    _refused(_do("set_state", fid, state=state, superseded_by="pmid:87654321"), "needs a reason")


def test_superseded_needs_superseded_by_and_keeps_the_original_sources(table):
    fid = _record(table)
    _refused(_do("set_state", fid, state="superseded", reason="newer review"), "superseded_by")
    _refused(
        _do("set_state", fid, state="superseded", reason="newer review", superseded_by="rf_20990101_deadbeef"), "not a recorded finding"
    )
    res = _do("set_state", fid, state="superseded", reason="a newer review", superseded_by="doi:10.1000/newer.2026")
    view = res["finding"]
    assert view["state"] == "superseded" and view["superseded_by"] == "doi:10.1000/newer.2026"
    assert view["sources"] == [rf.validate_source(_src(), today=TODAY)] and not view["live"]


def test_the_lifecycle_table_is_complete_and_closed_states_are_terminal():
    assert set(rf.TRANSITIONS) == set(rf.STATES)
    assert all(set(nxt) <= set(rf.STATES) for nxt in rf.TRANSITIONS.values())
    assert all(rf.TRANSITIONS[s] == () for s in rf.CLOSED_STATES)
    assert {s for s, nxt in rf.TRANSITIONS.items() if set(nxt) & rf.EVALUATED_STATES} == {
        rf.EXPERIMENT_IN_PROGRESS,
        rf.OBSERVATION_RECORDED,
    }
    assert {s for s, nxt in rf.TRANSITIONS.items() if rf.EXPERIMENT_IN_PROGRESS in nxt} == {rf.APPROVED_FOR_EXPERIMENT}
    assert {s for s, nxt in rf.TRANSITIONS.items() if rf.OBSERVATION_RECORDED in nxt} == {rf.OBSERVATION_PLANNED}
    reach, todo = {rf.NEWLY_DISCOVERED}, [rf.NEWLY_DISCOVERED]
    while todo:
        for nxt in rf.TRANSITIONS[todo.pop()]:
            if nxt not in reach:
                reach.add(nxt)
                todo.append(nxt)
    assert reach == set(rf.STATES)


@pytest.mark.parametrize(
    "frm, to, needle",
    [
        ("rejected", "approved_for_experiment", "terminal"),
        ("evaluated_supported", "newly_discovered", "terminal"),
        ("newly_discovered", "evaluated_supported", "next states are"),
        ("newly_discovered", "approved_for_experiment", "next states are"),
        ("under_review", "experiment_in_progress", "next states are"),
        ("approved_for_experiment", "experiment_in_progress", "needs a linked experiment"),
        ("experiment_in_progress", "evaluated_supported", "real personal result"),
        ("observation_recorded", "evaluated_inconclusive", "authorizes='verdict'"),
    ],
)
def test_the_probe_s_transition_bypasses_are_refused(frm, to, needle):
    view = {**rf.fold([rf.build_finding_head(**{**_head_kwargs(), "touches": ["observation"], "risk_tier": 1})])[0], "state": frm}
    with pytest.raises(rf.FindingError, match=re.escape(needle)):
        rf.build_finding_event(user_id="u", view=view, kind="state_change", recorded_at=NOW(), today=TODAY, state=to, reason="r")


def test_a_repeat_state_is_refused(table):
    fid = _record(table)
    _do("set_state", fid, state="under_review")
    _refused(_do("set_state", fid, state="under_review"), "already")


# ── rule 5: the event kinds ─────────────────────────────────────────────────────────────────


def test_link_recommendation_validates_the_record_id_and_its_existence(table):
    fid = _record(table)
    _refused(_do("link", fid, link_kind="recommendation", rec_id="rec_bad"), "recommendation-record id")
    _refused(_do("link", fid, link_kind="recommendation", rec_id="rec_20261120_sleep_coach_ffffffff"), "no recommendation")
    assert _do("link", fid, link_kind="recommendation", rec_id=REC_ID)["finding"]["recommendations"] == [REC_ID]
    _refused(_do("link", fid, link_kind="recommendation", rec_id=REC_ID), "already linked")


def test_link_experiment_and_a_personal_result_copied_from_its_analysis(table):
    fid = _record(table)
    eid = "morning-walk_2026-10-01"
    _refused(_do("link", fid, link_kind="personal_result", experiment_id=eid), "not linked")
    _refused(_do("link", fid, link_kind="experiment", experiment_id="nope_2026-01-01"), "no experiment")
    assert _do("link", fid, link_kind="experiment", experiment_id=eid)["status"] == "recorded"
    _refused(_do("link", fid, link_kind="personal_result", experiment_id=eid, verdict="supported"), "copied, never restated")
    res = _do("link", fid, link_kind="personal_result", experiment_id=eid)
    assert res["finding"]["personal_results"][0]["verdict"] == "inconclusive"
    assert res["finding"]["personal_results"][0]["simulated"] is False
    assert _do("link", fid, link_kind="personal_result", experiment_id=eid)["status"] == "duplicate"


def test_a_personal_result_needs_an_analysis_to_copy(table):
    fid = _record(table)
    _do("link", fid, link_kind="experiment", experiment_id="no-analysis_2026-11-01")
    _refused(_do("link", fid, link_kind="personal_result", experiment_id="no-analysis_2026-11-01"), "no analysis verdict")


def test_a_personal_result_never_changes_evidence_strength(table):
    fid = _record(table)
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    _refused(
        _do("link", fid, link_kind="personal_result", experiment_id="morning-walk_2026-10-01", evidence_strength="strong"),
        "never changes evidence_strength",
    )
    res = _do("link", fid, link_kind="personal_result", simulated=True, verdict="supported")
    assert res["finding"]["evidence_strength"] == "moderate"


def test_the_pure_builder_refuses_a_personal_result_that_restates_strength():
    view = {"finding_id": "rf_20261121_0a1b2c3d", "experiments": [], "state": rf.NEWLY_DISCOVERED}
    with pytest.raises(rf.FindingError, match="never changes evidence_strength"):
        rf.build_finding_event(
            user_id="u", view=view, kind=rf.EVENT_PERSONAL_RESULT, recorded_at="t", today=TODAY,
            verdict="supported", simulated=True, evidence_strength="weak",
        )  # fmt: skip


def test_a_decision_is_his_words_with_whose_words_and_provenance(table):
    fid = _record(table)
    _refused(_do("decide", fid, words="   ", **DECIDE), "verbatim")
    _refused(_do("decide", fid, words="Not now."), "words_are")
    _refused(_do("decide", fid, words="Not now.", words_are="owner_verbatim"), "provenance")
    _refused(_do("decide", fid, words="Not now.", words_are="the model", provenance="session"), "words_are")
    words = "Not now.\n  I'll  revisit after the holidays."
    res = _do("decide", fid, words=words, **DECIDE)
    d = res["finding"]["decisions"][0]
    assert d["words"] == words and d["words_are"] == "owner_verbatim" and d["provenance"] == DECIDE["provenance"]
    assert _do("decide", fid, words=words, **DECIDE)["status"] == "duplicate"
    summary = _do("decide", fid, words="He wants to wait until January.", words_are="session_summary", provenance="chat, 2026-11-22")
    assert summary["finding"]["decisions"][-1]["words_are"] == "session_summary"


def test_a_correction_needs_a_reason_and_a_correctable_field(table):
    fid = _record(table)
    _refused(_do("correct", fid, field="limitations", value="New limits."), "needs a reason")
    _refused(_do("correct", fid, field="dedupe_key", value="other", reason="x"), "restates one of")
    _refused(_do("correct", fid, field="origin", value="retrospective", reason="x"), "restates one of")
    _refused(_do("correct", fid, field="limitations", value="Short trials; self-reported outcomes.", reason="x"), "already says")


# ── history is append-only ─────────────────────────────────────────────────────────────────


def test_history_rows_are_never_rewritten(table):
    fid = _record(table)
    head_before = dict(table.store[(PK, rf.head_sk(fid))])
    _do("add_source", fid, source=FULL)
    _do("correct", fid, field="limitations", value="Short trials only.", reason="tightened")
    _do("set_state", fid, state="under_review")
    _do("decide", fid, words="Read it properly first.", **DECIDE)
    rows = [r for (p, s), r in table.store.items() if p == PK]
    assert table.store[(PK, rf.head_sk(fid))] == head_before, "the head was rewritten"
    assert len({p["sk"] for p in table.puts}) == len(table.puts) == len(rows), "a key was written twice"
    events = [r for r in rows if r["record_type"] == "research_finding_event"]
    assert {e["kind"] for e in events} == {"source_added", "correction", "state_change", "decision"}
    assert all(e["sk"].startswith(f"FINDING#{fid}#EV#") for e in events)
    view = rf.fold(rows)[0]
    assert view["limitations"] == "Short trials only." and len(view["sources"]) == 2 and len(view["history"]) == 4


def test_the_tool_never_updates_or_deletes():
    src = (ROOT / "mcp" / "tools_research_findings.py").read_text(encoding="utf-8")
    calls = {n.func.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"update_item", "delete_item", "batch_write_item", "transact_write_items"}


def test_only_owner_events_count():
    head = rf.build_finding_head(**_head_kwargs())
    stray = {
        **rf.build_finding_event(
            user_id="matthew", view=rf.fold([head])[0], kind="decision", recorded_at=NOW(), today=TODAY, words="x", **DECIDE
        )
    }
    stray["recorded_by"] = "machine"
    assert rf.fold([head, stray])[0]["decisions"] == []


def _head_kwargs():
    a = _args()
    return {
        "user_id": "matthew",
        "day": a.pop("date"),
        "today": TODAY,
        "recorded_at": "2026-11-21T00:00:00.000Z",
        **{k: v for k, v in a.items() if k != "action"},
    }


# ── simulated, retrospective, stale ──────────────────────────────────────────────────────────


def test_simulated_findings_are_out_of_every_default_list(table):
    real = _record(table)
    sim = _record(table, origin="simulated", dedupe_key="rehearsal-only")
    for status in trf.LIST_STATUSES:
        ids = {v["finding_id"] for v in trf.tool_manage_research_finding({"action": "list", "status": status})["findings"]}
        assert sim not in ids, status
    ids = {v["finding_id"] for v in trf.tool_manage_research_finding({"action": "list", "include_simulated": True})["findings"]}
    assert ids == {real, sim}


def test_simulated_personal_results_are_out_of_the_default_list(table):
    fid = _record(table)
    _do("link", fid, link_kind="personal_result", simulated=True, verdict="supported")
    assert trf.tool_manage_research_finding({"action": "list"})["findings"][0]["personal_results"] == []
    got = trf.tool_manage_research_finding({"action": "list", "include_simulated": True})["findings"][0]["personal_results"]
    assert got[0]["simulated"] is True


def test_retrospective_rows_carry_their_origin(table):
    fid = _record(table, origin="retrospective", date="2026-06-01", review_by="2026-09-01")
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert view["finding_id"] == fid and view["origin"] == "retrospective"


def test_a_past_review_by_reads_stale_and_a_closed_finding_never_does(table):
    fid = _record(table, origin="retrospective", date="2026-06-01", review_by="2026-09-01")
    listing = trf.tool_manage_research_finding({"action": "list", "status": "stale"})
    assert listing["stale_count"] == 1 and listing["findings"][0]["finding_id"] == fid and listing["findings"][0]["stale"]
    _do("set_state", fid, state="declined", reason="not for now")
    assert trf.tool_manage_research_finding({"action": "list", "status": "stale"})["count"] == 0
    assert trf.tool_manage_research_finding({"action": "list", "status": "closed"})["findings"][0]["stale"] is False


def test_a_future_date_is_refused(table):
    _refused(_call(date="2026-11-23", review_by="2027-01-01"), "future")


# ── the registries ─────────────────────────────────────────────────────────────────────────


def test_the_tool_schema_enums_equal_the_registries():
    props = trf.MANAGE_FINDING_INPUT["properties"]
    assert tuple(props["action"]["enum"]) == trf.ACTIONS
    assert tuple(props["link_kind"]["enum"]) == trf.LINK_KINDS
    assert tuple(props["status"]["enum"]) == trf.LIST_STATUSES
    assert tuple(props["state"]["enum"]) == rf.STATES
    assert tuple(props["evidence_strength"]["enum"]) == rf.EVIDENCE_STRENGTHS
    assert tuple(props["origin"]["enum"]) == rf.ORIGINS
    assert tuple(props["touches"]["items"]["enum"]) == rf.TOUCHES
    assert tuple(props["verdict"]["enum"]) == rf.PERSONAL_VERDICTS
    assert tuple(props["field"]["enum"]) == rf.CORRECTABLE_FIELDS
    assert set(rf.RISK_TIERS) == {1, 2, 3, 4, 5} and set(rf.TOUCH_MIN_TIER.values()) <= set(rf.RISK_TIERS)
    assert rf.CLOSED_STATES < set(rf.STATES) and rf.REASON_REQUIRED_STATES < set(rf.STATES)


def test_the_bundle_copies_equal_the_allowlist_file():
    allow = json.loads((ROOT / "config" / "evidence_source_allowlist.json").read_text(encoding="utf-8"))
    assert set(rf.DESIGNS) == set(allow["designs"]) | {"clinical_guideline"}
    assert tuple(rf.GUIDELINE_HOSTS) == tuple(allow["guideline_hosts"]["hosts"])
    assert tuple(rf.DENIED_HOSTS) == tuple(allow["denied_hosts"])
    assert tuple(rf.REJECTED_PUBTYPES) == tuple(allow["rejected_pubtypes"])


def test_the_allowlist_extension_is_additive():
    """The exercise library's own rules are untouched: still DOI/PMID only, and no guideline host is a library host."""
    allow = json.loads((ROOT / "config" / "evidence_source_allowlist.json").read_text(encoding="utf-8"))
    assert allow["version"] == "2.1.0"
    assert allow["identifier_kinds"] == ["doi", "pmid"] and allow["evidence_backing_requires"]["identifier"] == "pmid"
    assert not set(allow["guideline_hosts"]["hosts"]) & set(allow["allowed_hosts"])
    assert not set(allow["guideline_hosts"]["hosts"]) & set(allow["denied_hosts"])


def test_the_personal_verdicts_are_the_experiment_analysis_vocabulary():
    src = (ROOT / "lambdas" / "experiment" / "experiment_design.py").read_text(encoding="utf-8")
    for verdict in rf.PERSONAL_VERDICTS:
        assert f'"{verdict}"' in src, verdict


def test_the_tool_is_registered_as_a_write_with_replay_semantics():
    from mcp_registry_ast import registered_tool_names

    from mcp import audit, idempotency

    assert "manage_research_finding" in registered_tool_names((ROOT / "mcp" / "registry.py").read_text(encoding="utf-8"))
    assert audit.is_write_tool("manage_research_finding")
    assert "manage_research_finding" in idempotency.REPLAY_SEMANTICS


def test_the_source_is_owner_only_cross_phase_and_never_publishable():
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert field_tiers.SOURCE_TIERS[rf.SOURCE] == field_tiers.TIER_OWNER_ONLY
    assert not field_tiers.is_publishable(field_tiers.source_tier_of(rf.SOURCE))
    assert phase_taxonomy.SOURCE_CLASS[rf.SOURCE] == phase_taxonomy.CROSS_PHASE


# ── one writer, the publication boundary, no schedule (tree sweeps) ─────────────────────────────


def _tracked(*patterns: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", *patterns], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out if not p.startswith("tests/") and (ROOT / p).exists()]


WRITER_MODULE = "mcp/tools_research_findings.py"
REGISTRY_MODULE = "lambdas/research/findings.py"  # builds rows only inside fold's _replay, to re-validate; never writes
#: Every runtime module allowed to NAME the store. A new reader is a decision made here, on its PR.
ALLOWED_TO_NAME = frozenset(
    {
        "lambdas/research/__init__.py",  # the package (its docstring names the import)
        "lambdas/research/finding_risk.py",  # the risk vocabulary + rules, split out of the registry (no I/O, builds no row)
        "lambdas/research/finding_sources.py",  # the source vocabulary + admission check, split out (no I/O, builds no row)
        "lambdas/research/findings.py",  # the registry
        WRITER_MODULE,  # the one writer and reader
        "mcp/registry.py",  # registers the tool
        "mcp/idempotency.py",  # its replay semantics
        "lambdas/privacy/field_tiers.py",  # TIER_OWNER_ONLY
        "lambdas/experiment/phase_taxonomy.py",  # CROSS_PHASE
        "deploy/config_ownership_audit.py",  # the allowlist's ownership ruling names the verifier
        "lambdas/research/hypotheses.py",  # #6292: the personal-hypothesis kind in the same partition (its own sk family)
        "mcp/tools_personal_hypotheses.py",  # #6292: that kind's owner tool (reads direct, writes queue-only); builds no finding row
    }
)
RUNTIME_TREES = ("lambdas/", "mcp/", "deploy/", "cdk/")


def _names_the_store(src: str) -> bool:
    return any(s in src for s in ("research_findings", "research.findings", "from research import", "research_finding"))


def test_only_the_owner_tool_constructs_a_row_and_only_registered_modules_name_the_store():
    constructing, naming = set(), set()
    for rel in _tracked("*.py"):
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if _names_the_store(src) and rel.startswith(RUNTIME_TREES):
            naming.add(rel)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            f = call.func
            if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)) in ("build_finding_head", "build_finding_event"):
                constructing.add(rel)
    assert constructing == {WRITER_MODULE, REGISTRY_MODULE}, f"finding constructors outside the owner tool: {sorted(constructing)}"
    tree = ast.parse((ROOT / REGISTRY_MODULE).read_text(encoding="utf-8"))
    in_registry = {
        f.name
        for f in tree.body
        if isinstance(f, ast.FunctionDef)
        for n in ast.walk(f)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("build_finding_head", "build_finding_event")
    }
    assert in_registry == {"_replay"}, f"the registry builds rows outside fold's replay (which writes nothing): {in_registry}"
    assert (
        naming <= ALLOWED_TO_NAME
    ), f"modules naming the research findings store outside the allowlist: {sorted(naming - ALLOWED_TO_NAME)}"
    assert naming == ALLOWED_TO_NAME, f"an allowed module stopped naming the store (vacuous guard?): {sorted(ALLOWED_TO_NAME - naming)}"


def test_the_writer_sweep_can_fail():
    tree = ast.parse("def f():\n    rf.build_finding_event(user_id='u', view={}, kind='decision', recorded_at='t', today='d')\n")
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "build_finding_event"]
    assert _names_the_store("from research import findings")


def _import_graph() -> dict[str, set[str]]:
    mods: dict[str, Path] = {}
    for p in (ROOT / "lambdas").rglob("*.py"):
        mods[".".join(p.relative_to(ROOT / "lambdas").with_suffix("").parts).removesuffix(".__init__")] = p
    for p in (ROOT / "mcp").rglob("*.py"):
        mods[".".join(p.relative_to(ROOT).with_suffix("").parts)] = p
    graph: dict[str, set[str]] = {}
    for name, p in mods.items():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        deps: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                deps |= {a.name for a in n.names if a.name in mods}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                deps |= {n.module} & set(mods) | {f"{n.module}.{a.name}" for a in n.names if f"{n.module}.{a.name}" in mods}
        graph[name] = deps
    return graph


def _closure(graph: dict[str, set[str]], roots: list[str]) -> set[str]:
    seen, stack = set(roots), list(roots)
    while stack:
        for d in graph.get(stack.pop(), ()):
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


#: The public publishing pipeline and every coach-facing package: the site API, the content generators, the email
#: lambdas, and the coach package (no coach prompt reads the store). None may reach it, module-level or lazily.
NO_READ_PACKAGES = ("web.", "content.", "emails.", "coach.", "ai.", "intelligence.", "compute.")
STORE_MODULES = frozenset(
    {
        "research.findings",
        "research.finding_risk",
        "research.finding_sources",
        "mcp.tools_research_findings",
        "research.hypotheses",  # #6292: the personal-hypothesis kind in the same partition
        "mcp.tools_personal_hypotheses",
    }
)


def test_no_public_or_coach_module_can_reach_the_store():
    graph = _import_graph()
    roots = [m for m in graph if m.startswith(NO_READ_PACKAGES)]
    assert len(roots) > 50, "the roots were not found — vacuous guard"
    reached = _closure(graph, roots)
    assert not reached & STORE_MODULES, f"a public or coach module can import the store: {sorted(reached & STORE_MODULES)}"


def test_the_boundary_sweep_can_fail():
    graph = _import_graph()
    graph["web.site_api_fake"] = {"research.findings"}
    assert _closure(graph, ["web.site_api_fake"]) & STORE_MODULES


def test_no_schedule_and_no_ingestion_path_names_the_store():
    from ingestion import source_registry

    assert rf.SOURCE not in getattr(source_registry, "SOURCES", {})
    hits = []
    for rel in _tracked("cdk/*", ".github/workflows/*", "lambdas/ingestion/*"):
        if "research_finding" in (ROOT / rel).read_text(encoding="utf-8", errors="replace"):
            hits.append(rel)
    assert not hits, f"a schedule, workflow or ingestion module names the research findings store: {hits}"


# ── the verification stamp and the reader's support assertion (audit addition) ──────────────────────


def test_a_title_edited_after_verification_is_refused(table):
    edited = _src()
    edited["resolved_title"] = "A different paper the recorder typed by hand"
    _refused(_call(sources=[edited]), "edited after verification")
    both = _src()
    both["resolved_title"] = both["verification"]["resolved_title"] = "A different paper the recorder typed by hand"
    _refused(_call(sources=[both]), "stamp does not match")
    moved = _src()
    moved["id"] = "87654321"  # a real-looking PMID swapped in after the fetch
    _refused(_call(sources=[moved]), "stamp does not match")
    assert not table.puts


@pytest.mark.parametrize(
    "kw, needle",
    [
        ({"verification": None}, "no verification block"),
        ({"verification": {"resolver": "pubmed"}}, "fetched_at"),
        ({"claim_supported_by": None}, "claim_supported_by"),
        ({"claim_supported_by": "skimmed"}, "claim_supported_by"),
        ({"claim_supported_by": "full_text_read"}, "needs review_depth full_text"),
        ({"supports_note": "too short"}, "supports_note"),
        ({"supports_note": "x" * 401}, "supports_note"),
    ],
)
def test_support_is_asserted_by_a_reader_and_the_block_is_required(table, kw, needle):
    _refused(_call(sources=[_src(**kw)]), needle)


def test_the_stamp_is_the_documented_hash():
    import hashlib

    want = hashlib.sha256("pmid|1|T|2026-11-20T12:00:00Z".encode()).hexdigest()[:16]
    assert rf.verification_stamp("pmid", "1", "T", "2026-11-20T12:00:00Z") == want


# ── origin on every row, and the publishable() helper (audit addition) ──────────────────────────


def test_origin_is_on_every_list_row(table):
    _record(table)
    _record(table, origin="retrospective", dedupe_key="older-one", date="2026-06-01", review_by="2026-09-01")
    _record(table, origin="simulated", dedupe_key="rehearsal-one")
    for status in trf.LIST_STATUSES:
        for inc in (False, True):
            rows = trf.tool_manage_research_finding({"action": "list", "status": status, "include_simulated": inc})["findings"]
            assert all(r.get("origin") in rf.ORIGINS for r in rows), (status, inc)


def test_publishable_by_origin():
    assert rf.publishable({"origin": "prospective"}) == (True, [])
    for view, needle in (
        ({}, "missing"),
        ({"origin": "invented"}, "missing"),
        ({"origin": "simulated", "publication_eligible": True}, "rehearsal"),
        ({"origin": "retrospective"}, "explicit publication_eligible"),
        ({"origin": "retrospective", "publication_eligible": False}, "explicit publication_eligible"),
    ):
        ok, reasons = rf.publishable(view)
        assert not ok and any(needle in r for r in reasons), view
    assert rf.publishable({"origin": "retrospective", "publication_eligible": True}) == (True, [])


def test_a_retrospective_finding_becomes_publishable_only_by_his_decision(table):
    fid = _record(table, origin="retrospective", date="2026-06-01", review_by="2027-01-01")
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert rf.publishable(view)[0] is False
    _refused(_do("decide", fid, words="Fine to share.", publication_eligible="yes", **DECIDE), "true or false")
    res = _do("decide", fid, words="Fine to share one day.", publication_eligible=True, **DECIDE)
    assert res["finding"]["publication_eligible"] is True and rf.publishable(res["finding"]) == (True, [])
    res = _do("decide", fid, words="Changed my mind.", publication_eligible=False, **DECIDE)
    assert rf.publishable(res["finding"])[0] is False


def test_nothing_calls_publishable_yet():
    callers = []
    for rel in _tracked("*.py"):
        if rel == "lambdas/research/findings.py":
            continue
        if "publishable(" in (ROOT / rel).read_text(encoding="utf-8", errors="replace") and "rf.publishable" in (ROOT / rel).read_text(
            encoding="utf-8", errors="replace"
        ):
            callers.append(rel)
    assert not callers, f"a publish path now calls research.findings.publishable — review it on its own PR: {callers}"


# ── the laptop verifier, offline ───────────────────────────────────────────────────────────

CLAIM = "Does evening light exposure delay sleep onset in adults?"
LIGHT_TITLE = "A synthetic randomized trial of evening light exposure and sleep onset"
ABSTRACT_XML = "<PubmedArticle><Abstract><AbstractText>Evening light exposure delayed melatonin and sleep onset.</AbstractText></Abstract></PubmedArticle>"


def _verifier():
    import research_finding_verify as rfv

    return rfv


def _pubmed(pmid, title, author, year, pubtypes=("Journal Article",)):
    return {
        "result": {
            "uids": [pmid],
            pmid: {"title": title, "authors": [{"name": author}], "pubdate": f"{year} Jan", "pubtype": list(pubtypes)},
        }
    }


def _stub(responses):
    calls = []

    def http(url):
        calls.append(url)
        for needle, resp in responses.items():
            if needle in url:
                return resp
        return 404, None

    http.calls = calls  # type: ignore[attr-defined]
    return http


def _pmid_args(claim=CLAIM, title=LIGHT_TITLE, *extra):
    return [
        "--pmid", "23456789", "--title", title, "--authors", "Doe J", "--year", "2021", "--design", "randomized_trial",
        "--review-depth", "abstract_only", "--claim", claim, "--supported-by", "abstract_read",
        "--supports-note", "Synthetic: the trial reports later sleep onset after evening light.", *extra,
    ]  # fmt: skip


NOW = lambda: "2026-11-22T09:30:00Z"  # noqa: E731


def test_verifier_fetches_and_emits_a_stamped_source_the_tool_accepts():
    rfv = _verifier()
    http = _stub({"esummary": (200, _pubmed("23456789", LIGHT_TITLE, "Doe J", 2021))})
    text = lambda url: (200, ABSTRACT_XML)  # noqa: E731
    code, out = rfv.run(_pmid_args(), http=http, text=text, now=NOW)
    assert code == 0, out
    src = json.loads(out)
    v = src["verification"]
    assert src == rf.validate_source(src, today=TODAY) and src["resolved_title"] == LIGHT_TITLE and src["verified_on"] == TODAY
    assert v["resolver"] == "pubmed" and v["first_author"] == "Doe J" and v["year"] == 2021 and v["fetched_at"] == NOW()
    assert v["stamp"] == rf.verification_stamp("pmid", "23456789", LIGHT_TITLE, NOW())
    import hashlib

    assert v["abstract_sha256"] == hashlib.sha256(b"Evening light exposure delayed melatonin and sleep onset.").hexdigest()
    ov = v["subject_overlap"]
    assert {"evening", "light", "exposure", "sleep", "onset"} <= set(ov["shared_terms"]) and ov["count"] >= 2
    assert ov["basis"] == "title+abstract" and ov["low"] is False
    assert {urllib.parse.urlparse(u).hostname for u in http.calls} == {"eutils.ncbi.nlm.nih.gov"}
    src["resolved_title"] = src["verification"]["resolved_title"] = "Edited by hand"
    with pytest.raises(rf.FindingError, match="stamp does not match"):
        rf.validate_source(src, today=TODAY)


def test_low_subject_overlap_is_advisory_it_warns_and_still_emits():
    rfv = _verifier()
    unrelated = "A synthetic trial of rotator cuff repair techniques"
    http = _stub({"esummary": (200, _pubmed("23456789", unrelated, "Doe J", 2021))})
    warnings: list = []
    code, out = rfv.run(_pmid_args(CLAIM, unrelated), http=http, text=lambda url: (200, ""), now=NOW, warn=warnings.append)
    assert code == 0, out
    src = json.loads(out)
    assert src["verification"]["subject_overlap"] == {"shared_terms": [], "count": 0, "basis": "title", "low": True}
    assert len(warnings) == 1 and "WARNING (advisory)" in warnings[0] and "not a check of support" in warnings[0]
    assert rf.validate_source(src, today=TODAY)["verification"]["subject_overlap"]["low"] is True  # the store never refuses on it
    assert "override_reason" not in src["verification"]
    with pytest.raises(SystemExit):  # there is no --override flag to give
        rfv.run([*_pmid_args(CLAIM, unrelated), "--override", "x"], http=http, text=lambda url: (200, ""), now=NOW)


def test_a_related_paper_raises_no_warning():
    rfv = _verifier()
    warnings: list = []
    http = _stub({"esummary": (200, _pubmed("23456789", LIGHT_TITLE, "Doe J", 2021))})
    code, _ = rfv.run(_pmid_args(), http=http, text=lambda url: (200, ""), now=NOW, warn=warnings.append)
    assert code == 0 and warnings == []


def test_overlap_counts_shared_content_words_not_stop_words():
    rfv = _verifier()
    assert rfv.subject_overlap("Does the effect of a trial in adults improve?", "The effect of a trial in adults", "") == []
    assert rfv.subject_overlap("Evening light delays sleep", "Evening lights and sleep", "") == ["evening", "light", "sleep"]


def test_verifier_resolves_a_doi_through_crossref():
    rfv = _verifier()
    title = "A synthetic meta-analysis of evening light exposure"
    body = {
        "message": {
            "title": [title],
            "author": [{"family": "Roe", "given": "A", "sequence": "first"}],
            "issued": {"date-parts": [[2022]]},
            "type": "journal-article",
            "abstract": "<jats:p>Evening light and sleep onset.</jats:p>",
        }
    }
    args = ["--doi", "10.1000/SYNTH.22", "--title", title, "--authors", "Roe A", "--year", "2022", "--design", "meta_analysis",
            "--review-depth", "full_text", "--claim", CLAIM, "--supported-by", "full_text_read",
            "--supports-note", "Synthetic: the pooled effect on sleep onset is reported."]  # fmt: skip
    code, out = rfv.run(args, http=_stub({"crossref": (200, body)}), text=lambda u: (404, ""), now=NOW)
    assert code == 0, out
    src = json.loads(out)
    assert src["id"] == "10.1000/synth.22" and src["verification"]["resolver"] == "crossref" and src["verification"]["year"] == 2022
    assert "abstract_sha256" in src["verification"]


@pytest.mark.parametrize(
    "body, needle",
    [
        (_pubmed("23456789", "Something else entirely", "Doe J", 2021), "does not match"),
        (_pubmed("23456789", LIGHT_TITLE, "Doe J", 2021, ("Retracted Publication",)), "rejected"),
        ({"result": {"uids": []}}, "not_found"),
    ],
)
def test_verifier_refuses_a_mismatch_a_retraction_or_a_missing_record(body, needle):
    rfv = _verifier()
    code, out = rfv.run(_pmid_args(), http=_stub({"esummary": (200, body)}), text=lambda u: (200, ""), now=NOW)
    assert code == 1 and needle in out, out


def test_verifier_checks_a_guideline_page_title_and_refuses_an_off_list_host():
    rfv = _verifier()
    page = '<html><head><title>Evening light and sleep onset guideline | NICE</title><meta name="description" content="Evening light advice."></head></html>'
    text = lambda url: (200, page)  # noqa: E731
    ok_args = ["--guideline-url", "https://www.nice.org.uk/guidance/ng000", "--title", "Evening light and sleep onset guideline",
               "--design", "clinical_guideline", "--review-depth", "full_text", "--claim", CLAIM, "--supported-by", "full_text_read",
               "--supports-note", "Synthetic: the guideline's evening light section."]  # fmt: skip
    code, out = rfv.run(ok_args, text=text, now=NOW)
    assert code == 0, out
    v = json.loads(out)["verification"]
    assert v["resolver"] == "guideline_page" and v["first_author"] == "www.nice.org.uk" and "abstract_sha256" in v
    code, out = rfv.run([*ok_args[:1], "https://example.org/guide", *ok_args[2:]], text=text, now=NOW)
    assert code == 1 and "not an allow-listed guideline host" in out
    code, out = rfv.run([*ok_args[:3], "A different guideline", *ok_args[4:]], text=text, now=NOW)
    assert code == 1 and "does not carry" in out


def test_verifier_imports_the_existing_resolvers_rather_than_copying_them():
    src = (ROOT / "scripts" / "research_finding_verify.py").read_text(encoding="utf-8")
    assert "import library_evidence_review as ler" in src and "ler.verify_citation(" in src
    for fn in ("def verify_pmid", "def verify_doi", "def verify_citation", "def titles_match"):
        assert fn not in src
    assert "does NOT prove the Lambda verified anything" in src and "not a check that the paper SUPPORTS" in src
    assert "known high false-alarm rate on titles alone" in src


# ── follow-up review: observations, clean paths, risk rationale, the wider tripwire, fold replay, redirects, clock ──


def test_clean_observation_path_record_review_discuss_plan_record_and_his_verdict(table):
    fid = _record(table, risk_tier=1, touches=["observation"])
    for state in ("under_review", "discussed"):
        assert _do("set_state", fid, state=state)["status"] == "recorded", state
    _refused(_do("set_state", fid, state="observation_planned"), "authorizes='observation'")
    _do("decide", fid, words="Yes, watch it for two weeks.", authorizes="observation", **DECIDE)
    assert _do("set_state", fid, state="observation_planned")["finding"]["state"] == "observation_planned"
    _refused(_do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01"), "takes no experiment link")
    _refused(_do("set_state", fid, state="observation_recorded", observed_on="2026-11-22", observation_note="short"), "observation_note")
    _refused(_do("set_state", fid, state="observation_recorded", observed_on="2026-11-30", observation_note="x" * 30), "observed_on")
    res = _do(
        "set_state",
        fid,
        state="observation_recorded",
        observed_on="2026-11-22",
        observation_note="Synthetic: seven nights logged, no change seen.",
    )
    assert res["finding"]["observations"][0]["observed_on"] == "2026-11-22" and res["finding"]["state"] == "observation_recorded"
    _refused(_do("set_state", fid, state="evaluated_inconclusive"), "authorizes='verdict'")
    _refused(_do("decide", fid, words="Call it.", authorizes="verdict", **DECIDE), "verdict one of")
    _do("decide", fid, words="Call it inconclusive.", authorizes="verdict", verdict="inconclusive", **DECIDE)
    _refused(_do("set_state", fid, state="evaluated_supported"), "the evaluation is evaluated_inconclusive")
    assert _do("set_state", fid, state="evaluated_inconclusive")["finding"]["state"] == "evaluated_inconclusive"


def test_an_old_authorization_does_not_carry_into_a_later_state(table):
    fid = _record(table, risk_tier=1, touches=["observation"])
    _do(
        "decide", fid, words="Watch it.", authorizes="verdict", verdict="supported", **DECIDE
    )  # a verdict decided before anything was observed
    _do("decide", fid, words="Watch it.", authorizes="observation", **DECIDE)
    _do("set_state", fid, state="observation_planned")
    _do("set_state", fid, state="observation_recorded", observed_on="2026-11-22", observation_note="Synthetic: seven nights logged.")
    _refused(_do("set_state", fid, state="evaluated_supported"), "authorizes='verdict'")


@pytest.mark.parametrize(
    "kw",
    [
        {"risk_tier": 3, "touches": ["training"]},
        {"risk_tier": 2, "touches": ["observation", "behaviour"]},
        {"risk_tier": 3, "touches": ["observation"]},
    ],
)
def test_an_observation_is_only_for_an_observation_only_low_tier_finding(table, kw):
    fid = _record(table, **kw)
    _do("decide", fid, words="Watch it.", authorizes="observation", **DECIDE)
    _refused(_do("set_state", fid, state="observation_planned"), "exactly ['observation']")


def test_an_observation_finding_with_an_experiment_link_cannot_be_planned(table):
    fid = _record(table, risk_tier=1, touches=["observation"])
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    _do("decide", fid, words="Watch it.", authorizes="observation", **DECIDE)
    _refused(_do("set_state", fid, state="observation_planned"), "no experiment link")


def test_clean_experiment_path_and_its_evaluation_needs_a_real_result(table):
    fid = _record(table, risk_tier=3, touches=["training"])
    _do("set_state", fid, state="under_review")
    assert _do("set_state", fid, state="approved_for_experiment")["status"] == "recorded"
    _refused(_do("set_state", fid, state="experiment_in_progress"), "needs a linked experiment")
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    assert _do("set_state", fid, state="experiment_in_progress")["status"] == "recorded"
    _do("link", fid, link_kind="personal_result", simulated=True, verdict="supported")
    _refused(_do("set_state", fid, state="evaluated_supported"), "real personal result")
    _do("link", fid, link_kind="personal_result", experiment_id="morning-walk_2026-10-01")
    assert _do("set_state", fid, state="evaluated_inconclusive")["finding"]["state"] == "evaluated_inconclusive"
    _refused(_do("set_state", fid, state="under_review"), "terminal")


def test_a_simulated_finding_may_be_evaluated_on_a_simulated_result(table):
    fid = _record(table, risk_tier=3, touches=["training"], origin="simulated")
    for st in ("under_review", "approved_for_experiment"):
        _do("set_state", fid, state=st)
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    _do("set_state", fid, state="experiment_in_progress")
    _do("link", fid, link_kind="personal_result", simulated=True, verdict="supported")
    assert _do("set_state", fid, state="evaluated_supported")["status"] == "recorded"


def test_risk_rationale_is_required_and_shown(table):
    _refused(_call(risk_rationale=None), "risk_rationale")
    _refused(_call(risk_rationale="too short"), "risk_rationale")
    fid = _record(table)
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert view["finding_id"] == fid and view["risk_rationale"].startswith("Synthetic")


@pytest.mark.parametrize(
    "question, touch",
    [
        ("Would a beta blocker change my resting heart rate trends?", "medication"),
        ("Does metoprolol blunt heart rate variability readings?", "medication"),
        ("Does a statin change exercise recovery markers over time?", "medication"),
        ("Is the dose of the drug affecting resting heart rate?", "medication"),
        ("Do NSAIDs like ibuprofen blunt strength gains over time?", "medication"),
        ("Do anticoagulants change bruising after heavy training?", "medication"),
        ("Should the kcal target drop by 200 on rest days?", "intake_target"),
        ("Does a larger calorie deficit slow weight loss over time?", "intake_target"),
        ("Does a protein target of 1.6 g/kg preserve lean mass?", "intake_target"),
        ("Does intermittent fasting improve fasting glucose?", "intake_target"),
        ("Does caffeine after noon reduce deep sleep duration?", "intake_target"),
        ("Does alcohol at dinner reduce overnight HRV readings?", "intake_target"),
        ("Does vitamin D3 in winter improve mood scores?", "supplements"),
        ("Does fish oil (omega-3) lower triglycerides over time?", "supplements"),
        ("Does melatonin at night improve sleep onset time?", "supplements"),
        ("Does ashwagandha reduce evening cortisol levels?", "supplements"),
        ("Does salt loading before training raise HRV readings?", "electrolytes"),
    ],
)
def test_the_wider_tripwire_refuses_an_undeclared_touch(table, question, touch):
    _refused(_call(question=question), f"declare '{touch}'")


def test_dose_response_is_not_a_medication_word(table):
    assert (
        _call(question="What is the dose-response of weekly sets on hypertrophy?", risk_tier=3, touches=["training"])["status"]
        == "recorded"
    )


def test_the_tripwire_is_documented_as_a_tripwire_with_gaps():
    assert "known gaps" in (rf.__doc__ or "").lower() and "not a classifier" in (rf.__doc__ or "")
    assert "known gaps and is not a classifier" in trf.MANAGE_FINDING_DESCRIPTION


def test_the_tool_says_identity_not_support():
    desc = trf.MANAGE_FINDING_DESCRIPTION
    assert "identity-verified sources (the identifier resolves to this record; this does not show the source supports the finding)" in desc
    assert "VERIFIED sources" not in desc


def _stored_rows(table):
    return [r for (p, _s), r in table.store.items() if p == PK]


def test_fold_replays_events_and_skips_a_forged_row(table):
    fid = _record(table)
    forged = {
        "pk": PK,
        "sk": rf.event_sk(fid, "2026-11-22T11:00:00.000Z", "correction"),
        "record_type": "research_finding_event",
        "finding_id": fid,
        "kind": "correction",
        "recorded_by": "owner",
        "recorded_at": "2026-11-22T11:00:00.000Z",
        "field": "risk_tier",
        "value": 1,
        "reason": "forged",
    }
    jump = {
        **forged,
        "sk": rf.event_sk(fid, "2026-11-22T11:00:01.000Z", "state_change"),
        "kind": "state_change",
        "to_state": "evaluated_supported",
        "recorded_at": "2026-11-22T11:00:01.000Z",
    }
    junk = {
        **forged,
        "sk": rf.event_sk(fid, "2026-11-22T11:00:02.000Z", "nonsense"),
        "kind": "nonsense",
        "recorded_at": "2026-11-22T11:00:02.000Z",
    }
    view = rf.fold(_stored_rows(table) + [forged, jump, junk])[0]
    assert view["risk_tier"] == 2 and view["state"] == "newly_discovered"
    assert view["invalid_events"] == {"count": 3, "sks": sorted([forged["sk"], jump["sk"], junk["sk"]])}
    assert view["history"] == []


def test_fold_reads_dynamodb_decimals(table):
    from decimal import Decimal

    fid = _record(table, risk_tier=3, touches=["training"])
    _do("correct", fid, field="clinical_review_required", value=True, reason="tightened")
    assert _do("correct", fid, field="risk_tier", value=4, reason="tightened")["status"] == "recorded"
    rows = [{k: (Decimal(v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in r.items()} for r in _stored_rows(table)]
    view = rf.fold(rows)[0]
    assert view["risk_tier"] == 4 and view["invalid_events"]["count"] == 0


def test_an_evening_pacific_verification_is_not_a_future_date(table, monkeypatch):
    """17:00 PT on 2026-11-22 is 01:00Z on 2026-11-23: the verifier writes verified_on 2026-11-23 (UTC)."""
    monkeypatch.setattr(rf, "utc_today", lambda: "2026-11-23")
    evening = _src(verified_on="2026-11-23")
    assert evening["verification"]["fetched_at"].startswith("2026-11-23")
    fid = _record(table, sources=[evening])
    assert _do("add_source", fid, source=_src(id="23456789", verified_on="2026-11-23"))["status"] == "recorded"
    assert rf.fold(_stored_rows(table))[0]["invalid_events"]["count"] == 0
    monkeypatch.setattr(rf, "utc_today", lambda: "2026-11-22")
    _refused(_call(sources=[_src(verified_on="2026-11-24")], dedupe_key="later-one"), "future")


def test_the_verifier_refuses_a_redirect_off_the_allow_list():
    rfv = _verifier()
    handler = rfv.RefuseOffListRedirect()
    req = urllib.request.Request("https://www.nice.org.uk/guidance/ng000")
    with pytest.raises(urllib.error.HTTPError, match="not allow-listed"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/fake-guideline")
    with pytest.raises(urllib.error.HTTPError, match="not allow-listed"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://www.nice.org.uk/guidance/ng000")
    ok = handler.redirect_request(req, None, 301, "Moved", {}, "https://www.nice.org.uk/guidance/ng000/chapter/1")
    assert ok is not None and urllib.parse.urlparse(ok.full_url).hostname == "www.nice.org.uk"
    assert rfv.allowed_host("api.crossref.org") and not rfv.allowed_host("evil-nice.org.uk")


def test_the_verifier_drops_a_response_whose_final_host_is_off_list(monkeypatch):
    rfv = _verifier()

    class _Resp:
        status = 200

        def geturl(self):
            return "https://evil.example.com/landing"

        def read(self, *a):
            return b"<title>Evening light and sleep onset guideline</title>"

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def open(self, req, timeout=None):
            return _Resp()

    monkeypatch.setattr(rfv.urllib.request, "build_opener", lambda *handlers: _Opener())
    assert rfv.text_get("https://www.nice.org.uk/guidance/ng000") == (0, "")
    assert rfv.json_get("https://api.crossref.org/works/10.1000/x") == (0, None)


def test_two_acts_in_one_millisecond_replay_in_the_order_they_were_made(table, monkeypatch):
    monkeypatch.setattr(rf, "now_instant", lambda: "2026-11-22T10:00:00.000Z")  # a frozen clock: every act in one millisecond
    fid = _record(table)
    assert _do("add_source", fid, source=FULL)["status"] == "recorded"
    res = _do("correct", fid, field="evidence_strength", value="strong", reason="the full trial was read")
    assert res["finding"]["evidence_strength"] == "strong" and res["finding"]["invalid_events"]["count"] == 0
    assert rf.next_instant(["2026-11-22T10:00:00.999Z"], now="2026-11-22T10:00:00.000Z") == "2026-11-22T10:00:01.000Z"


# ── finish line (re-probe of 9a3d19906): (a) observation leak, (b) clinician hold, (c) evaluation = verdict,
# (d) lenient instants, (e) duplicate touches ─────────────────────────────────────────────────────────────


def _planned_observation(table):
    fid = _record(table, risk_tier=1, touches=["observation"], dedupe_key="obs-leak")
    _do("decide", fid, words="Watch it.", authorizes="observation", **DECIDE)
    assert _do("set_state", fid, state="observation_planned")["status"] == "recorded"
    return fid


def test_a_an_observation_cannot_take_on_intervention_risk(table):
    fid = _planned_observation(table)
    leak = "cannot take on intervention risk; close it and record a new finding"
    assert _do("correct", fid, field="clinical_review_required", value=True, reason="ask first")["status"] == "recorded"
    _refused(_do("correct", fid, field="risk_tier", value=5, reason="x"), leak)
    _refused(_do("correct", fid, field="risk_tier", value=3, reason="x"), leak)
    _refused(_do("correct", fid, field="touches", value=["observation", "medication", "supplements"], reason="x"), leak)
    _refused(
        _do("correct", fid, field="question", value="Does metoprolol at night lower resting heart rate?", reason="x"),
        "declare 'medication'",
    )
    view = trf.tool_manage_research_finding({"action": "list"})["findings"][0]
    assert (view["state"], view["touches"], view["risk_tier"], view["clinician_hold"]) == ("observation_planned", ["observation"], 1, False)


def test_a_a_forged_leak_row_is_skipped_at_fold(table):
    fid = _planned_observation(table)
    forged = {
        "pk": PK,
        "sk": rf.event_sk(fid, "2099-01-01T00:00:00.000Z", "correction"),
        "record_type": "research_finding_event",
        "finding_id": fid,
        "kind": "correction",
        "recorded_by": "owner",
        "recorded_at": "2099-01-01T00:00:00.000Z",
        "field": "risk_tier",
        "value": 2,
        "reason": "forged",
    }
    forged_touch = {**forged, "sk": forged["sk"] + "x", "field": "touches", "value": ["behaviour", "observation"]}
    view = rf.fold(_stored_rows(table) + [forged, forged_touch])[0]
    assert view["touches"] == ["observation"] and view["invalid_events"]["count"] == 1  # tier 2 keeps the invariant; a 2nd touch does not
    assert view["risk_tier"] == 2


def test_a_the_tripwire_runs_on_every_question_correction_in_every_state(table):
    fid = _record(table)
    _do("set_state", fid, state="under_review")
    _refused(
        _do("correct", fid, field="question", value="Does melatonin at night improve sleep consistency?", reason="x"),
        "declare 'supplements'",
    )
    _refused(
        _do("correct", fid, field="evidence_summary", value="Synthetic: trials of caffeine timing show an effect.", reason="x"),
        "declare 'intake_target'",
    )


def _tier5_in_experiment(table):
    fid = _record(table, risk_tier=3, touches=["training"], dedupe_key="raise-five")
    for st in ("under_review", "approved_for_experiment"):
        _do("set_state", fid, state=st)
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    _do("set_state", fid, state="experiment_in_progress")
    for field, value in (("clinical_review_required", True), ("risk_tier", 5), ("touches", ["medication", "training"])):
        assert _do("correct", fid, field=field, value=value, reason="it is prescribed").get("status") == "recorded", field
    return fid


def test_b_a_tier_5_finding_is_held_in_every_state_and_never_evaluated_here(table):
    fid = _tier5_in_experiment(table)
    _do("link", fid, link_kind="personal_result", experiment_id="morning-walk_2026-10-01")
    for state in ("evaluated_supported", "evaluated_inconclusive", "evaluated_not_supported"):
        _refused(_do("set_state", fid, state=state), "only exits are declined, rejected or superseded")
    assert trf.tool_manage_research_finding({"action": "list"})["findings"][0]["clinician_hold"] is True
    res = _do("set_state", fid, state="declined", reason="the clinician decides this one")
    assert res["finding"]["state"] == "declined" and res["finding"]["clinician_hold"] is True  # closed, still held
    held = _record(table, risk_tier=5, touches=["medication"], clinical_review_required=True, dedupe_key="born-five")
    assert (
        next(v for v in trf.tool_manage_research_finding({"action": "list"})["findings"] if v["finding_id"] == held)["clinician_hold"]
        is True
    )


def test_b_a_tier_5_experiment_may_be_rejected(table):
    fid = _tier5_in_experiment(table)
    assert _do("set_state", fid, state="rejected", reason="not for this tool")["finding"]["clinician_hold"] is True


def _in_progress(table, key):
    fid = _record(table, risk_tier=3, touches=["training"], dedupe_key=key)
    for st in ("under_review", "approved_for_experiment"):
        _do("set_state", fid, state=st)
    _do("link", fid, link_kind="experiment", experiment_id="morning-walk_2026-10-01")
    return fid


def test_c_an_evaluation_equals_the_copied_result(table):
    fid = _in_progress(table, "verdict-match")
    _do("set_state", fid, state="experiment_in_progress")
    _do("link", fid, link_kind="personal_result", experiment_id="morning-walk_2026-10-01")  # the analysis says inconclusive
    _refused(_do("set_state", fid, state="evaluated_supported"), "the evaluation is evaluated_inconclusive")
    _refused(_do("set_state", fid, state="evaluated_not_supported"), "the evaluation is evaluated_inconclusive")
    assert _do("set_state", fid, state="evaluated_inconclusive")["status"] == "recorded"


def test_c_a_result_recorded_before_the_experiment_started_does_not_count(table):
    fid = _in_progress(table, "pre-start")
    assert _do("link", fid, link_kind="personal_result", experiment_id="morning-walk_2026-10-01")["status"] == "recorded"
    _do("set_state", fid, state="experiment_in_progress")
    _refused(_do("set_state", fid, state="evaluated_inconclusive"), "recorded after the experiment started")


def test_c_an_observation_evaluation_equals_his_verdict(table):
    fid = _planned_observation(table)
    _do("set_state", fid, state="observation_recorded", observed_on="2026-11-22", observation_note="Synthetic: seven nights logged.")
    _do("decide", fid, words="It held up.", authorizes="verdict", verdict="supported", **DECIDE)
    _refused(_do("set_state", fid, state="evaluated_inconclusive"), "the evaluation is evaluated_supported")
    assert _do("set_state", fid, state="evaluated_supported")["status"] == "recorded"


def test_c_the_verdict_map_covers_the_personal_verdicts():
    assert set(rf.VERDICT_STATE) == set(rf.PERSONAL_VERDICTS) and set(rf.VERDICT_STATE.values()) == rf.EVALUATED_STATES


def test_d_instants_parse_with_or_without_fractional_seconds():
    assert rf.next_instant(["2026-11-22T12:00:05Z"], now="2026-11-22T12:00:00.000Z") == "2026-11-22T12:00:05.001Z"
    assert rf.next_instant(["garbage", None, "2026-11-22T12:00:05Z"], now="2026-11-22T13:00:00Z") == "2026-11-22T13:00:00.000Z"
    assert rf.parse_instant("2026-11-22T12:00:05Z") < rf.parse_instant("2026-11-22T12:00:05.500Z")
    assert rf.parse_instant("not an instant") is None


def test_d_a_stored_row_without_milliseconds_blocks_nothing_and_a_garbled_one_is_reported(table, monkeypatch):
    fid = _record(table)
    no_ms = rf.build_finding_event(
        user_id="matthew",
        view=rf.fold(_stored_rows(table))[0],
        kind="state_change",
        recorded_at="2026-11-22T12:00:05Z",
        today=TODAY,
        state="under_review",
    )
    table.store[(PK, no_ms["sk"])] = no_ms
    garbled = {
        **no_ms,
        "sk": rf.event_sk(fid, "garbled", "decision"),
        "kind": "decision",
        "recorded_at": "yesterday-ish",
        "words": "x",
        **DECIDE,
    }
    table.store[(PK, garbled["sk"])] = garbled
    monkeypatch.setattr(rf, "now_instant", lambda: "2026-11-22T12:00:05.000Z")  # same second as the stored row
    res = _do("set_state", fid, state="discussed")
    assert res["status"] == "recorded" and res["finding"]["state"] == "discussed"
    assert res["finding"]["invalid_events"] == {"count": 1, "sks": [garbled["sk"]]}


def test_d_replay_orders_by_time_not_by_sort_key_text(table):
    _record(table)
    first = rf.build_finding_event(
        user_id="matthew",
        view=rf.fold(_stored_rows(table))[0],
        kind="state_change",
        recorded_at="2026-11-22T12:00:05Z",
        today=TODAY,
        state="under_review",
    )
    view = rf.fold(_stored_rows(table) + [first])[0]
    second = rf.build_finding_event(
        user_id="matthew", view=view, kind="state_change", recorded_at="2026-11-22T12:00:05.500Z", today=TODAY, state="discussed"
    )
    assert first["sk"] > second["sk"]  # the text order is the wrong order
    view = rf.fold(_stored_rows(table) + [second, first])[0]
    assert view["state"] == "discussed" and view["invalid_events"]["count"] == 0


def test_e_touches_are_unique_and_sorted(table):
    _refused(_call(touches=["sleep", "sleep"]), "twice")
    fid = _record(table, risk_tier=3, touches=["training", "sleep"])
    assert table.store[(PK, rf.head_sk(fid))]["touches"] == ["sleep", "training"]
    _refused(_do("correct", fid, field="touches", value=["training", "sleep", "sleep"], reason="x"), "twice")
    _refused(_do("correct", fid, field="touches", value=["training", "sleep"], reason="x"), "already says")


def test_e_the_split_modules_are_pure_and_re_exported():
    from research import finding_risk, finding_sources

    for mod in (finding_risk, finding_sources):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "boto3" not in src and "urllib.request" not in src and "build_finding" not in src
    assert rf.FindingError is finding_risk.FindingError and rf.validate_source is finding_sources.validate_source

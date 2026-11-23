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
import subprocess
import sys
import urllib.parse
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
            "overlap_terms": ["synthetic", "wake"],
            "overlap_count": 2,
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


def test_a_tier_5_finding_can_never_be_approved_for_experiment(table):
    fid = _record(table, risk_tier=5, touches=["medication"], clinical_review_required=True)
    res = _do("set_state", fid, state="approved_for_experiment")
    _refused(res, "treating clinician")
    assert _do("set_state", fid, state="discussed")["status"] == "recorded"
    _refused(_do("set_state", fid, state="approved_for_experiment"), "treating clinician")


def test_a_correction_cannot_slip_a_tier_under_its_rule(table):
    fid = _record(table, risk_tier=4, touches=["supplements"], clinical_review_required=True)
    _refused(_do("correct", fid, field="clinical_review_required", value=False, reason="x"), "clinical_review_required must be true")
    _refused(_do("correct", fid, field="risk_tier", value=2, reason="x"), "below what it touches")


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


def test_every_state_is_reachable_and_a_repeat_is_refused(table):
    fid = _record(table)
    for state in rf.STATES:
        if state in (rf.NEWLY_DISCOVERED, rf.SUPERSEDED):
            continue
        assert _do("set_state", fid, state=state, reason="synthetic")["status"] == "recorded", state
    _refused(_do("set_state", fid, state=rf.STATES[-1], reason="again"), "already")


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


def test_a_decision_is_his_words_verbatim(table):
    fid = _record(table)
    _refused(_do("decide", fid, words="   "), "verbatim")
    words = "Not now.\n  I'll  revisit after the holidays."
    res = _do("decide", fid, words=words)
    assert res["finding"]["decisions"][0]["words"] == words
    assert _do("decide", fid, words=words)["status"] == "duplicate"


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
    _do("decide", fid, words="Read it properly first.")
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
    head = rf.build_finding_head(**{**_head_kwargs(), "recorded_at": "2026-11-21T00:00:00.000Z"})
    stray = {
        **rf.build_finding_event(user_id="matthew", view=rf.fold([head])[0], kind="decision", recorded_at="t1", today=TODAY, words="x")
    }
    stray["recorded_by"] = "machine"
    assert rf.fold([head, stray])[0]["decisions"] == []


def _head_kwargs():
    a = _args()
    return {
        "user_id": "matthew",
        "day": a.pop("date"),
        "today": TODAY,
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
#: Every runtime module allowed to NAME the store. A new reader is a decision made here, on its PR.
ALLOWED_TO_NAME = frozenset(
    {
        "lambdas/research/__init__.py",  # the package (its docstring names the import)
        "lambdas/research/findings.py",  # the registry
        WRITER_MODULE,  # the one writer and reader
        "mcp/registry.py",  # registers the tool
        "mcp/idempotency.py",  # its replay semantics
        "lambdas/privacy/field_tiers.py",  # TIER_OWNER_ONLY
        "lambdas/experiment/phase_taxonomy.py",  # CROSS_PHASE
        "deploy/config_ownership_audit.py",  # the allowlist's ownership ruling names the verifier
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
    assert constructing == {WRITER_MODULE}, f"finding constructors outside the owner tool: {sorted(constructing)}"
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
STORE_MODULES = frozenset({"research.findings", "mcp.tools_research_findings"})


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
    _refused(_do("decide", fid, words="Fine to share.", publication_eligible="yes"), "true or false")
    res = _do("decide", fid, words="Fine to share one day.", publication_eligible=True)
    assert res["finding"]["publication_eligible"] is True and rf.publishable(res["finding"]) == (True, [])
    res = _do("decide", fid, words="Changed my mind.", publication_eligible=False)
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
    assert {"evening", "light", "exposure", "sleep", "onset"} <= set(v["overlap_terms"]) and v["overlap_count"] >= 2
    assert "override_reason" not in v
    assert {urllib.parse.urlparse(u).hostname for u in http.calls} == {"eutils.ncbi.nlm.nih.gov"}
    src["resolved_title"] = src["verification"]["resolved_title"] = "Edited by hand"
    with pytest.raises(rf.FindingError, match="stamp does not match"):
        rf.validate_source(src, today=TODAY)


def test_the_overlap_tripwire_refuses_an_unrelated_paper_unless_overridden():
    rfv = _verifier()
    unrelated = "A synthetic trial of rotator cuff repair techniques"
    http = _stub({"esummary": (200, _pubmed("23456789", unrelated, "Doe J", 2021))})
    text = lambda url: (200, "")  # noqa: E731
    code, out = rfv.run(_pmid_args(CLAIM, unrelated), http=http, text=text, now=NOW)
    assert code == 1 and "NOT EMITTED" in out and "0 shared content word" in out and "not a check of support" in out
    code, out = rfv.run(
        [*_pmid_args(CLAIM, unrelated), "--override", "the trial's control arm is the relevant part"], http=http, text=text, now=NOW
    )
    assert code == 0, out
    v = json.loads(out)["verification"]
    assert v["override_reason"] == "the trial's control arm is the relevant part" and v["overlap_count"] == 0 and "abstract_sha256" not in v


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

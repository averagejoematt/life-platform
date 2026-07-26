"""tests/test_coach_dossier.py — The Coach Dossier (#1387).

The privacy-filter test class here is the one that BLOCKS LAUNCH (AC2): seeded
violations of every standing content absolute — substance names, chronological-age
leakage, genotype strings, real-person third parties — must be caught, and the
ADR-141 §4 conversation-channel exclusion must hold structurally.

All offline/hermetic: coach_dossier is a pure module; the site-layer tests run
web.site_api_coach against FakeDdbTable with a pk/sk-prefix-dispatching query hook.
"""

import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import coach_corrections  # noqa: E402
import coach_dossier as cd  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# AC2 — the privacy pass (ships first, blocks launch)
# ══════════════════════════════════════════════════════════════════════════════

# One seeded violation per standing content absolute. Each MUST be caught.
SEEDED_VIOLATIONS = [
    # substances (privacy_guard.VICE_KEYWORDS reused via journal_quotes)
    ("substance_cannabis", "committed to zero cannabis for the rest of the cycle"),
    ("substance_thc", "the THC experiment is over as far as I'm concerned"),
    ("substance_porn", "we agreed the porn moderation streak gets logged daily"),
    ("substance_alcohol_family", "he reported three beers at the wedding reception"),
    # chronological-age leakage (PhenoAge Option A — never public)
    ("age_years_old", "remarkable adherence for a man 43 years old"),
    ("age_turns", "before he turns 44 I want the RHR under 60"),
    ("age_im", "he told me: I'm 43 and tired of restarting"),
    # genotype strings (PRE-13 / DATA_GOVERNANCE)
    ("genotype_rsid", "the rs429358 variant explains the lipid response"),
    ("genotype_gene", "given his APOE status we keep saturated fat conservative"),
    ("genotype_allele_pair", "as an e3/e4 carrier the target stays aggressive"),
    ("genotype_vocab", "he is heterozygous for the relevant polymorphism"),
    # real-person third parties (privacy_guard banned-name sets)
    ("real_name_full", "as Peter Attia says, zone 2 is the base of the pyramid"),
    ("real_name_surname", "ran the Huberman morning-light protocol for a week"),
    # private third parties / family specifics (journal_quotes family vocabulary)
    ("family_specific", "he skipped the session to drive my sister to the airport"),
]


@pytest.mark.parametrize("label,text", SEEDED_VIOLATIONS, ids=[s[0] for s in SEEDED_VIOLATIONS])
def test_privacy_filter_catches_seeded_violation(label, text):
    hits = cd.find_dossier_violations(text)
    assert hits, f"seeded violation NOT caught ({label}): {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "committed to a 10pm screens-off window through Sunday",
        "sleep_efficiency trended up; the call said up — confirmed",
        "protein floor held at 180g on 6 of 7 days",
        "biological age moved in the right direction this quarter",  # bio-age phrasing without a number is public
    ],
)
def test_privacy_filter_passes_clean_lines(text):
    assert cd.find_dossier_violations(text) == []


def test_violating_commitment_is_withheld_wholesale():
    item = {
        "sk": "COMMITMENT#commit_x",
        "created_date": "2026-07-23",
        "commitment_natural": "zero cannabis for the rest of the cycle",
        "status": "pending",
    }
    entry, status = cd.commitment_entry(item)
    assert entry is None and status == cd.WITHHELD


def test_violation_in_secondary_field_also_withholds():
    # fail-closed applies to EVERY text field, not just the headline one
    item = {
        "sk": "COMMITMENT#commit_y",
        "created_date": "2026-07-23",
        "commitment_natural": "hold the evening wind-down window",
        "status": "broken",
        "outcome_notes": "broken — he was drinking at the reunion",
    }
    entry, status = cd.commitment_entry(item)
    assert entry is None and status == cd.WITHHELD


# ══════════════════════════════════════════════════════════════════════════════
# ADR-141 §4 — conversation-channel rows NEVER enter a dossier
# ══════════════════════════════════════════════════════════════════════════════


def _conversation_learning():
    return {
        "sk": "LEARNING#2026-07-20#conv-abc",
        "date": "2026-07-20",
        "channel": "conversation",
        "status": "noted",
        "metric": "mood",
        "reason": "a perfectly clean line that still must not render",
        "answer_quote": "MATTHEW-PRIVATE verbatim answer",
        "takeaway": "MATTHEW-PRIVATE takeaway",
    }


def test_conversation_channel_learning_is_excluded_even_when_clean():
    entry, status = cd.learning_entry(_conversation_learning())
    assert entry is None and status == cd.SKIP


def test_missing_channel_defaults_to_data_and_renders():
    entry, status = cd.learning_entry(
        {"sk": "LEARNING#2026-07-19#x", "date": "2026-07-19", "status": "confirmed", "metric": "hrv", "reason": "hrv trended up as called"}
    )
    assert status == cd.OK
    assert entry["date"] == "2026-07-19"


def test_learning_entry_never_carries_private_fields():
    # allowlist construction: even for a data-channel row carrying stray private
    # fields, nothing outside the allowlist can cross into the public entry.
    item = {
        "sk": "LEARNING#2026-07-19#x",
        "date": "2026-07-19",
        "status": "confirmed",
        "metric": "hrv",
        "reason": "clean",
        "answer_quote": "should never cross",
        "question": "should never cross",
    }
    entry, status = cd.learning_entry(item)
    assert status == cd.OK
    blob = json.dumps(entry)
    assert "answer_quote" not in blob and "should never cross" not in blob and "question" not in blob


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — verbatim projections: date on every line, evidence link where present
# ══════════════════════════════════════════════════════════════════════════════


def test_commitment_entry_is_verbatim_and_dated():
    item = {
        "sk": "COMMITMENT#commit_20260722_screens",
        "created_date": "2026-07-22",
        "commitment_natural": "screens off by 10pm through Sunday",
        "status": "kept",
        "due_date": "2026-07-27",
        "outcome": "kept",
        "outcome_date": "2026-07-28",
        "action_check": {"metric": "sleep_efficiency", "direction": "up"},
        "surfaced_to_subject": True,  # not public — must not cross
    }
    entry, status = cd.commitment_entry(item)
    assert status == cd.OK
    assert entry["text"] == "screens off by 10pm through Sunday"  # exact bytes
    assert entry["date"] == "2026-07-22"
    assert entry["check"] == {"metric": "sleep_efficiency", "direction": "up"}
    assert entry["evidence_link"] == "/data/sleep/"
    assert "surfaced_to_subject" not in entry


def test_dateless_record_cannot_become_a_dossier_line():
    entry, status = cd.commitment_entry({"sk": "COMMITMENT#x", "commitment_natural": "clean text, no date"})
    assert entry is None and status == cd.SKIP


def test_learning_entry_evidence_link_only_when_prediction_present():
    with_pred, s1 = cd.learning_entry(
        {
            "sk": "LEARNING#2026-07-18#a",
            "date": "2026-07-18",
            "status": "refuted",
            "metric": "rhr",
            "reason": "called down, went up",
            "prediction_id": "pred_1",
            "actual_value": 61,
            "threshold": 58,
        }
    )
    without, s2 = cd.learning_entry(
        {"sk": "LEARNING#2026-07-18#b", "date": "2026-07-18", "status": "confirmed", "metric": "rhr", "reason": "clean"}
    )
    assert s1 == s2 == cd.OK
    assert with_pred["evidence_link"] == "/coaching/scorecard/"
    assert with_pred["evidence"]["prediction_id"] == "pred_1"
    assert without["evidence_link"] is None


def test_reason_translator_is_applied():
    entry, _ = cd.learning_entry(
        {"sk": "LEARNING#2026-07-18#c", "date": "2026-07-18", "status": "confirmed", "metric": "hrv", "reason": "[machine spec] raw"},
        reason_translator=lambda t: "reader copy",
    )
    assert entry["reason"] == "reader copy"


def test_relationship_entry_dated_and_projected():
    entry, status = cd.relationship_entry(
        {
            "journey_phase": "working_rapport",
            "rapport_level": 0.4231,
            "interaction_count": 9,
            "tenure_days": 34,
            "first_interaction_date": "2026-06-22",
            "last_interaction_date": "2026-07-24",
            "updated_at": "2026-07-25T04:00:00+00:00",
            "context_summary": "steady adherence, one broken commitment revisited",
        }
    )
    assert status == cd.OK
    assert entry["date"] == "2026-07-25"
    assert entry["journey_phase"] == "working_rapport"
    assert entry["rapport_level"] == 0.423
    assert entry["first_interaction_date"] == "2026-06-22"


def test_docket_entry_takes_this_coachs_side_both_id_forms():
    row = {
        "sk": "OPEN#glucose|sleep#late-eating",
        "opened_date": "2026-07-20",
        "topic": "late eating vs sleep quality",
        "coach_a": "glucose",
        "coach_b": "sleep",
        "claims": {"glucose": "post-8pm meals spike overnight glucose", "sleep": "meal timing is noise next to the screens window"},
        "criterion": {"description": "sleep_efficiency >= 88 on 2026-08-03"},
        "resolution_date": "2026-08-03",
    }
    for cid in ("sleep", "sleep_coach"):
        entry, status = cd.docket_entry(row, cid)
        assert status == cd.OK, cid
        assert entry["my_claim"] == "meal timing is noise next to the screens window"
        assert entry["versus"] == "glucose"
        assert entry["date"] == "2026-07-20"
        assert entry["resolution_date"] == "2026-08-03"
    entry, status = cd.docket_entry(row, "training_coach")
    assert entry is None and status == cd.SKIP


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — corrections: reuse the #1689 ledger; retract removes + counts; never mutate
# ══════════════════════════════════════════════════════════════════════════════


def _ledger_row(record_sk, action, note="stale — retracted", coach="sleep_coach"):
    return coach_corrections.build_correction_item(
        {"surface": cd.CORRECTION_SURFACE, "coach": coach, "record_sk": record_sk, "action": action},
        note,
        "other",
    )


def test_dossier_corrections_filters_to_surface_and_coach():
    rows = [
        _ledger_row("COMMITMENT#a", "retract"),
        _ledger_row("COMMITMENT#b", "correct", coach="glucose_coach"),  # other coach
        coach_corrections.build_correction_item({"surface": "review_pack", "coach": "sleep_coach"}, "not ours", "framing"),
    ]
    got = cd.dossier_corrections(rows, "sleep_coach")
    assert [c["record_sk"] for c in got] == ["COMMITMENT#a"]
    assert got[0]["action"] == "retract"
    assert got[0]["date"]  # the correction itself is dated (auditable)


def test_apply_corrections_retract_removes_and_counts_without_mutating_input():
    entries = [
        {"record_id": "COMMITMENT#a", "date": "2026-07-20", "text": "x"},
        {"record_id": "COMMITMENT#b", "date": "2026-07-21", "text": "y"},
    ]
    snapshot = json.dumps(entries, sort_keys=True)
    kept, retracted = cd.apply_corrections(entries, cd.dossier_corrections([_ledger_row("COMMITMENT#a", "retract")], "sleep_coach"))
    assert retracted == 1
    assert [e["record_id"] for e in kept] == ["COMMITMENT#b"]
    assert json.dumps(entries, sort_keys=True) == snapshot  # pure — inputs unmutated


def test_apply_corrections_correct_attaches_dated_note():
    entries = [{"record_id": "LEARNING#2026-07-18#a", "date": "2026-07-18", "reason": "r"}]
    kept, retracted = cd.apply_corrections(
        entries,
        cd.dossier_corrections([_ledger_row("LEARNING#2026-07-18#a", "correct", note="the baseline cited was stale")], "sleep_coach"),
    )
    assert retracted == 0
    notes = kept[0]["corrections"]
    assert notes and notes[0]["note"] == "the baseline cited was stale" and notes[0]["date"]


def test_apply_corrections_violating_note_is_withheld_but_dated():
    kept, _ = cd.apply_corrections(
        [{"record_id": "COMMITMENT#a", "date": "2026-07-20", "text": "x"}],
        cd.dossier_corrections([_ledger_row("COMMITMENT#a", "correct", note="actually it was about cannabis")], "sleep_coach"),
    )
    n = kept[0]["corrections"][0]
    assert n["note"] is None and n["note_withheld"] is True and n["date"]


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — honest zero-state
# ══════════════════════════════════════════════════════════════════════════════


def test_commitment_counts_zero_state_is_honest():
    counts = cd.commitment_counts([])
    assert counts == {"held": 0, "kept": 0, "broken": 0, "pending": 0, "unresolved": 0}


def test_commitment_counts_tally():
    entries = [{"status": "kept"}, {"status": "broken"}, {"status": "pending"}, {"status": "kept"}]
    counts = cd.commitment_counts(entries)
    assert counts["held"] == 4 and counts["kept"] == 2 and counts["broken"] == 1 and counts["pending"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Site layer — /api/coach/{id} carries the dossier end-to-end (no LLM anywhere)
# ══════════════════════════════════════════════════════════════════════════════

from web import site_api_coach as api  # noqa: E402


def _cond_parts(cond):
    """(pk, sk_prefix_or_None) out of a boto3 Key condition — for hook dispatch."""
    expr = cond.get_expression()
    if expr.get("operator") == "AND":
        a, b = expr["values"]
        pk = a.get_expression()["values"][1]
        sk = b.get_expression()["values"][1]
        return pk, sk
    return expr["values"][1], None


def _seeded_table():
    coach_pk = "COACH#sleep_coach"
    rows = {
        (coach_pk, "COMMITMENT#"): [
            {
                "pk": coach_pk,
                "sk": "COMMITMENT#commit_20260722_screens",
                "created_date": "2026-07-22",
                "commitment_natural": "screens off by 10pm through Sunday",
                "status": "pending",
                "due_date": "2026-07-27",
            },
            {  # seeded privacy violation — must be withheld and counted
                "pk": coach_pk,
                "sk": "COMMITMENT#commit_20260721_vice",
                "created_date": "2026-07-21",
                "commitment_natural": "zero cannabis this cycle",
                "status": "pending",
            },
            {  # retracted below via the corrections ledger
                "pk": coach_pk,
                "sk": "COMMITMENT#commit_20260720_stale",
                "created_date": "2026-07-20",
                "commitment_natural": "a stale commitment Matthew retracted",
                "status": "pending",
            },
        ],
        (coach_pk, "LEARNING#"): [
            {
                "pk": coach_pk,
                "sk": "LEARNING#2026-07-19#pred1-confirmed",
                "date": "2026-07-19",
                "channel": "data",
                "status": "confirmed",
                "metric": "sleep_efficiency",
                "reason": "sleep_efficiency cleared the threshold as called",
                "prediction_id": "pred_1",
            },
            _conversation_learning() | {"pk": coach_pk},  # ADR-141: must NOT appear
        ],
        ("USER#matthew#SOURCE#coach_corrections", None): [
            _ledger_row("COMMITMENT#commit_20260720_stale", "retract"),
        ],
        ("ENSEMBLE#docket", "OPEN#"): [
            {
                "pk": "ENSEMBLE#docket",
                "sk": "OPEN#glucose|sleep#late-eating",
                "opened_date": "2026-07-20",
                "topic": "late eating vs sleep quality",
                "coach_a": "glucose",
                "coach_b": "sleep",
                "claims": {"glucose": "late meals spike overnight glucose", "sleep": "meal timing is noise next to screens"},
                "criterion": {"description": "sleep_efficiency >= 88 on 2026-08-03"},
                "resolution_date": "2026-08-03",
            }
        ],
    }

    def _hook(table, **kw):
        pk, sk = _cond_parts(kw["KeyConditionExpression"])
        for (rpk, rsk), items in rows.items():
            if rpk == pk and (rsk is None or (sk or "").startswith(rsk) or (rsk or "").startswith(sk or "")):
                return {"Items": [dict(i) for i in items]}
        return {"Items": []}

    def _get_hook(table, key, **kw):
        if key.get("sk") == "RELATIONSHIP#state" and key.get("pk") == coach_pk:
            return {
                "Item": {
                    "pk": coach_pk,
                    "sk": "RELATIONSHIP#state",
                    "journey_phase": "working_rapport",
                    "rapport_level": 0.41,
                    "interaction_count": 7,
                    "tenure_days": 30,
                    "first_interaction_date": "2026-06-22",
                    "last_interaction_date": "2026-07-24",
                    "updated_at": "2026-07-25T04:00:00+00:00",
                    "context_summary": "steady adherence, one commitment revisited",
                }
            }
        return {}

    return FakeDdbTable(query_hook=_hook, get_item_hook=_get_hook)


def _dossier_via_api(monkeypatch):
    monkeypatch.setattr(api, "table", _seeded_table())
    resp = api.handle_coach({"rawPath": "/api/coach/sleep_coach"})
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])["dossier"]


def test_site_dossier_renders_verbatim_with_dates_and_evidence(monkeypatch):
    d = _dossier_via_api(monkeypatch)
    assert d["verbatim"] is True
    texts = [c["text"] for c in d["commitments"]]
    assert texts == ["screens off by 10pm through Sunday"]  # verbatim, exact bytes
    assert all(c["date"] for c in d["commitments"])
    assert d["learnings"][0]["date"] == "2026-07-19"
    assert d["learnings"][0]["evidence_link"] == "/coaching/scorecard/"
    assert d["relationship"]["journey_phase"] == "working_rapport"
    assert d["docket_positions"][0]["my_claim"] == "meal timing is noise next to screens"
    assert d["docket_positions"][0]["date"] == "2026-07-20"


def test_site_dossier_withholds_seeded_violation_and_counts_it(monkeypatch):
    d = _dossier_via_api(monkeypatch)
    blob = json.dumps(d)
    assert "cannabis" not in blob
    assert d["withheld"] >= 1


def test_site_dossier_excludes_conversation_learnings_structurally(monkeypatch):
    d = _dossier_via_api(monkeypatch)
    blob = json.dumps(d)
    assert "MATTHEW-PRIVATE" not in blob
    assert "conversation" not in json.dumps(d["learnings"])
    assert len(d["learnings"]) == 1  # the data-channel row only


def test_site_dossier_honors_retraction_and_counts_it(monkeypatch):
    d = _dossier_via_api(monkeypatch)
    blob = json.dumps(d)
    assert "stale commitment Matthew retracted" not in blob
    assert d["retracted"] == 1


def test_site_dossier_zero_state_is_honest(monkeypatch):
    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=lambda t, **kw: {"Items": []}, get_item_hook=lambda t, k, **kw: {}))
    resp = api.handle_coach({"rawPath": "/api/coach/sleep_coach"})
    d = json.loads(resp["body"])["dossier"]
    assert d["commitments"] == [] and d["learnings"] == [] and d["docket_positions"] == []
    assert d["relationship"] is None
    assert d["commitment_counts"]["held"] == 0
    assert d["withheld"] == 0 and d["retracted"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — the MCP audit/correction tool (private by construction)
# ══════════════════════════════════════════════════════════════════════════════


def _mcp(monkeypatch, fake):
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", fake)
    return tci


def test_mcp_view_returns_unfiltered_memory_with_conversation_flagged(monkeypatch):
    conv = _conversation_learning() | {"pk": "COACH#sleep_coach"}
    fake = FakeDdbTable(rows=[conv])
    tci = _mcp(monkeypatch, fake)
    out = tci.tool_audit_coach_dossier({"coach_id": "sleep", "action": "view"})
    assert "UNFILTERED" in out["view"]
    learning_rows = out["records"]["learning"]
    # the private view DOES show the conversation row (this is Matthew's audit view)…
    assert any(r.get("answer_quote") == "MATTHEW-PRIVATE verbatim answer" for r in learning_rows)
    # …explicitly flagged as never-public
    assert any("ADR-141" in str(r.get("_private_channel", "")) for r in learning_rows)


def test_mcp_retract_writes_dated_correction_and_never_mutates(monkeypatch):
    record = {
        "pk": "COACH#sleep_coach",
        "sk": "COMMITMENT#commit_20260720_stale",
        "commitment_natural": "a stale commitment",
        "created_date": "2026-07-20",
    }
    fake = FakeDdbTable(rows=[record])
    tci = _mcp(monkeypatch, fake)
    out = tci.tool_audit_coach_dossier(
        {"coach_id": "sleep_coach", "action": "retract", "record_sk": record["sk"], "note": "stale — pre-reset baseline"}
    )
    assert out.get("success") is True
    assert out["correction_sk"].startswith("CORRECTION#")
    # exactly ONE write happened, and it went to the corrections ledger — the
    # memory record was never touched (auditable, not silently editable)
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["pk"] == coach_corrections.PK
    assert put["item_ref"]["surface"] == cd.CORRECTION_SURFACE
    assert put["item_ref"]["record_sk"] == record["sk"]
    assert put["item_ref"]["action"] == "retract"
    assert fake.store[("COACH#sleep_coach", record["sk"])] == record


def test_mcp_retract_requires_existing_record_and_note(monkeypatch):
    tci = _mcp(monkeypatch, FakeDdbTable(rows=[]))
    missing = tci.tool_audit_coach_dossier({"coach_id": "sleep", "action": "retract", "record_sk": "COMMITMENT#nope", "note": "x"})
    assert "no record" in missing["error"]
    no_note = tci.tool_audit_coach_dossier({"coach_id": "sleep", "action": "retract", "record_sk": "COMMITMENT#nope"})
    assert "note required" in no_note["error"]
    bad_coach = tci.tool_audit_coach_dossier({"coach_id": "nonsense", "action": "view"})
    assert "coach_id required" in bad_coach["error"]

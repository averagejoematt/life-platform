"""tests/test_chapter_corrections_6177.py — dated public chapter corrections, platform-signed (#6177).

Owner rulings 2026-11-22 §3 (a dated public correction through the established process; originals preserved) and §7
(do not present Margaret Calloway as an independent human editor; disclose her AI status where her historical notes
render; future corrections carry a transparent platform signature, date, factual explanation and approval history).

What this pins:
  * the record (lambdas/content/chapter_corrections.py): the platform's signature is computed, never supplied; a
    persona can never sign; nothing renders without the owner's approval recorded on it; supersession keeps both.
  * the one writer (mcp/tools_chapter_corrections.py): append-only — conditional put, a one-time approval that never
    rewrites the statement, no delete; ``approved`` must be exactly true.
  * the one public reader (/api/chapters ``corrections``): approved only; a failed read is ``null``, never ``[]``.
  * the snapshot (scripts/publish_snapshot_chapter_corrections.py) and the feed (scripts/v4_build_rss.py) refuse a
    persona signature and a failed read, and the feed keeps a historical note word for word with the disclosure.
  * the code sweep: no source writes a NEW note or correction signed by a persona (the two historical artifacts that
    reproduce the October 2026 notes verbatim are named, with why).
"""

# premerge-gate: sweeps lambdas/, mcp/, deploy/ and scripts/ for a persona-signed note literal, so a new file anywhere in them is in scope

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content import chapter_corrections as CC  # noqa: E402

PERSONA_SIGNED = re.compile(r"(?:Editor\\?[’']s note|Correction|Qualification)[^\n\"]{0,40}— Margaret Calloway|Margaret Calloway:\*\*")
#: Files that reproduce the October 2026 Margaret-signed notes verbatim — the audit trail the ruling preserves. Neither
#: writes a new note: one is the season rebuild's historical text, the other a one-shot repair whose marker must keep
#: matching the note it already published (re-running it is a no-op).
HISTORICAL = {
    "scripts/season_promote.py": "the October 2026 season rebuild's notes, kept verbatim as published (#4537)",
    "deploy/fix_prologue_part3_editors_note.py": "the #1985 one-shot repair; its marker detects the note it already published",
}


def _proposal(**kw):
    base = dict(
        chapter_id="week-09",
        correction_id="interview-scene",
        kind="correction",
        published_said="The chapter described a conversation as an interview.",
        record_shows="No interview took place; the record holds no such conversation.",
        evidence="The chronicle row for the week and its source dossier.",
        proposed_at="2026-11-22T18:00:00Z",
    )
    base.update(kw)
    return CC.new_proposal(**base)


def _approved(**kw):
    item = _proposal(**kw)
    day = "2026-11-23"
    item.update(
        approvals=[CC.approval(at="2026-11-23T17:00:00Z", dated_on=day)],
        approved_at="2026-11-23T17:00:00Z",
        dated_on=day,
        signature=CC.signature(item["kind"], day),
    )
    return item


# ── the record ──────────────────────────────────────────────────────────────────────────────


def test_the_signature_is_the_platforms_dated_in_words():
    assert CC.signature("correction", "2026-11-22") == "Correction, 22 November 2026 — Average Joe Matt editorial record"
    assert CC.signature("qualification", "2026-11-03") == "Qualification, 3 November 2026 — Average Joe Matt editorial record"
    for name in CC.persona_names():
        assert name not in CC.signature("correction", "2026-11-22")


def test_every_persona_is_known_and_none_can_sign():
    names = CC.persona_names()
    assert {"Margaret Calloway", "Elena Voss"} <= names
    assert len(names) >= 8, "the coaches' names come from the persona registry"
    for name in sorted(names):
        bad = _approved()
        bad["signature"] = f"Correction, 23 November 2026 — {name}"
        with pytest.raises(CC.CorrectionError):
            CC.validate(bad)
        for field in ("published_said", "record_shows", "evidence"):
            with pytest.raises(CC.CorrectionError):
                _proposal(**{field: f"A sentence. — {name}"})
            with pytest.raises(CC.CorrectionError):
                _proposal(**{field: f"{name}: a sentence."})


def test_a_statement_may_name_a_coach_but_is_never_an_editors_note():
    ok = _proposal(published_said="The chapter said Lisa Park's call was right.")
    assert ok["published_said"].startswith("The chapter said Lisa Park")
    with pytest.raises(CC.CorrectionError):
        _proposal(published_said="Editor's note: the chapter was wrong.")


def test_a_proposal_is_unapproved_unsigned_undated_and_never_public():
    p = _proposal()
    assert p["approvals"] == [] and p["signature"] is None and p["dated_on"] is None
    assert p["sk"] == "CHAPTER_CORRECTION#week-09#interview-scene" and p["pk"] == "USER#matthew#SOURCE#chronicle"
    assert not CC.is_approved(p)
    assert CC.public_view([p]) == []


def test_validation_refuses_what_must_not_be_served():
    good = _approved()
    assert CC.is_approved(good)
    for mutate in (
        lambda i: i.update(approvals=[]),
        lambda i: i.update(approvals=[{"by": "session", "at": "2026-11-23T17:00:00Z"}]),
        lambda i: i.update(signature="Correction, 23 November 2026 — Margaret Calloway"),
        lambda i: i.update(signature="Correction, 24 November 2026 — Average Joe Matt editorial record"),  # wrong day
        lambda i: i.update(dated_on=None),
        lambda i: i.update(record_shows=""),
        lambda i: i.update(sk="CHAPTER_CORRECTION#week-08#interview-scene"),
        lambda i: i.update(supersedes="interview-scene"),
    ):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        assert not CC.is_approved(bad), bad


def test_public_view_keeps_a_superseded_correction_marked_and_drops_the_unapproved():
    first = _approved()
    second = _approved(correction_id="interview-scene-2", supersedes="interview-scene", kind="qualification")
    second.update(dated_on="2026-11-24", signature=CC.signature("qualification", "2026-11-24"))
    second["approvals"][0]["on"] = "2026-11-24"
    pending = _proposal(correction_id="pending-one", supersedes="interview-scene-2")
    view = CC.public_view([pending, second, first])
    assert [c["id"] for c in view] == ["interview-scene", "interview-scene-2"]
    assert view[0]["superseded_by"] == "interview-scene-2" and view[1]["superseded_by"] is None
    assert set(view[0]) == set(CC.PUBLIC_FIELDS)
    assert view[0]["approvals"] == [{"by": "owner", "on": "2026-11-23", "via": CC.APPROVED_VIA}]
    # an unapproved successor neither renders nor marks its predecessor replaced
    assert CC.public_view([first, pending])[0]["superseded_by"] is None


# ── the disclosure and the signature are one constant on every surface ──────────────────────


def test_the_disclosure_and_signature_are_pinned_equal_across_python_js_and_the_repair_device():
    js = open(os.path.join(_REPO, "www", "src", "lib", "chapter_corrections.js"), encoding="utf-8").read()
    assert f'export const PERSONA_DISCLOSURE = "{CC.PERSONA_DISCLOSURE}";' in js
    assert f'export const PLATFORM_SIGNATURE = "{CC.PLATFORM_SIGNATURE}";' in js
    assert CC.PERSONA_DISCLOSURE == "Margaret Calloway is an AI editorial persona of the platform, not a person."
    repair = open(os.path.join(_REPO, "deploy", "restart_leadin_repair.py"), encoding="utf-8").read()
    assert f'sig = "{CC.PLATFORM_SIGNATURE}"' in repair


def test_no_source_signs_a_new_note_or_correction_with_a_persona():
    offenders = []
    for top in ("lambdas", "mcp", "deploy", "scripts"):
        for root, dirs, files in os.walk(os.path.join(_REPO, top)):
            dirs[:] = [d for d in dirs if d not in ("archive", "__pycache__", "node_modules")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(root, f), _REPO)
                if rel in HISTORICAL:
                    continue
                if PERSONA_SIGNED.search(open(os.path.join(root, f), encoding="utf-8").read()):
                    offenders.append(rel)
    assert not offenders, f"a persona signs a new note or correction in: {offenders} (#6177: the platform signs)"
    for rel in HISTORICAL:  # the allowlist is real: each still carries the verbatim historical note
        assert PERSONA_SIGNED.search(open(os.path.join(_REPO, rel), encoding="utf-8").read()), rel


def test_the_sweep_catches_a_planted_persona_signature():
    for planted in (
        'block = f"> **Editor\'s note — Margaret Calloway:** {note}"',
        "'<strong>Editor\\'s note — Margaret Calloway:</strong>'",
        '"Correction, 22 November 2026 — Margaret Calloway"',
    ):
        assert PERSONA_SIGNED.search(planted), planted


def test_the_legacy_writers_note_is_platform_signed_and_refuses_a_persona_signoff():
    from ai import margaret_editor_pass as mep

    out = mep.splice_editors_note("Body.\n\n---\n*Week 8 of The Measured Life*", "A craft note.")
    assert "> **Editor's note — Average Joe Matt editorial record:** A craft note." in out and "Margaret" not in out
    assert mep.extract_editors_note({"editors_note": "A note. --Margaret"}, True, set()) is None


# ── the one writer: the MCP tool ────────────────────────────────────────────────────────────


class _FakeTable:
    def __init__(self):
        self.items: dict = {}
        self.calls: list = []

    def put_item(self, Item, ConditionExpression=None):
        self.calls.append(("put", ConditionExpression))
        k = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = json.loads(json.dumps(Item))

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": json.loads(json.dumps(it))} if it else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        self.calls.append(("update", UpdateExpression))
        it = self.items.get((Key["pk"], Key["sk"]))
        if it is None or len(it.get("approvals") or []) != ExpressionAttributeValues[":zero"]:
            raise RuntimeError("ConditionalCheckFailedException")
        for field in CC.STATEMENT_FIELDS:  # the approval never rewrites the statement
            assert field not in UpdateExpression.split("SET", 1)[1].replace("approvals", "").replace("approved_at", "")
        it["approvals"] = it["approvals"] + ExpressionAttributeValues[":a"]
        it.update(
            approved_at=ExpressionAttributeValues[":at"],
            dated_on=ExpressionAttributeValues[":d"],
            signature=ExpressionAttributeValues[":s"],
        )

    def query(self, **kw):
        return {"Items": [json.loads(json.dumps(v)) for (p, s), v in sorted(self.items.items()) if s.startswith(CC.SK_PREFIX)]}

    def delete_item(self, **kw):  # pragma: no cover — must never be called
        raise AssertionError("a correction is never deleted")


@pytest.fixture
def tool(monkeypatch):
    import mcp.tools_chapter_corrections as t

    table = _FakeTable()
    monkeypatch.setattr(t, "_table_ref", table)
    monkeypatch.setattr(t, "pacific_today", lambda: "2026-11-23")
    return t, table


_ARGS = dict(
    chapter_id="week-09",
    correction_id="interview-scene",
    kind="correction",
    published_said="The chapter described a conversation as an interview.",
    record_shows="No interview took place.",
    evidence="The chronicle row for the week.",
)


def test_propose_then_approve_is_append_only_and_platform_signed(tool):
    t, table = tool
    r = t.tool_manage_chapter_corrections({"action": "propose", **_ARGS})
    assert r["stored"] and r["renders"] is False
    assert t.tool_manage_chapter_corrections({"action": "list"})["rendering"] == 0
    dup = t.tool_manage_chapter_corrections({"action": "propose", **_ARGS, "record_shows": "Different words."})
    assert "append-only" in dup["error"]
    stored = table.get_item(Key={"pk": CC.pk(), "sk": CC.sk("week-09", "interview-scene")})["Item"]
    assert stored["record_shows"] == "No interview took place."  # the duplicate rewrote nothing

    for not_true in (None, False, "true", 1):
        r = t.tool_manage_chapter_corrections(
            {"action": "approve", "chapter_id": "week-09", "correction_id": "interview-scene", "approved": not_true}
        )
        assert "exactly true" in r["error"]
    r = t.tool_manage_chapter_corrections(
        {"action": "approve", "chapter_id": "week-09", "correction_id": "interview-scene", "approved": True}
    )
    assert r["approved"] and r["signature"] == "Correction, 23 November 2026 — Average Joe Matt editorial record"
    again = t.tool_manage_chapter_corrections(
        {"action": "approve", "chapter_id": "week-09", "correction_id": "interview-scene", "approved": True}
    )
    assert "already approved" in again["error"]
    listing = t.tool_manage_chapter_corrections({"action": "list", "chapter_id": "week-09"})
    assert listing["rendering"] == 1 and listing["corrections"][0]["renders"] is True
    assert all(kind in ("put", "update") for kind, _ in table.calls)


def test_a_supersession_must_name_a_real_correction(tool):
    t, _ = tool
    r = t.tool_manage_chapter_corrections({"action": "propose", **_ARGS, "correction_id": "second", "supersedes": "nothing-here"})
    assert "supersedes names no correction" in r["error"]


def test_the_tool_is_registered_with_its_replay_semantics():
    import mcp.idempotency as idem
    import mcp.registry as reg

    assert "manage_chapter_corrections" in reg.TOOLS
    assert "manage_chapter_corrections" in idem.REPLAY_SEMANTICS


# ── the public reader: /api/chapters ────────────────────────────────────────────────────────


def test_the_route_serves_approved_corrections_only_and_says_when_it_cannot_read():
    from web import site_api_chapters as chapters

    rows = [_approved(), _proposal(correction_id="pending-one")]
    assert [c["id"] for c in chapters.corrections_field(lambda: rows)["corrections"]] == ["interview-scene"]

    def boom():
        raise RuntimeError("throttled")

    failed = chapters.corrections_field(boom)
    assert failed["corrections"] is None and failed["corrections_error"]


# ── the snapshot and the feed ──────────────────────────────────────────────────────────────


def _public_chapters():
    return {"chapter": [{"id": "week-09", "status": "published"}, {"id": "week-08", "status": "held"}]}


def test_the_snapshot_carries_approved_platform_signed_corrections_and_refuses_the_rest():
    import publish_snapshot_chapter_corrections as SC

    view = CC.public_view([_approved()])
    doc = SC.validate(SC.compose({"corrections": view}), _public_chapters())
    assert [c["id"] for c in doc["corrections"]] == ["interview-scene"]
    assert SC.compose({"weeks": []})["state"] == "absent"  # a Site API from before #6177
    with pytest.raises(ValueError):
        SC.compose({"corrections": None, "corrections_error": "x"})  # a failed read never builds
    for mutate in (
        lambda c: c.update(signature="Correction, 23 November 2026 — Margaret Calloway"),
        lambda c: c.update(approvals=[]),
        lambda c: c.update(record_shows=""),  # a wire-emptied text never renders blank
        lambda c: c.update(extra="field"),
    ):
        bad = json.loads(json.dumps(view))
        mutate(bad[0])
        with pytest.raises(ValueError):
            SC.validate(SC.compose({"corrections": bad}), _public_chapters())
    held = json.loads(json.dumps(view))
    held[0].update(chapter_id="week-08", signature=held[0]["signature"])
    assert SC.validate(SC.compose({"corrections": held}), _public_chapters())["corrections"] == []


def test_the_snapshot_route_failure_stops_the_build():
    import publish_snapshot_chapter_corrections as SC

    def down(_path):
        raise urllib.error.HTTPError("u", 503, "x", {}, None)

    with pytest.raises(ValueError):
        SC.live(down, lambda m: None)

    def missing(_path):
        raise urllib.error.HTTPError("u", 404, "x", {}, None)

    assert SC.live(missing, lambda m: None)["state"] == "absent"


def test_the_fixture_runs_the_platforms_filter():
    import publish_snapshot_chapter_corrections as SC

    doc = SC.fixture(os.path.join(_REPO, "www", "content", "fixtures"))
    text = json.dumps(doc)
    assert "SENTINEL-UNAPPROVED" not in text
    assert {c["id"] for c in doc["corrections"]} == {"sample-walk-distance", "sample-walk-distance-2"}


def test_the_feed_keeps_the_historical_note_verbatim_with_the_disclosure_and_leads_with_a_correction():
    import v4_build_rss as R

    note = (
        "*Editor's note, October 2026 — Margaret Calloway: this prologue was rewritten with the plan's final figures. "
        "The earlier version quoted working numbers from before the plan was frozen.*"
    )
    desc = R.item_description(note + "\n\nMatthew steps on the scale for the first time. " * 3)
    assert desc.startswith(note + " (" + CC.PERSONA_DISCLOSURE + ")")
    view = CC.public_view([_approved()])
    led = R.item_description("A plain excerpt.", view)
    assert led.startswith("Correction, 23 November 2026 — Average Joe Matt editorial record. What was published:")
    replaced = [dict(view[0], superseded_by="later")]
    assert R.item_description("A plain excerpt.", replaced) == "A plain excerpt."
    assert R.corrections_by_url({"corrections": view})["/journal/posts/week-09/"][0]["id"] == "interview-scene"
    assert R.corrections_by_url({"weeks": []}) == {}
    with pytest.raises(SystemExit):
        R.corrections_by_url({"corrections": None})

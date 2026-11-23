"""tests/test_chapter_editions_6193.py — second editions of published chapters, dark behind one switch (#6193).

Owner ruling 2026-11-22 §3: the canonical chapter URL serves the approved latest edition; the original publication date
is preserved and a separate revision date shown; the original evidence is kept privately and immutably; an unredacted
first edition is never restored to public access — a public first edition, if offered, is a privacy-safe archival
rendering with a note that never describes what was removed; no misleading feed announcement, no subscriber resend.

What this pins (synthetic fixtures only — no chapter prose, no private call):
  * the record (lambdas/content/chapter_editions.py): computed platform words, append-only shapes, nothing public
    without the owner's approval, the first edition's evidence record, the gates (content filter, private calls,
    truth checks) withholding fail-closed;
  * the one writer (mcp/tools_chapter_corrections.py, the existing tool — no new tool): approved exactly true, the
    backup before the approval, carried corrections approved, one-time approval, no delete;
  * the switch: /api/chapters byte-identical and its reader never called while LIVE is False; the exporter writes no
    file; the public view needs the switch on;
  * the snapshot validation; the backup script (write-once, private, read back);
  * the feed (scripts/v4_build_rss.py, the real builder) and the send selection (the real
    chronicle_email_sender_lambda._get_this_weeks_installment): an edition changes no item, no date, no guid, no send.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

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

from content import chapter_corrections as CC, chapter_editions as CE, private_call_check  # noqa: E402

COMMITTED_LIVE = CE.LIVE  # captured at import, before the conftest baseline fixture touches it

TEXT = (
    '"A Sample Chapter"\n\n*A sample summary line for a test, for layout only.*\n\n'
    "Sample edition text for a test, for layout only. The week's figures are counted from the log as it stands.\n\n"
    "A second paragraph says what the record holds, and nothing more."
)
ARCHIVAL = "Sample archival rendering for a test, for layout only. It is prepared for public reading and approved on its own."
NEVER = lambda _t: False  # noqa: E731 — the publication record with nothing withheld
NO_FILTER_HITS = lambda _t: []  # noqa: E731


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _original(chapter="week-04", at="2026-11-22T17:00:00Z"):
    prefix = f"backups/chronicle-editions/{chapter}/20261122T170000Z/"
    return CE.original_record(
        chapter_id=chapter,
        row_sk="DATE#2026-09-08",
        backup_prefix=prefix,
        objects=[{"source": "ddb:DATE#2026-09-08", "backup_key": prefix + "ddb/row.json", "sha256": "a" * 64}],
        backed_up_at=at,
    )


def _edition(n=2, chapter="week-04", approved_at="2026-11-23T18:00:00Z", text=TEXT, carries=()):
    item = CE.new_edition(
        chapter_id=chapter, edition=n, text=text, first_published="2026-09-11", proposed_at="2026-11-22T18:00:00Z", carries=carries
    )
    if approved_at:
        day = approved_at[:10]
        item.update(
            approvals=[CE.approval(at=approved_at, dated_on=day, sha256=item["text_sha256"])],
            approved_at=approved_at,
            revised_on=day,
            signature=CE.signature(n, day),
        )
    return item


def _archival(n=1, chapter="week-04", approved_at="2026-11-23T19:00:00Z", text=ARCHIVAL):
    item = CE.new_archival(chapter_id=chapter, archival_id=n, text=text, proposed_at="2026-11-22T19:00:00Z")
    if approved_at:
        item.update(
            approvals=[CE.approval(at=approved_at, dated_on=approved_at[:10], sha256=item["text_sha256"])],
            approved_at=approved_at,
            approved_on=approved_at[:10],
        )
    return item


def _with_restores(rows):
    """#6193 rehearsal §6: every evidence record here is given its passed restore rehearsal (tests of its ABSENCE live in
    tests/test_edition_publication_6193.py)."""
    rows = list(rows)
    have = {r.get("chapter_id") for r in rows if r.get("record_type") == CE.RESTORE_TYPE}
    for r in list(rows):
        if r.get("record_type") == CE.ORIGINAL_TYPE and r["chapter_id"] not in have:
            rows.append(CE.restore_record(original=r, verified_at=r["backed_up_at"]))
    return rows


def _view(rows, tainted=NEVER, hits=NO_FILTER_HITS):
    return CE.public_view(
        _with_restores(rows), tainted=tainted, private_calls=private_call_check.for_text(private_call_check.CallSet()), filter_hits=hits
    )  # #6199: no private calls


# ── the record ────────────────────────────────────────────────────────────────────────────


def test_the_switch_is_committed_off():
    # Committed LIVE (owner ruling 2026-11-22); the name is historical. ROLLBACK: LIVE = False + site rebuild.
    assert COMMITTED_LIVE is True


def test_the_words_are_the_platforms_and_dated_in_words():
    assert CE.edition_line(2, "2026-11-23", "2026-09-11") == "Second edition, revised 23 November 2026. First published 11 September 2026."
    assert CE.signature(3, "2026-11-23") == "Third edition, revised 23 November 2026 — Average Joe Matt editorial record"
    for bad in (1, 10, True, "2", None, 2.5):
        with pytest.raises(CE.EditionError):
            CE.ordinal(bad)
    assert not any(n in CE.signature(2, "2026-11-23") for n in CC.persona_names())


def test_the_archival_note_says_what_the_page_is_and_nothing_about_what_it_leaves_out():
    note = CE.archival_note("2026-09-11", "2026-11-23")
    assert "first published 11 September 2026" in note and "revised 23 November 2026" in note
    # no count, no wording, no identity of anything removed: the only digits are the two dates, and the note takes no
    # free text from any record (its only inputs are the two days)
    assert re.sub(r"\d{1,2} \w+ 20\d\d", "", note).strip() and not re.search(r"\d", re.sub(r"\d{1,2} \w+ 20\d\d", "", note))
    for word in ("removed", "redacted", "passage", "private", "restricted", "call"):
        assert word not in note.lower()
    assert CE.archival_note.__code__.co_argcount == 3  # #6193 B6: the two days, and the recorded as_of day
    later = CE.archival_note("2026-09-11", "2026-11-23", "2026-10-25")
    assert "as it stood on 25 October 2026" in later and "first edition" not in later
    for word in ("removed", "redacted", "passage", "private", "restricted", "call"):
        assert word not in later.lower()


def test_a_proposal_is_unapproved_unsigned_and_refuses_what_is_malformed():
    item = _edition(approved_at=None)
    assert item["approvals"] == [] and item["signature"] is None and item["revised_on"] is None
    assert item["sk"] == "CHAPTER_EDITION#week-04#02" and item["text_sha256"] == _sha(TEXT) and item["phase"] == "experiment"
    for kw in (dict(chapter_id="04"), dict(edition=1), dict(first_published="11 Sept"), dict(text="short"), dict(carries=["Bad Id"])):
        args = dict(chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11", proposed_at="2026-11-22T18:00:00Z")
        args.update(kw)
        with pytest.raises(CE.EditionError):
            CE.new_edition(**args)


def test_the_evidence_record_must_be_private_and_name_the_row():
    with pytest.raises(CE.EditionError):
        CE.original_record(
            chapter_id="week-04", row_sk="DATE#x", backup_prefix="site/story/", objects=[], backed_up_at="2026-11-22T17:00:00Z"
        )
    with pytest.raises(CE.EditionError):  # no copy of the chronicle row itself
        CE.original_record(
            chapter_id="week-04",
            row_sk="DATE#2026-09-08",
            backup_prefix="backups/chronicle-editions/week-04/x/",
            objects=[{"source": "s3:k", "backup_key": "backups/chronicle-editions/week-04/x/s3/k", "sha256": "b" * 64}],
            backed_up_at="2026-11-22T17:00:00Z",
        )
    assert CE.validate_original(_original())["edition"] == 1


def test_validation_refuses_what_must_not_be_served():
    good = _edition()
    assert CE.validate_edition(good)["edition"] == 2
    for mutate in (
        lambda e: e.update(approvals=[]),
        lambda e: e.update(signature="Second edition, revised 23 November 2026 — Margaret Calloway"),
        lambda e: e.update(text=TEXT + " changed after the proposal"),
        lambda e: e.update(revised_on="2026-09-01"),
        lambda e: e.update(approvals=[{"by": "agent", "at": "2026-11-23T18:00:00Z"}]),
    ):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        with pytest.raises(CE.EditionError):
            CE.validate_edition(bad)


def test_the_markup_of_a_stored_text_is_escaped():
    html = CE.render_html("A line with <script>x()</script> & an ampersand.\n\n> A quotation.")
    assert "<script>" not in html and "&lt;script>" in html and "&amp; an ampersand" in html and "<blockquote>" in html


# ── the public view ───────────────────────────────────────────────────────────────────────


def test_the_public_view_serves_only_the_latest_approved_edition_with_evidence_first():
    rows = [_original(), _edition(2), _edition(3, approved_at=None)]
    (e,) = _view(rows)
    assert set(e) == set(CE.PUBLIC_FIELDS) and e["edition"] == 2 and e["archival"] is None
    assert e["first_published"] == "2026-09-11" and e["revised_on"] == "2026-11-23"
    assert e["approvals"] == [{"by": "owner", "on": "2026-11-23", "via": CC.APPROVED_VIA}]
    assert "proposed_at" not in json.dumps(e) and "backups/" not in json.dumps(e)  # no private key or instant rides along
    later = _edition(3, approved_at="2026-11-24T18:00:00Z", text=TEXT + " Third.")
    assert _view([_original(), _edition(2), later])[0]["edition"] == 3
    assert _view([_edition(2)]) == []  # no evidence record: nothing
    assert _view([_original(at="2026-11-24T00:00:00Z"), _edition(2)]) == []  # backed up only after the approval: nothing


def test_every_gate_withholds_fail_closed():
    rows = [_original(), _edition(2)]
    assert _view(rows, tainted=lambda t: "record holds" in t) == []  # echoes a withheld call
    assert _view(rows, tainted=None) == []  # the record could not be opened
    assert _view(rows, tainted=lambda t: 1 / 0) == []  # the record could not be read
    assert _view(rows, hits=lambda t: [("vice", "x")]) == []  # the content filter

    def unavailable(_t):
        raise RuntimeError("no channel")

    assert _view(rows, hits=unavailable) == []
    staged = _edition(2, text=TEXT + "\n\nWhen I reached Lisa Park she paused, then answered.")
    assert _view([_original(), staged]) == []  # a staged encounter no source holds
    # an older approved edition that passes is served when the newest is withheld
    bad3 = _edition(3, approved_at="2026-11-24T18:00:00Z", text=TEXT + "\n\nWhen I reached Lisa Park she paused, then answered.")
    assert _view([_original(), _edition(2), bad3])[0]["edition"] == 2


def test_the_archival_rendering_is_its_own_approved_text_and_off_by_default():
    rows = [_original(), _edition(2)]
    assert _view(rows)[0]["archival"] is None  # off by default
    assert _view(rows + [_archival(approved_at=None)])[0]["archival"] is None
    a = _view(rows + [_archival()])[0]["archival"]
    assert set(a) == set(CE.PUBLIC_ARCHIVAL_FIELDS) and "approved on its own" in a["body_html"]
    assert a["note"] == CE.archival_note("2026-09-11", "2026-11-23")
    assert _view(rows + [_archival()], tainted=lambda t: "approved on its own" in t)[0]["archival"] is None
    assert _view([_original(), _archival()]) == []  # no served edition: no archival page either


# ── the one writer: the existing MCP tool ─────────────────────────────────────────────────


class _FakeTable:
    def __init__(self):
        self.items: dict = {}
        self.calls: list = []

    def put_item(self, Item, ConditionExpression=None):
        self.calls.append(("put", Item["sk"]))
        k = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = json.loads(json.dumps(Item))

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": json.loads(json.dumps(it))} if it else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        self.calls.append(("update", Key["sk"]))
        it = self.items.get((Key["pk"], Key["sk"]))
        if it is None or len(it.get("approvals") or []) != ExpressionAttributeValues[":zero"]:
            raise RuntimeError("ConditionalCheckFailedException")
        assert "text" not in UpdateExpression.replace("text_sha", "")  # the approval never rewrites the text
        it["approvals"] = it["approvals"] + ExpressionAttributeValues[":a"]
        it["approved_at"] = ExpressionAttributeValues[":at"]
        if "revised_on" in UpdateExpression:
            it.update(revised_on=ExpressionAttributeValues[":d"], signature=ExpressionAttributeValues[":s"])
        else:
            it.update(approved_on=ExpressionAttributeValues[":d"])

    def query(self, **kw):
        prefix = kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1]
        return {"Items": [json.loads(json.dumps(v)) for (p, s), v in sorted(self.items.items()) if s.startswith(prefix)]}

    def delete_item(self, **kw):  # pragma: no cover — must never be called
        raise AssertionError("an edition record is never deleted")


@pytest.fixture
def tool(monkeypatch):
    import mcp.tools_chapter_corrections as t

    table = _FakeTable()
    monkeypatch.setattr(t, "_table_ref", table)
    monkeypatch.setattr(t, "pacific_today", lambda: "2026-11-23")
    monkeypatch.setattr(t, "_tainted", lambda: NEVER)
    monkeypatch.setattr(t, "_published_title", lambda _cid: "A Sample Chapter")  # #6193 B4: the chapter's public heading
    return t, table


def _backed_up(table, chapter="week-04"):
    """The first edition's backup pointer AND its passed restore rehearsal (rehearsal ruling §6)."""
    o = _original(chapter)
    table.put_item(Item=o)
    table.put_item(Item=CE.restore_record(original=o, verified_at="2026-11-22T17:05:00Z"))


def _call(t, **kw):
    return t.tool_manage_chapter_corrections(kw)


def test_propose_backup_approve_is_append_only_and_never_inferred(tool):
    t, table = tool
    r = _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11")
    assert r["stored"] and r["renders"] is False
    dup = _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT + " Other.", first_published="2026-09-11")
    assert "append-only" in dup["error"]
    for not_true in (None, False, "true", 1):
        assert (
            "exactly true"
            in _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=not_true, sha256=_sha(TEXT))["error"]
        )
    assert "required" in _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True)["error"]
    other = _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT + " other bytes"))
    assert "does not bind to these bytes" in other["error"]  # the approval binds to the exact approved bytes
    refused = _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))
    assert "no private backup" in refused["error"]  # the first edition is kept before anything changes
    table.put_item(Item=_original())
    unrehearsed = _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))
    assert "restore rehearsal" in unrehearsed["error"]  # the restore path verified, not merely the files present
    table.put_item(Item=CE.restore_record(original=_original(), verified_at="2026-11-22T17:05:00Z"))
    ok = _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))
    assert ok["approved"] and ok["revised_on"] == "2026-11-23" and ok["renders"] is False  # the switch is off
    assert ok["signature"] == "Second edition, revised 23 November 2026 — Average Joe Matt editorial record"
    assert (
        "already approved" in _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))["error"]
    )
    stored = table.get_item(Key={"pk": CE.pk(), "sk": CE.sk_edition("week-04", 2)})["Item"]
    assert stored["text"] == TEXT and stored["first_published"] == "2026-09-11"
    listing = _call(t, action="list_editions", chapter_id="week-04")
    assert listing["switch_live"] is False and listing["chapters_with_an_edition"] == ["week-04"]
    assert {r["kind"] for r in listing["records"]} == {"edition", "first-edition evidence", "restore rehearsal (passed)"}
    assert all(r["renders"] is False for r in listing["records"])
    assert all(kind in ("put", "update") for kind, _ in table.calls)


def test_the_gates_refuse_at_proposal_and_carried_corrections_must_be_approved(tool, monkeypatch):
    t, table = tool
    monkeypatch.setattr(t, "_tainted", lambda: None)  # the publication record cannot be opened
    r = _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11")
    assert "gates refused" in r["error"] and not table.items
    monkeypatch.setattr(t, "_tainted", lambda: NEVER)
    r = _call(
        t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11", carries=["walk-distance"]
    )
    assert r["stored"]
    _backed_up(table)
    r = _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))
    assert "not approved" in r["error"]


def test_the_archival_rendering_needs_an_approved_edition_and_its_own_approval(tool):
    t, table = tool
    r = _call(t, action="propose_archival", chapter_id="week-04", archival_id=1, text=ARCHIVAL)
    assert r["stored"] and r["renders"] is False
    assert (
        "no approved second edition"
        in _call(t, action="approve_archival", chapter_id="week-04", archival_id=1, approved=True, sha256=_sha(ARCHIVAL))["error"]
    )
    _backed_up(table)
    _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11")
    _call(t, action="approve_edition", chapter_id="week-04", edition=2, approved=True, sha256=_sha(TEXT))
    assert (
        "exactly true"
        in _call(t, action="approve_archival", chapter_id="week-04", archival_id=1, approved="yes", sha256=_sha(ARCHIVAL))["error"]
    )
    ok = _call(t, action="approve_archival", chapter_id="week-04", archival_id=1, approved=True, sha256=_sha(ARCHIVAL))
    assert ok["approved"] and ok["approved_on"] == "2026-11-23"
    rows = [v for v in table.items.values()]
    assert _view(rows)[0]["archival"]["archival_id"] == 1


def test_no_new_tool_and_no_sender_is_reachable_from_the_writer():
    import mcp.registry as reg

    assert "manage_chapter_corrections" in reg.TOOLS
    assert not [k for k in reg.TOOLS if "edition" in k]  # the existing door, actions not a tool
    for path in ("mcp/tools_chapter_corrections.py", "lambdas/content/chapter_editions.py"):
        src = open(os.path.join(_REPO, path), encoding="utf-8").read()
        for forbidden in (
            "send_email",
            "send_raw_email",
            "sesv2",
            '"ses"',
            "lambda_client",
            ".invoke(",
            "chronicle_email_sender",
            "delivered_at",
        ):
            assert forbidden not in src, f"{path} reaches a sender ({forbidden})"


# ── the switch: the route and the exporter ────────────────────────────────────────────────


def _handle(chapters, read_editions):
    rows = [{"date": "2026-09-08", "status": "published", "title": "A week", "week_number": 1, "phase": "experiment"}]
    return chapters.handle_chapters(
        {},
        query=lambda *a, **k: rows,
        read_manifest=lambda: {"posts": [{"date": "2026-09-08", "url": "/journal/posts/week-04/", "title": "A week"}]},
        read_corrections=lambda: [],
        read_editions=read_editions,
        today="2026-11-23",
    )


def test_switch_off_the_route_is_byte_identical_and_never_reads_the_rows(monkeypatch):
    from web import site_api_chapters as chapters

    def boom():
        raise AssertionError("the editions were read with the switch off")

    def same_instant(resp):  # the two calls differ only in the served-at instant the envelope stamps
        return {**resp, "body": re.sub(r'"(generated_at|served_at)": "[^"]*"', r'"\1": "T"', resp["body"])}

    off = same_instant(_handle(chapters, boom))
    monkeypatch.setattr(chapters, "editions_field", lambda *a, **k: {})  # the route as it was before #6193
    before = same_instant(_handle(chapters, boom))
    assert off == before and "editions" not in json.loads(off["body"])


def test_switch_on_the_route_serves_approved_editions_and_says_when_it_cannot_read(monkeypatch):
    from web import site_api_chapters as chapters

    monkeypatch.setattr(CE, "LIVE", True)
    rows = _with_restores([_original(), _edition(2)])
    # the real gates, the suite's neutral content-filter vocabulary (tests/conftest.py)
    assert [e["edition"] for e in chapters.editions_field(lambda: rows, tainted=NEVER)["editions"]] == [2]
    assert chapters.editions_field(lambda: rows, tainted=lambda t: True)["editions"] == []  # a private-call echo withholds

    def down():
        raise RuntimeError("throttled")

    failed = chapters.editions_field(down, tainted=NEVER)
    assert failed["editions"] is None and failed["editions_error"]

    # LIVE on with NO approved edition (#6193 activation): the response differs from LIVE off by exactly one additive
    # key, "editions": [] (and one extra read per request) — nothing else moves.
    def same_instant(resp):
        return re.sub(r'"(generated_at|served_at)": "[^"]*"', r'"\1": "T"', resp["body"])

    # (#6199: the route also reads the private-call record from the raw table, cached 900 s — one more read, no body change)
    monkeypatch.setattr(chapters.private_call_check, "load", lambda _table: private_call_check.CallSet())
    chapters._CALLS_CACHE.update(at=None, calls=None)
    on_empty = json.loads(same_instant(_handle(chapters, lambda: [])))
    monkeypatch.setattr(CE, "LIVE", False)
    off = json.loads(same_instant(_handle(chapters, lambda: [])))
    assert on_empty.pop("editions") == [] and on_empty == off
    monkeypatch.setattr(CE, "LIVE", True)

    # Failure modes of the two reads, as served: an unreadable editions read -> "editions": null + editions_error; an
    # unreadable private-call read -> every edition withheld ("editions": [], 200) and a logged error, never served.
    rows = _with_restores([_original(), _edition(2)])
    assert [e["edition"] for e in chapters.editions_field(lambda: rows, tainted=NEVER)["editions"]] == [2]

    def calls_down(_table):
        raise RuntimeError("throttled")

    monkeypatch.setattr(chapters.private_call_check, "load", calls_down)
    chapters._CALLS_CACHE.update(at=None, calls=None)
    assert chapters.editions_field(lambda: rows, tainted=NEVER)["editions"] == []

    # The documented failure mode (not changed here): with the switch on, an unreadable editions read is a schema error
    # in the snapshot exporter, so that build exits non-zero instead of building without editions.
    import publish_snapshot_chapter_editions as SE

    monkeypatch.setattr(CE, "LIVE", True)
    with pytest.raises(ValueError):
        SE.live(lambda path: failed, lambda m: None)
    with pytest.raises(ValueError):
        SE.live(lambda path: (_ for _ in ()).throw(OSError("503")), lambda m: None)


def _public(published_at="2026-09-11T18:00:44+00:00"):
    return {
        "chapter": [
            {"id": "week-04", "status": "published", "published_at": published_at, "title": "A Sample Chapter"},
            {"id": "week-10", "status": "held"},
        ]
    }


def test_the_exporter_writes_nothing_while_the_switch_is_off(monkeypatch):
    import publish_snapshot_chapter_editions as SE

    monkeypatch.delenv(SE.FIXTURE_ENV, raising=False)
    fixtures = os.path.join(_REPO, "www", "content", "fixtures")
    served = {"editions": _view([_original(), _edition(2)])}
    assert SE.resolve("fixture", fixtures, lambda p: served, print, _public(), None) is None
    assert SE.resolve("live", fixtures, lambda p: served, print, _public(), None) is None  # the repo switch gates live too
    monkeypatch.setenv(SE.FIXTURE_ENV, "1")
    doc = SE.resolve(
        "fixture",
        fixtures,
        lambda p: served,
        print,
        {"chapter": [{"id": "week-06", "status": "published", "published_at": "2026-10-17", "title": "The protein argument"}]},
        {"corrections": [{"chapter_id": "week-06", "id": "sample-walk-distance-2"}]},
    )
    assert [e["chapter_id"] for e in doc["editions"]] == ["week-06"] and "SENTINEL" not in json.dumps(doc)


def test_the_fixture_export_with_the_switch_off_writes_no_editions_file(tmp_path):
    # LIVE is committed True (owner ruling 2026-11-22), and a subprocess does not see the conftest monkeypatch. The child
    # sets the module's switch OFF itself, then runs the real exporter script: no production override is involved.
    env = {k: v for k, v in os.environ.items() if k != "WEB_EDITIONS"}
    child = (
        "import runpy, sys\n"
        f"sys.path[:0] = [{os.path.join(_REPO, 'lambdas')!r}, {os.path.join(_REPO, 'scripts')!r}]\n"
        "from content import chapter_editions as CE\n"
        "CE.LIVE = False\n"
        f"sys.argv = ['publish_snapshot.py', '--mode', 'fixture', '--out', {str(tmp_path / 'snap')!r}]\n"
        f"runpy.run_path({os.path.join(_REPO, 'scripts', 'publish_snapshot.py')!r}, run_name='__main__')\n"
    )
    cp = subprocess.run([sys.executable, "-c", child], cwd=_REPO, env=env, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr[-1500:]
    assert (tmp_path / "snap" / "manifest.json").exists()  # the export really ran
    assert not (tmp_path / "snap" / "chapter_editions.json").exists()
    assert "chapter_editions" not in (tmp_path / "snap" / "manifest.json").read_text()


def test_the_snapshot_validation_holds_each_failing_edition_on_its_own():
    import publish_snapshot_chapter_editions as SE

    corrections = {"corrections": [{"chapter_id": "week-04", "id": "walk-distance"}]}
    view = _view([_original(), _edition(2, carries=["walk-distance"]), _archival()])
    assert SE.validate(SE.compose({"editions": view}), _public(), corrections)["editions"][0]["edition"] == 2
    assert SE.compose({"weeks": []}) is None
    with pytest.raises(ValueError):
        SE.compose({"editions": None, "editions_error": "x"})
    with pytest.raises(ValueError):  # a malformed FILE stops the build
        SE.validate(SE.compose({"editions": [dict(view[0], extra=1)]}), _public(), corrections)
    for mutate, public, corr in (
        (lambda e: None, _public("2026-09-12T00:00:00+00:00"), corrections),  # a first-published day that is not the chapter's
        (lambda e: e.update(chapter_id="week-10"), _public(), corrections),  # a held chapter has no page
        (lambda e: None, _public(), {"corrections": []}),  # a carried correction that is not approved
        (lambda e: e.update(body_html=""), _public(), corrections),  # a wire-emptied body never renders blank
        (lambda e: e.update(body_html=e["body_html"].replace("nothing more", "nothing else")), _public(), corrections),  # bytes != approved
        (lambda e: e.update(text=e["text"] + " x"), _public(), corrections),  # text != its approved hash
        (lambda e: e.update(edition_line="Second edition, revised whenever."), _public(), corrections),
        (
            lambda e: e.update(signature=e["signature"].replace("Average Joe Matt editorial record", "Margaret Calloway")),
            _public(),
            corrections,
        ),
    ):
        bad = json.loads(json.dumps(view))
        mutate(bad[0])
        other = dict(json.loads(json.dumps(view))[0], chapter_id="week-05", carries=[])
        pub = {
            "chapter": public["chapter"]
            + [{"id": "week-05", "status": "published", "published_at": "2026-09-11T00:00:00+00:00", "title": "A Sample Chapter"}]
        }
        held: list = []
        out = SE.validate(SE.compose({"editions": [bad[0], other]}), pub, corr, log=lambda m: None, held=held)
        assert [e["chapter_id"] for e in out["editions"]] == ["week-05"], "one held edition never blocks an unrelated verified one"
        assert held == [bad[0]["chapter_id"]]
    bad = json.loads(json.dumps(view))
    bad[0]["archival"]["note"] += " Two passages were removed."
    held = []
    out = SE.validate(SE.compose({"editions": bad}), _public(), corrections, log=lambda m: None, held=held)
    assert out["editions"][0]["archival"] is None and held == ["week-04#archival"]  # only the archival page is held


def test_a_deployed_page_verifies_against_the_approved_bytes_and_permitted_presentation_only():
    import chronicle_edition_verify as V

    body = CE.render_html(CE.presentation(TEXT)["body"])  # #6193 B4: the body without the title and summary lines
    figure = '<figure class="evidence" data-evidence="weight"><figcaption>Evidence</figcaption><p>A chart note.</p></figure>'
    placed = body.replace("</p>\n<p>", "</p>" + figure + "<p>", 1)

    def page(b, line=CE.edition_line(2, "2026-11-23", "2026-09-11")):
        return (
            f'<h1>A Sample Chapter</h1><p class="dek">A sample summary line for a test, for layout only.</p>'
            f"<p data-edition-line><b>{line}</b></p>"
            f'<article><div data-published-body>{b}</div></article><link rel="canonical" href="x">'
        )

    slots = {"dek": "A sample summary line for a test, for layout only.", "h1": "A Sample Chapter"}
    assert CE.verify_page(page(placed), TEXT, _sha(TEXT), **slots) == []  # an evidence figure between paragraphs is permitted
    assert CE.verify_page(page(placed.replace("nothing more", "nothing else")), TEXT, _sha(TEXT), **slots)  # one word changed
    assert CE.verify_page(page(placed), TEXT, _sha(TEXT + "x"), **slots)  # not the approved hash
    assert CE.verify_page(page(placed), TEXT, _sha(TEXT), dek="A different summary.", h1=slots["h1"])  # #6193 B4: wrong slot
    view = _view([_original(), _edition(2)])
    rss = '<guid isPermaLink="true">https://s/journal/posts/week-04/</guid>'
    site = {
        "https://s/api/chapters": json.dumps({"editions": view, "weeks": [{"url": "/journal/posts/week-04/"}]}),
        "https://s/story/week-04/": page(placed),
        "https://s/rss.xml": rss,
    }
    assert V.verify(site.__getitem__, "week-04", _sha(TEXT), base="https://s") == []
    assert V.verify(site.__getitem__, "week-04", _sha(TEXT + " other"), base="https://s")  # not the approved bytes
    site["https://s/rss.xml"] = rss * 2
    assert any("2 time(s)" in p for p in V.verify(site.__getitem__, "week-04", _sha(TEXT), base="https://s"))


def test_the_preview_renders_in_memory_records_that_never_claim_a_real_approval_date():
    import chronicle_edition_preview as P

    rows = P.preview_records("week-04", TEXT, "2026-09-11", ARCHIVAL, "2026-11-30")
    (e,) = _view(rows)
    assert e["edition_line"].startswith("Second edition, revised 30 November 2026") and e["archival"] is not None
    src = open(os.path.join(_REPO, "scripts", "chronicle_edition_preview.py"), encoding="utf-8").read()
    for forbidden in ("put_item", "update_item", "put_object", "safe_sync", "s3 sync", "create_invalidation", "deploy/"):
        assert forbidden not in src, forbidden


# ── the backup script ─────────────────────────────────────────────────────────────────────


class _FakeS3:
    def __init__(self, objects, corrupt=False):
        self.objects = dict(objects)
        self.puts: list = []
        self.corrupt = corrupt

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        body = self.objects[Key]
        return {"Body": io.BytesIO(body + (b"x" if self.corrupt and Key.startswith("backups/") else b""))}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **kw):
        assert IfNoneMatch == "*" and Key.startswith(CE.BACKUP_ROOT)  # write-once, private
        if Key in self.objects:
            raise RuntimeError("PreconditionFailed")
        self.puts.append(Key)
        self.objects[Key] = Body


def _row():
    return {
        "pk": CE.pk(),
        "sk": "DATE#2026-09-08",
        "status": "published",
        "draft_journal_post_key": "generated/journal/posts/week-04/index.html",
    }


def test_the_backup_is_private_write_once_read_back_then_pointed_to():
    import chronicle_edition_backup as B

    table = _FakeTable()
    table.items[(CE.pk(), "DATE#2026-09-08")] = _row()
    s3 = _FakeS3({"generated/journal/posts/week-04/index.html": b"<p>first edition</p>", "site/story/week-04/index.html": b"<p>v9</p>"})
    with pytest.raises(B.Refused):  # page address and chapter differ
        B.plan("week-05", "DATE#2026-09-08", s3, table, now="2026-11-22T17:00:00Z")
    p = B.plan("week-04", "DATE#2026-09-08", s3, table, now="2026-11-22T17:00:00Z")
    assert [o["source"] for o in p["objects"]] == [
        "ddb:DATE#2026-09-08",
        "s3:generated/journal/posts/week-04/index.html",
        "s3:site/story/week-04/index.html",
    ]
    assert not s3.puts and not table.calls  # the plan is reads only
    item = B.apply(p, s3, table, log=lambda m: None)
    assert all(k.startswith("backups/chronicle-editions/week-04/20261122T170000Z/") for k in s3.puts) and len(s3.puts) == 3
    assert s3.objects["generated/journal/posts/week-04/index.html"] == b"<p>first edition</p>"  # the original is untouched
    assert CE.validate_original(item) and table.items[(CE.pk(), CE.sk_original("week-04"))]["objects"][1]["sha256"] == _sha(
        "<p>first edition</p>"
    )
    with pytest.raises(B.Refused):  # once per chapter
        B.plan("week-04", "DATE#2026-09-08", s3, table, now="2026-11-22T18:00:00Z")


def test_a_backup_that_does_not_read_back_equal_writes_no_pointer():
    import chronicle_edition_backup as B

    table = _FakeTable()
    table.items[(CE.pk(), "DATE#2026-09-08")] = _row()
    s3 = _FakeS3({"generated/journal/posts/week-04/index.html": b"<p>first edition</p>"}, corrupt=True)
    p = B.plan("week-04", "DATE#2026-09-08", s3, table, now="2026-11-22T17:00:00Z")
    with pytest.raises(B.Unverified):
        B.apply(p, s3, table, log=lambda m: None)
    assert (CE.pk(), CE.sk_original("week-04")) not in table.items


# ── feeds and mail: an edition changes nothing ────────────────────────────────────────────


def _feed(monkeypatch, tmp_path, chapters):
    import v4_build_rss

    # utc-exempt(#6193): the feed builder's freshness guard compares a post date with its own UTC clock, not a Pacific day
    dateline = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posts = {"posts": [{"date": dateline, "title": "A week", "url": "/journal/posts/week-04/", "excerpt": "The first edition's excerpt."}]}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    monkeypatch.setattr(
        v4_build_rss, "urlopen", lambda url, timeout=0: _Resp(json.dumps(chapters if url == v4_build_rss.CHAPTERS_SRC else posts).encode())
    )
    monkeypatch.setattr(v4_build_rss, "_blog_posts", lambda: [])
    out = tmp_path / f"rss-{len(list(tmp_path.iterdir()))}.xml"
    monkeypatch.setattr(v4_build_rss, "OUT", out)
    monkeypatch.setattr(v4_build_rss, "OUT_ALIAS", tmp_path / "feed.xml")
    assert v4_build_rss.main() == 0
    return re.sub(r"<lastBuildDate>[^<]*</lastBuildDate>", "", out.read_text(encoding="utf-8"))


def test_an_approved_edition_changes_no_feed_item_date_or_guid(monkeypatch, tmp_path):
    weeks = {"weeks": [{"url": "/journal/posts/week-04/", "published_at": "2026-09-11T18:00:44+00:00"}], "corrections": []}
    before = _feed(monkeypatch, tmp_path, weeks)
    with_edition = _feed(monkeypatch, tmp_path, {**weeks, "editions": _view([_original(), _edition(2), _archival()])})
    # #6193 B4: ONLY the item's description changes — to the edition's own summary; title, link, guid, pubDate, count stay
    desc = re.compile(r"<description>[^<]*</description>")
    assert desc.sub("", with_edition) == desc.sub("", before)
    assert "<description>A sample summary line for a test, for layout only.</description>" in with_edition
    assert before.count("<item>") == 1 and "Fri, 11 Sep 2026 18:00:44 +0000" in before


def test_an_approved_edition_is_never_selected_for_a_subscriber_send(monkeypatch):
    cel = importlib.import_module("chronicle_email_sender_lambda")
    from decimal import Decimal

    class _RangeTable:
        """Honours the sender's real key condition: pk = :pk AND sk BETWEEN :s AND :e, newest first, Limit."""

        def __init__(self, items):
            self.items = items

        def query(self, **kw):
            v = kw["ExpressionAttributeValues"]
            assert kw["KeyConditionExpression"] == "pk = :pk AND sk BETWEEN :s AND :e"
            hits = sorted(
                (i for i in self.items if i["pk"] == v[":pk"] and v[":s"] <= i["sk"] <= v[":e"]), key=lambda i: i["sk"], reverse=True
            )
            return {"Items": hits[: kw.get("Limit", len(hits))]}

    monkeypatch.setattr(cel, "pacific_now", lambda: datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc))
    delivered = {
        "pk": cel.CHRONICLE_PK,
        "sk": "DATE#2026-11-20",
        "status": "published",
        "phase": "experiment",
        "delivered_at": "2026-11-20T18:00:00Z",
        "sent_to_count": Decimal("3"),
    }
    pk = cel.CHRONICLE_PK
    editions = [{**r, "pk": pk} for r in (_original(), _edition(2), _archival())]
    monkeypatch.setattr(cel, "table", _RangeTable([delivered]))
    before = cel._get_this_weeks_installment()
    monkeypatch.setattr(cel, "table", _RangeTable([delivered] + editions))
    after = cel._get_this_weeks_installment()
    assert before is None and after is None  # the delivered week stays delivered; the edition rows are never a candidate
    assert all(not e["sk"].startswith("DATE#") for e in editions)  # outside every DATE# range the sender reads

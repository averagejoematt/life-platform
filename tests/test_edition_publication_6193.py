"""tests/test_edition_publication_6193.py — the publication blockers a read-only rehearsal found in second editions (#6193).

Synthetic fixtures only: no chapter prose, no private call, no private record key.

  * B1 — the backup derives a chapter's journal page from its page id when the row records none, and only when that
    page exists and carries the row's title;
  * rehearsal ruling §6 — the restore path is rehearsed (every object read back, the row rebuilt to the captured bytes)
    and recorded; no edition is approved or served without it;
  * B4 — an edition's title line and summary line are its presentation fields: a deterministic, invertible split; the
    summary is the chapter's summary on every surface; a title line that is not the published title is refused;
  * B6 — the archival note names a recorded as_of day for a later rewrite and never calls it the first edition;
  * B7 — the owner withdraws ONE edition or rendering by an appended, dated record; that chapter serves its first edition
    again, the others are untouched, nothing earlier is revived, and the verifier says "withdrawn";
  * B9 — an edition that points at its first-edition address is held while no archival rendering is served;
  * B3 — an attempt count passes the truth gate ONLY inside the exact, quoted, pinned own-words statement.
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content import chapter_editions as CE, story_checks  # noqa: E402
from test_chapter_editions_6193 import (  # noqa: E402 — the same synthetic records and fakes
    TEXT,
    _archival,
    _call,
    _edition,
    _FakeS3,
    _FakeTable,
    _original,
    _sha,
    _view,
)


@pytest.fixture
def tool(monkeypatch):
    """The real tool over the in-memory table (the same set-up as tests/test_chapter_editions_6193.py)."""
    import mcp.tools_chapter_corrections as t

    table = _FakeTable()
    monkeypatch.setattr(t, "_table_ref", table)
    monkeypatch.setattr(t, "pacific_today", lambda: "2026-11-23")
    monkeypatch.setattr(t, "_tainted", lambda: lambda _t: False)
    monkeypatch.setattr(t, "_published_title", lambda _cid: "A Sample Chapter")
    return t, table


TITLE, SUMMARY = "A Sample Chapter", "A sample summary line for a test, for layout only."


# ── B1 + rehearsal §6: the backup and its restore rehearsal ───────────────────────────────────


def _legacy_row(title=TITLE):
    """A row written before draft_journal_post_key existed."""
    return {"pk": CE.pk(), "sk": "DATE#2026-01-01", "status": "published", "title": title}


def _page(title):
    return f"<html><head><title>{title} — The Measured Life</title></head><body><p>first edition</p></body></html>".encode()


def test_b1_a_row_without_a_recorded_page_derives_it_from_the_page_id_only_when_it_exists_and_matches():
    import chronicle_edition_backup as B

    table = _FakeTable()
    table.items[(CE.pk(), "DATE#2026-01-01")] = _legacy_row()
    s3 = _FakeS3({"generated/journal/posts/week-01/index.html": _page(TITLE)})
    p = B.plan("week-01", "DATE#2026-01-01", s3, table, now="2026-11-22T17:00:00Z")
    assert p["journal_key_derived"] and [o["source"] for o in p["objects"]] == [
        "ddb:DATE#2026-01-01",
        "s3:generated/journal/posts/week-01/index.html",
    ]
    with pytest.raises(B.Refused, match="does not exist"):  # no page at the derived address: refused
        B.plan("week-02", "DATE#2026-01-01", s3, table, now="2026-11-22T17:00:00Z")
    s3.objects["generated/journal/posts/week-03/index.html"] = _page("Another Chapter")
    with pytest.raises(B.Refused, match="not the row's"):  # a page of another chapter: refused
        B.plan("week-03", "DATE#2026-01-01", s3, table, now="2026-11-22T17:00:00Z")
    assert not s3.puts and not table.calls  # the plan reads only


def test_the_restore_is_rehearsed_and_recorded_and_a_corrupt_backup_records_nothing():
    import chronicle_edition_backup as B

    table = _FakeTable()
    table.items[(CE.pk(), "DATE#2026-01-01")] = _legacy_row()
    s3 = _FakeS3({"generated/journal/posts/week-01/index.html": _page(TITLE)})
    with pytest.raises(B.Refused):  # nothing to rehearse before the backup
        B.verify_restore("week-01", s3, table)
    p = B.plan("week-01", "DATE#2026-01-01", s3, table, now="2026-11-22T17:00:00Z")
    pointer = B.apply(p, s3, table, log=lambda m: None)
    _ptr, problems, commands = B.verify_restore("week-01", s3, table)
    assert problems == [] and any("dynamodb put-item" in c for c in commands) and any(c.startswith("aws s3 cp s3://") for c in commands)
    item = B.record_restore("week-01", s3, table, now="2026-11-22T17:01:00Z", log=lambda m: None)
    assert CE.validate_restore(item, pointer) and item["row_rebuilt"] is True
    # a backed-up object that no longer matches its captured sha256: the rehearsal fails and nothing is recorded
    table2 = _FakeTable()
    table2.items[(CE.pk(), "DATE#2026-01-01")] = _legacy_row()
    s3b = _FakeS3({"generated/journal/posts/week-01/index.html": _page(TITLE)})
    B.apply(B.plan("week-01", "DATE#2026-01-01", s3b, table2, now="2026-11-22T17:00:00Z"), s3b, table2, log=lambda m: None)
    s3b.corrupt = True
    with pytest.raises(B.Unverified):
        B.record_restore("week-01", s3b, table2, now="2026-11-22T17:01:00Z", log=lambda m: None)
    assert (CE.pk(), CE.sk_restore("week-01")) not in table2.items


def test_the_row_rebuilds_to_exactly_the_captured_item():
    from decimal import Decimal

    import chronicle_edition_backup as B
    from chronicle_revision_apply import ddb_json

    row = {"pk": CE.pk(), "sk": "DATE#2026-01-01", "n": Decimal("3"), "nested": {"a": [Decimal("1.5"), "x", True, None]}}
    captured = ddb_json(row).encode("utf-8")
    assert B.rebuild_row(captured) == row and ddb_json(B.rebuild_row(captured)).encode("utf-8") == captured


def test_no_edition_serves_without_a_passed_restore_rehearsal():
    rows = [_original(), _edition(2)]
    assert CE.public_view(rows, tainted=lambda t: False, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda t: []) == []
    assert [e["edition"] for e in _view(rows)] == [2]
    other = dict(CE.restore_record(original=_original(), verified_at="2026-11-22T17:05:00Z"))
    other["objects"] = [{"backup_key": "backups/chronicle-editions/week-04/x", "sha256": "b" * 64}]
    with pytest.raises(CE.EditionError):  # a rehearsal of some other backup is not this one's
        CE.validate_restore(other, _original())


# ── B4: the presentation fields ───────────────────────────────────────────────────────────────


def test_b4_the_split_is_deterministic_and_rebuilds_the_approved_bytes():
    p = CE.presentation(TEXT)
    assert (p["title"], p["summary"]) == (TITLE, SUMMARY) and TITLE not in p["body"] and SUMMARY not in p["body"]
    assert CE.compose_text(p["title"], p["summary"], p["body"]) == TEXT and CE.text_sha256(CE.compose_text(**p)) == _sha(TEXT)
    for bad in (
        TEXT.split("\n\n", 1)[1],  # no title line
        TEXT.replace(f"*{SUMMARY}*\n\n", ""),  # no summary line
        TEXT.replace('"A Sample Chapter"\n\n', '"A Sample Chapter"\n\n\n'),  # not the canonical head: could not be rebuilt
        TEXT.replace('"A Sample Chapter"', "“A Sample Chapter”"),
    ):
        with pytest.raises(CE.EditionError):
            CE.new_edition(chapter_id="week-04", edition=2, text=bad, first_published="2026-09-11", proposed_at="2026-11-22T18:00:00Z")


def test_b4_the_served_edition_carries_its_title_and_summary_and_a_body_without_them():
    (e,) = _view([_original(), _edition(2)])
    assert (e["title"], e["summary"]) == (TITLE, SUMMARY) and e["text"] == TEXT
    assert SUMMARY not in e["body_html"] and TITLE not in e["body_html"]
    assert e["body_html"] == CE.render_html(CE.presentation(TEXT)["body"])
    assert dict(CE.PERMITTED_PRESENTATION).keys() >= {"title-line", "edition-summary"}


def test_b4_an_edition_never_retitles_a_chapter(tool, monkeypatch):
    t, table = tool
    assert CE.title_problem(TEXT, TITLE) is None
    assert "cannot retitle" in CE.title_problem(TEXT, "Another Title")
    monkeypatch.setattr(t, "_published_title", lambda _cid: "Another Title")
    r = _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11")
    assert "cannot retitle" in r["error"] and not table.items
    monkeypatch.setattr(t, "_published_title", lambda _cid: None)  # the published title cannot be read: refused, fail closed
    r = _call(t, action="propose_edition", chapter_id="week-04", edition=2, text=TEXT, first_published="2026-09-11")
    assert "could not be read" in r["error"] and not table.items


def test_b4_the_build_holds_an_edition_whose_title_is_not_the_published_title():
    import publish_snapshot_chapter_editions as SE

    view = _view([_original(), _edition(2)])
    pub = lambda title: {
        "chapter": [{"id": "week-04", "status": "published", "published_at": "2026-09-11T18:00:00+00:00", "title": title}]
    }  # noqa: E731
    assert len(SE.validate(SE.compose({"editions": view}), pub(TITLE), None)["editions"]) == 1
    held: list = []
    assert SE.validate(SE.compose({"editions": view}), pub("Renamed"), None, log=lambda m: None, held=held)["editions"] == []
    assert held == ["week-04"]
    moved = json.loads(json.dumps(view))
    moved[0]["summary"] = "A summary the text does not carry."
    held = []
    assert SE.validate(SE.compose({"editions": moved}), pub(TITLE), None, log=lambda m: None, held=held)["editions"] == []


def test_b4_the_verifier_rebuilds_the_approved_text_from_the_deployed_slots():
    body = CE.render_html(CE.presentation(TEXT)["body"])
    page = f'<h1>{TITLE}</h1><p class="dek">{SUMMARY}</p><article><div data-published-body>{body}</div></article>'
    assert CE.verify_page(page, TEXT, _sha(TEXT), dek=SUMMARY, h1=TITLE) == []
    wrong = CE.verify_page(page, TEXT, _sha(TEXT), dek="An older summary of the first edition.", h1=TITLE)
    assert any("header summary" in p for p in wrong) and any("rebuilt" in p for p in wrong)
    assert any("heading" in p for p in CE.verify_page(page, TEXT, _sha(TEXT), dek=SUMMARY, h1="Renamed"))


# ── B6: the archival rendering's day ──────────────────────────────────────────────────────────


def test_b6_an_archival_as_of_names_its_day_and_must_lie_between_publication_and_revision():
    a = _archival()
    a["as_of"] = "2026-10-25"
    (e,) = _view([_original(), _edition(2), a])
    assert e["archival"]["as_of"] == "2026-10-25" and "as it stood on 25 October 2026" in e["archival"]["note"]
    assert "first edition" not in e["archival"]["note"]
    late = dict(a, as_of="2026-12-31")
    (e,) = _view([_original(), _edition(2), late])
    assert e["archival"] is None  # an as_of after the revision is not a historical text of this edition: held
    with pytest.raises(CE.EditionError):
        CE.new_archival(chapter_id="week-04", archival_id=1, text=TEXT, proposed_at="2026-11-22T19:00:00Z", as_of="25 Oct")


# ── B9: no edition advertises an archival page that does not exist ────────────────────────────

POINTING = TEXT + "\n\n*An archival rendering is at /story/week-04/first-edition/.*"


def test_b9_an_edition_pointing_at_its_archive_is_held_without_one_and_served_with_one():
    assert CE.references_archive(POINTING, "week-04") and not CE.references_archive(POINTING, "week-05")
    assert _view([_original(), _edition(2, text=POINTING)]) == []
    (e,) = _view([_original(), _edition(2, text=POINTING), _archival()])
    assert e["archival"] is not None
    assert [x["edition"] for x in _view([_original(), _edition(2, text=TEXT)])] == [2]  # no pointer: no archive needed


def test_b9_the_build_holds_the_edition_when_its_archival_rendering_is_held():
    import publish_snapshot_chapter_editions as SE

    view = json.loads(json.dumps(_view([_original(), _edition(2, text=POINTING), _archival()])))
    view[0]["archival"]["note"] += " Extra words."  # the archival page is held at build ...
    pub = {"chapter": [{"id": "week-04", "status": "published", "published_at": "2026-09-11T18:00:00+00:00", "title": TITLE}]}
    held: list = []
    out = SE.validate(SE.compose({"editions": view}), pub, None, log=lambda m: None, held=held)
    assert out["editions"] == [] and held == ["week-04#archival", "week-04"]  # ... so the edition that points at it is too


# ── B7: withdrawal ────────────────────────────────────────────────────────────────────────────


def _withdrawal(chapter="week-04", kind="edition", n=2):
    return CE.new_withdrawal(chapter_id=chapter, kind=kind, number=n, at="2026-11-24T09:00:00Z", dated_on="2026-11-24")


def test_b7_a_withdrawn_edition_serves_its_first_edition_and_leaves_other_chapters_alone():
    base = [_original(), _edition(2), _original("week-05"), _edition(2, chapter="week-05")]
    assert [e["chapter_id"] for e in _view(base)] == ["week-04", "week-05"]
    assert [e["chapter_id"] for e in _view(base + [_withdrawal()])] == ["week-05"]
    # withdrawing edition 3 never revives the edition 2 it replaced; a later approved edition 4 serves
    three = base + [_edition(3, approved_at="2026-11-24T10:00:00Z"), _withdrawal(n=3)]
    assert [e["chapter_id"] for e in _view(three)] == ["week-05"]
    assert {e["chapter_id"]: e["edition"] for e in _view(three + [_edition(4, approved_at="2026-11-25T10:00:00Z")])}["week-04"] == 4
    # an archival rendering withdrawn: the edition stays, its archival page goes
    (e,) = [x for x in _view(base + [_archival(), _withdrawal(kind="archival", n=1)]) if x["chapter_id"] == "week-04"]
    assert e["archival"] is None
    assert CE.public_withdrawals([_withdrawal()]) == [
        {"chapter_id": "week-04", "kind": "edition", "number": 2, "withdrawn_on": "2026-11-24"}
    ]


def test_b7_the_tool_withdraws_only_on_his_explicit_word_and_only_once(tool):
    t, table = tool
    for not_true in (None, False, "true", 1):
        assert "exactly true" in _call(t, action="withdraw_edition", chapter_id="week-04", edition=2, approved=not_true)["error"]
    assert "no approved edition" in _call(t, action="withdraw_edition", chapter_id="week-04", edition=2, approved=True)["error"]
    table.put_item(Item=_edition(2))
    r = _call(t, action="withdraw_edition", chapter_id="week-04", edition=2, approved=True, note="a test")
    assert r["withdrawn"] and r["withdrawn_on"] == "2026-11-23"
    assert "append-only" in _call(t, action="withdraw_edition", chapter_id="week-04", edition=2, approved=True)["error"]
    stored = table.get_item(Key={"pk": CE.pk(), "sk": CE.sk_withdrawal("week-04", "edition", 2)})["Item"]
    assert CE.validate_withdrawal(stored)["number"] == 2 and stored["approvals"][0]["by"] == CE.APPROVER
    assert table.get_item(Key={"pk": CE.pk(), "sk": CE.sk_edition("week-04", 2)})["Item"]["approvals"]  # nothing edited
    assert all(kind in ("put", "update") for kind, _ in table.calls)


def test_b7_the_verifier_says_withdrawn():
    import chronicle_edition_verify as V

    site = {
        "https://s/api/chapters": json.dumps({"editions": [], "edition_withdrawals": CE.public_withdrawals([_withdrawal()]), "weeks": []}),
        "https://s/story/week-04/": "<h1>x</h1>",
    }
    (p,) = V.verify(site.__getitem__, "week-04", _sha(TEXT), base="https://s")
    assert "WITHDRAWN" in p and "first edition" in p
    site["https://s/story/week-04/"] = "<p data-edition-line><b>Second edition</b></p>"
    assert any("still prints an edition line" in p for p in V.verify(site.__getitem__, "week-04", _sha(TEXT), base="https://s"))


# ── B3: his own approved statement, and nothing else ──────────────────────────────────────────


def test_b3_a_count_passes_only_inside_the_exact_quoted_pinned_statement():
    (q,) = story_checks.OWN_WORDS_COUNT_QUOTES
    assert story_checks.reader_surface(f'He wrote that day: "{q}" The week went on.') == []
    assert story_checks.reader_surface(f"He wrote that day: “{q}”") == []
    for refused in (
        f"He wrote that day: {q}",  # not quoted
        f'He wrote that day: "{q.replace("16th", "17th")}"',  # not his exact words
        f'He wrote that day: "{q}" It was his 16th reset.',  # the count again, outside the quotation
        "It was his sixteenth attempt.",  # a count of the writer's own
        "After a previous attempt that stalled, he began again.",  # a reference, as before
    ):
        assert story_checks.reader_surface(refused), refused


def test_b3_the_python_exception_is_the_sites_pinned_line_and_the_prologue_is_in_its_scope():
    import check_www_build as W

    pins = W.own_words_pins()
    assert pins["beginning"]["text"] == story_checks.OWN_WORDS_COUNT_QUOTES[0]  # one statement, pinned twice, equal
    assert "/story/week-01/" in pins["beginning"]["scope"] and "/story/moments/" in pins["beginning"]["scope"]
    from content import elena_canon

    assert elena_canon.ELENA_CANON_VERSION == "1.2.0"
    assert any("quoted exactly" in rule and "never a total inferred" in rule for rule in elena_canon.NEVER)


def test_the_withdrawal_and_restore_records_never_reach_a_sender():
    for path in ("scripts/chronicle_edition_backup.py",):
        src = open(os.path.join(_REPO, path), encoding="utf-8").read()
        for forbidden in ("send_email", "sesv2", ".invoke(", "delivered_at", "delete_item", "delete_object"):
            assert forbidden not in src, f"{path}: {forbidden}"
    assert re.search(r"--verify-restore", open(os.path.join(_REPO, "scripts", "chronicle_edition_backup.py"), encoding="utf-8").read())


# ── rehearsal ruling §4: a correction beside the passage it concerns ──────────────────────────

ARCH_TEXT = "A synthetic archive. Day 9 was a sample day of the test, with words.\n\nA second paragraph of the archive, for layout only."


def _anchor(correction_id="walk", passage="Day 9 was a sample day", approved=True):
    a = CE.new_anchor(chapter_id="week-04", correction_id=correction_id, passage=passage, proposed_at="2026-11-22T20:00:00Z")
    if approved:
        a["approvals"] = [{"by": CE.APPROVER, "at": "2026-11-22T20:05:00Z", "on": "2026-11-22", "via": "x", "note": ""}]
    return a


def test_an_approved_anchor_rides_on_the_archival_rendering_only_when_its_passage_is_there_once():
    rows = [_original(), _edition(2), _archival(text=ARCH_TEXT)]
    (e,) = _view(
        rows + [_anchor(), _anchor("other", "not anywhere in the archive", True), _anchor("unapproved", "A second paragraph", False)]
    )
    assert e["archival"]["anchors"] == [{"correction_id": "walk", "passage": "Day 9 was a sample day"}]
    with pytest.raises(CE.EditionError):
        _anchor(passage="short")
    # the verifier ignores a correction block placed between paragraphs (permitted presentation)
    page = (
        "<article><div data-archival-body><div data-published-body><p>A synthetic archive. Day 9 was a sample day of the test, "
        'with words.</p><aside class="chapter-correction" data-correction="walk"><p>Correction</p></aside>'
        "<p>A second paragraph of the archive, for layout only.</p></div></div></article>"
    )
    assert CE.verify_archival_page(page, ARCH_TEXT) == []
    assert "correction-beside-passage" in dict(CE.PERMITTED_PRESENTATION)


def test_the_build_drops_an_anchor_whose_correction_is_not_approved():
    import publish_snapshot_chapter_editions as SE

    view = _view([_original(), _edition(2), _archival(text=ARCH_TEXT), _anchor()])
    pub = {"chapter": [{"id": "week-04", "status": "published", "published_at": "2026-09-11T18:00:00+00:00", "title": TITLE}]}
    keep = SE.validate(SE.compose({"editions": view}), pub, {"corrections": [{"chapter_id": "week-04", "id": "walk"}]}, log=lambda m: None)
    assert keep["editions"][0]["archival"]["anchors"][0]["correction_id"] == "walk"
    drop = SE.validate(SE.compose({"editions": view}), pub, {"corrections": []}, log=lambda m: None)
    assert drop["editions"][0]["archival"]["anchors"] == []  # the archival page stays; only the placement goes


def test_the_tool_places_an_anchor_only_on_his_word_for_an_approved_correction_in_the_archive(tool, monkeypatch):
    t, table = tool
    r = _call(t, action="propose_anchor", chapter_id="week-04", correction_id="walk", passage="Day 9 was a sample day")
    assert r["stored"] and r["approved"] is False
    assert "exactly true" in _call(t, action="approve_anchor", chapter_id="week-04", correction_id="walk", approved="yes")["error"]
    monkeypatch.setattr(t.CC, "public_view", lambda rows: [])
    assert (
        "not an approved correction"
        in _call(t, action="approve_anchor", chapter_id="week-04", correction_id="walk", approved=True)["error"]
    )
    monkeypatch.setattr(t.CC, "public_view", lambda rows: [{"chapter_id": "week-04", "id": "walk"}])
    assert "carries this passage" in _call(t, action="approve_anchor", chapter_id="week-04", correction_id="walk", approved=True)["error"]
    table.put_item(Item=_archival(text=ARCH_TEXT, approved_at=None))
    ok = _call(t, action="approve_anchor", chapter_id="week-04", correction_id="walk", approved=True)
    assert ok["approved"] is True
    assert "already approved" in _call(t, action="approve_anchor", chapter_id="week-04", correction_id="walk", approved=True)["error"]


# ── rehearsal ruling §9: the rehearsal's own checks ───────────────────────────────────────────


def test_the_rehearsal_withdrawal_simulation_and_table():
    import chronicle_edition_rehearsal as R

    rows = {
        "week-04": R.records({"chapter": "week-04", "carries": []}, TEXT, None, "2026-09-11", "2026-11-23"),
        "week-05": R.records({"chapter": "week-05", "carries": []}, TEXT, None, "2026-09-18", "2026-11-23"),
    }
    assert R.simulate_withdrawal(rows, "week-04", "2026-11-23") is None  # withdrawn alone, others kept, re-approval serves
    assert "not served" in R.simulate_withdrawal(
        {"week-04": [r for r in rows["week-04"] if r["record_type"] != CE.RESTORE_TYPE]}, "week-04", "2026-11-23"
    )
    t = R.table(
        {"week-04": {**{c: None for c in R.CHECKS}, "archive": "n/a"}, "week-05": {**{c: None for c in R.CHECKS}, "title": "renamed"}}
    )
    assert "| week-04 | PASS |" in t and "| week-05 | BLOCKED |" in t and "BLOCKED: renamed" in t
    src = open(os.path.join(_REPO, "scripts", "chronicle_edition_rehearsal.py"), encoding="utf-8").read()
    for forbidden in ("put_item", "update_item", "put_object", "safe_sync", "create_invalidation", "--apply"):
        assert forbidden not in src, forbidden


def test_the_rehearsal_surface_check_finds_a_first_edition_summary_left_behind(tmp_path):
    import chronicle_edition_rehearsal as R

    (tmp_path / "story" / "week-04").mkdir(parents=True)
    (tmp_path / "story" / "index.html").write_text("<p>The edition's own summary line.</p>")
    page = '<meta property="og:description" content="The edition\'s own summary line."><p class="dek">The edition\'s own summary line.</p>'
    (tmp_path / "story" / "week-04" / "index.html").write_text(page)
    assert R.surfaces(str(tmp_path), "week-04", "The edition's own summary line.", "An older summary of the first edition.") is None
    (tmp_path / "story" / "moments").mkdir()
    (tmp_path / "story" / "moments" / "index.html").write_text("<p>An older summary of the first edition.</p>")
    assert "still shows the first edition's summary" in R.surfaces(
        str(tmp_path), "week-04", "The edition's own summary line.", "An older summary of the first edition."
    )

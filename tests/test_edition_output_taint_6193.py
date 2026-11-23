"""tests/test_edition_output_taint_6193.py — an edition may not carry the words of a coach output the policy withholds (#6193).

The graded record (``web.publication_snapshot``) never covered a coach's daily OUTPUT rows: a site route empties a withheld
one at the read, so nothing was left to scrub. An edition's prose is written off the page, so a sentence copied from a
withheld daily output passed the edition gate. ``web.withheld_outputs`` closes it for the edition gate only — the same
six-word run, the same decision (the owner's by-record exceptions included), fail closed. Synthetic rows only.
"""

from __future__ import annotations

import os
import sys

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
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import narrative_provenance as NP  # noqa: E402
from content import chapter_editions as CE  # noqa: E402
from web import publication_snapshot as PS, withheld_outputs as WO  # noqa: E402

PK = "COACH#mind_coach"
WITHHELD = "A synthetic daily summary sentence that the provenance policy keeps off every public page today."
PUBLIC = "A synthetic public summary sentence written only from measured sources and recorded as public."


def _row(sk, text, provenance=None):
    r = {"pk": PK, "sk": sk, "public_summary": text, "date": "2026-09-22"}
    if provenance is not None:
        r[NP.PROVENANCE_KEY] = provenance
    return r


ROWS = {
    PK: [
        _row("OUTPUT#2026-09-22#daily_brief_mind", WITHHELD),  # no record: unrecorded, withheld
        _row("OUTPUT#2026-09-23#daily_brief_mind", PUBLIC, NP.stamp(["whoop"], producer="test")),  # a public record
    ]
}


class _Table:
    """A raw table answering a key query by partition and sort-key prefix (all on one page)."""

    def __init__(self, rows_by_pk, fail=False):
        self.rows = [r for rows in rows_by_pk.values() for r in rows]
        self.fail = fail
        self.queries = 0

    def query(self, **kw):
        self.queries += 1
        if self.fail:
            raise RuntimeError("throttled")
        expr = kw["KeyConditionExpression"].get_expression()["values"]
        pk = expr[0].get_expression()["values"][1]
        prefix = expr[1].get_expression()["values"][1]
        return {"Items": [dict(r) for r in self.rows if r["pk"] == pk and r["sk"].startswith(prefix)]}


@pytest.fixture(autouse=True)
def _fresh():
    WO.reset()
    yield
    WO.reset()


def test_a_withheld_outputs_words_are_caught_and_a_public_outputs_are_not():
    hit = WO.matcher(WO.digest(ROWS))
    assert hit(WITHHELD)
    assert hit("He read it as follows: the provenance policy keeps off every public page today, and moved on.")  # a run
    assert not hit(PUBLIC)  # a row with a public record is not withheld
    assert not hit("A sentence of the edition's own that shares no six-word run with any stored output at all.")
    assert not hit("keeps off every public")  # under six words: never a run


def test_the_whole_partition_is_read_and_cached_and_an_unreadable_read_refuses():
    t = _Table(ROWS)
    assert WO.matcher(WO.load(t))(WITHHELD)
    n = t.queries
    assert n == len([p for p in PS.partitions() if p != PS.DOCKET_PK]) * len(WO.SK_PREFIXES)  # every coach seat, whole
    WO.load(t)
    assert t.queries == n  # cached
    WO.reset()
    with pytest.raises(RuntimeError):
        WO.load(_Table(ROWS, fail=True))


def test_the_edition_gate_refuses_a_withheld_outputs_words_and_fails_closed():
    t = _Table(ROWS)
    text = '"A Sample Chapter"\n\n*A sample summary line for a test, for layout only.*\n\n' + WITHHELD
    tainted = WO.with_outputs(lambda _t: False, t)
    findings = CE.gate_findings(text, tainted=tainted, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: [])
    assert any(f.startswith("private-call:") for f in findings)
    clean = '"A Sample Chapter"\n\n*A sample summary line for a test, for layout only.*\n\n' + PUBLIC
    assert CE.gate_findings(clean, tainted=tainted, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: []) == []
    WO.reset()
    broken = WO.with_outputs(lambda _t: False, _Table(ROWS, fail=True))
    got = CE.gate_findings(clean, tainted=broken, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: [])
    assert any("could not be read" in f for f in got)  # unreadable outputs: nothing is published unchecked


def test_the_mcp_door_and_the_site_api_both_check_the_outputs(monkeypatch):
    from web import narrative_publication as NPub, site_api_chapters as chapters

    import mcp.tools_chapter_corrections as tool

    t = _Table(ROWS)
    monkeypatch.setattr(tool, "_table_ref", t)
    monkeypatch.setattr(PS, "complete", lambda: (frozenset(), frozenset()))
    assert tool._tainted()(WITHHELD) and not tool._tainted()(PUBLIC)
    WO.reset()
    monkeypatch.setattr(tool, "_table_ref", _Table(ROWS, fail=True))
    assert tool._tainted() is None  # unreadable: the door refuses
    WO.reset()
    monkeypatch.setattr(chapters, "table", t)
    monkeypatch.setattr(NPub, "is_tainted", lambda _t: False)
    assert chapters._is_tainted(WITHHELD) and not chapters._is_tainted(PUBLIC)


def test_the_site_wire_scrub_is_unchanged():
    """The extension is the EDITION gate's: the Site API's wire scrub (``is_tainted``) does not read output rows."""
    from web import narrative_publication as NPub

    src = open(os.path.join(_REPO, "lambdas", "web", "narrative_publication.py"), encoding="utf-8").read()
    assert "withheld_outputs" not in src
    assert NPub.COUNTED_SK_PREFIXES == ("PREDICTION#", "COMMITMENT#", "LEARNING#", "CALIB#", "OPEN#", "RESOLVED#")


def test_an_unreadable_outputs_read_withholds_editions_and_never_fails_the_chapters_route(monkeypatch):
    """LIVE is committed on: a throttled OUTPUT read must leave /api/chapters serving (200) with every edition withheld."""
    from content import private_call_check
    from test_chapter_editions_6193 import _edition, _original, _with_restores
    from web import narrative_publication as NPub, site_api_chapters as chapters

    monkeypatch.setattr(CE, "LIVE", True)
    monkeypatch.setattr(NPub, "is_tainted", lambda _t: False)
    monkeypatch.setattr(chapters.private_call_check, "load", lambda _table: private_call_check.CallSet())
    chapters._CALLS_CACHE.update(at=None, calls=None)
    rows = _with_restores([_original(), _edition(2)])
    monkeypatch.setattr(chapters, "table", _Table(ROWS))
    assert [e["edition"] for e in chapters.editions_field(lambda: rows)["editions"]] == [2]
    WO.reset()
    monkeypatch.setattr(chapters, "table", _Table(ROWS, fail=True))
    assert chapters.editions_field(lambda: rows) == {"editions": []}  # withheld, the field still served, no error key

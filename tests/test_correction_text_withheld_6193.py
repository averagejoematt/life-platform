"""tests/test_correction_text_withheld_6193.py — a superseded correction whose own text restates withheld material (#6193).

The owner may append ONE approved record that withholds a SUPERSEDED correction's statement text from public view. The
stored correction is never edited or deleted; the public view keeps its id, kind, date, signature and approvals, drops
``published_said`` / ``record_shows`` / ``evidence`` and says ``text_withheld``; the page says only that a correction of
that date was replaced. A correction that is not superseded is refused. And a NEW correction's text is refused at
proposal if it restates a withheld call or a withheld coach output (fail closed). Synthetic records only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in (("TABLE_NAME", "life-platform"), ("AWS_REGION", "us-west-2"), ("AWS_DEFAULT_REGION", "us-west-2"), ("USER_ID", "matthew")):
    os.environ.setdefault(_k, _v)
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content import chapter_corrections as CC  # noqa: E402
from test_chapter_corrections_6177 import _approved, _FakeTable  # noqa: E402

OLD = "old-figure"
NEW = "figure-removed"


def _pair():
    return [_approved(correction_id=OLD), _approved(correction_id=NEW, supersedes=OLD)]


def _withheld(corr=OLD):
    return CC.new_text_withheld(chapter_id="week-09", correction_id=corr, at="2026-11-23T18:00:00Z", dated_on="2026-11-23")


def test_a_withheld_superseded_correction_keeps_its_trail_and_loses_only_its_statement():
    rows = _pair()
    before = {c["id"]: c for c in CC.public_view(rows)}
    assert before[OLD]["superseded_by"] == NEW and "text_withheld" not in before[OLD]  # no record: as before, byte for byte
    after = {c["id"]: c for c in CC.public_view(rows + [_withheld()])}
    old = after[OLD]
    assert old["text_withheld"] is True and old["superseded_by"] == NEW
    assert not set(CC.STATEMENT_TEXT_FIELDS) & set(old)
    assert old["signature"] == before[OLD]["signature"] and old["dated_on"] == before[OLD]["dated_on"] and old["approvals"]
    assert after[NEW] == before[NEW]  # the correction that replaced it is untouched
    # a record for a correction that is NOT superseded changes nothing (the tool refuses it; the view ignores it too)
    lone = {c["id"]: c for c in CC.public_view([_approved(correction_id=OLD)] + [_withheld()])}
    assert "text_withheld" not in lone[OLD] and lone[OLD]["published_said"]


def test_the_snapshot_accepts_the_withheld_shape_only_for_a_superseded_correction():
    import publish_snapshot_chapter_corrections as SC

    pub = {"chapter": [{"id": "week-09", "status": "published"}]}
    doc = {"state": "ok", "source": ["/api/chapters"], "absent_text": None, "corrections": CC.public_view(_pair() + [_withheld()])}
    out = SC.validate(json.loads(json.dumps(doc)), pub)
    assert {c["id"]: c.get("text_withheld") for c in out["corrections"]} == {OLD: True, NEW: None}
    bad = json.loads(json.dumps(doc))
    bad["corrections"][[c["id"] for c in bad["corrections"]].index(OLD)]["superseded_by"] = None
    with pytest.raises(ValueError):
        SC.validate(bad, pub)


def test_the_page_says_only_that_a_correction_was_replaced():
    view = CC.public_view(_pair() + [_withheld()])
    script = (
        "import { correctionsHtml } from './src/lib/chapter_corrections.js';\n"
        f"const view = {json.dumps(view)};\n"
        "process.stdout.write(correctionsHtml(view));\n"
    )
    cp = subprocess.run(["node", "--input-type=module", "-e", script], cwd=os.path.join(_REPO, "www"), capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr[-800:]
    html = cp.stdout
    old_block = html[html.index(f'data-correction="{OLD}"') :]
    assert "data-text-withheld" in old_block and "A correction dated 23 November 2026 was replaced by the correction above." in old_block
    assert "What the chapter published" not in old_block and "Correction, 23 November 2026 — Average Joe Matt editorial record" in old_block


@pytest.fixture
def tool(monkeypatch):
    import mcp.tools_chapter_corrections as t

    table = _FakeTable()
    monkeypatch.setattr(t, "_table_ref", table)
    monkeypatch.setattr(t, "pacific_today", lambda: "2026-11-23")
    monkeypatch.setattr(t, "_tainted", lambda: lambda text: "restates a withheld coach summary" in text)
    from content import private_call_check

    monkeypatch.setattr(t, "_private_calls", lambda: private_call_check.CallSet())
    return t, table


def test_the_tool_withholds_only_on_his_word_and_only_a_superseded_correction(tool):
    t, table = tool
    call = lambda **kw: t.tool_manage_chapter_corrections(
        {"action": "withhold_correction_text", "chapter_id": "week-09", **kw}
    )  # noqa: E731
    for not_true in (None, False, "true", 1):
        assert "exactly true" in call(correction_id=OLD, approved=not_true)["error"]
    assert "not an approved correction" in call(correction_id=OLD, approved=True)["error"]
    table.put_item(Item=_approved(correction_id=OLD))
    assert "not superseded" in call(correction_id=OLD, approved=True)["error"]
    table.put_item(Item=_approved(correction_id=NEW, supersedes=OLD))
    ok = call(correction_id=OLD, approved=True, note="a test")
    assert ok["stored"] and ok["superseded_by"] == NEW
    assert "append-only" in call(correction_id=OLD, approved=True)["error"]
    stored = table.get_item(Key={"pk": CC.pk(), "sk": CC.sk("week-09", OLD)})["Item"]
    assert stored["published_said"]  # the correction record itself is never edited
    listing = t.tool_manage_chapter_corrections({"action": "list", "chapter_id": "week-09"})
    assert {r["correction_id"]: r["text_withheld"] for r in listing["corrections"]} == {OLD: True, NEW: False}


def test_a_new_correction_cannot_restate_withheld_words_and_fails_closed(tool, monkeypatch):
    t, table = tool
    args = dict(
        chapter_id="week-09",
        correction_id="a-new-one",
        kind="correction",
        published_said="The chapter quoted a line that restates a withheld coach summary word for word.",
        record_shows="The quotation's source could not be established as publishable.",
        evidence="The chronicle row for the week.",
    )
    r = t.tool_manage_chapter_corrections({"action": "propose", **args})
    assert "keeps private" in r["error"] and r["findings"] and not table.items
    ok = t.tool_manage_chapter_corrections({"action": "propose", **args, "published_said": "The chapter quoted a coach's written summary."})
    assert ok["stored"]
    monkeypatch.setattr(t, "_tainted", lambda: None)  # the publication record cannot be opened: refused
    r = t.tool_manage_chapter_corrections({"action": "propose", **args, "correction_id": "another", "published_said": "Plain words."})
    assert "keeps private" in r["error"]

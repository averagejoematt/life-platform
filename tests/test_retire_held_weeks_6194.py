"""tests/test_retire_held_weeks_6194.py — retiring held chronicle weeks 8, 9 and 11 (#6194, owner ruling 2026-11-22).

The ruling: retire the drafts rather than force them into chapters; preserve every original record; the public status
says a draft existed and did not meet the standard for publication; week 7 stays skipped because no chapter was written.

What is pinned (the #6178 machinery — the status, the switch, the publish refusals — is pinned in
tests/test_chronicle_week_states_6178.py and is not repeated here):
  * THE WORDING: a retired week reads exactly the ruled fact — a draft was written and did not meet the standard — with
    no reason, no blame, no actor and nothing from the draft.
  * WEEK 7: with the switch on, a skipped week (no row, so no draft) says "no chapter was written"; with it off the
    wire is unchanged. A held-marker reason still wins for the week it names.
  * PRESERVATION: the Wednesday writer never writes over a retired row — not on a re-run, and not under
    {"force": true}; a draft or published row keeps its existing guard.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from content import autopublish_audit  # noqa: E402
from emails import chronicle_store  # noqa: E402
from web import site_api_chapters as chapters  # noqa: E402

GENESIS, TODAY = "2026-09-06", "2026-11-22"
SENTINEL = "DRAFT-SENTINEL-6194"


def _ps():
    spec = importlib.util.spec_from_file_location("publish_snapshot_6194", _REPO / "scripts" / "publish_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The live shape on 2026-11-22: weeks 1-6 and 10 published, 7 with no row, 8/9 changes_requested, 11 draft.
def _rows(held_status="retired"):
    rows = [
        {"date": d, "week_number": str(w), "status": "published", "generated_at": f"{d}T15:00:00+00:00"}
        for w, d in ((1, "2026-09-08"), (2, "2026-09-15"), (3, "2026-09-22"), (4, "2026-09-29"), (5, "2026-10-06"), (6, "2026-10-13"))
    ]
    rows.append({"date": "2026-11-10", "week_number": "10", "status": "published", "generated_at": "2026-11-11T15:00:00+00:00"})
    for w, d in ((8, "2026-10-27"), (9, "2026-11-03"), (11, "2026-11-17")):
        rows.append({"date": d, "week_number": str(w), "status": held_status, "generated_at": f"{d}T16:00:00+00:00", "title": SENTINEL})
    return rows


def _journal(marker=None):
    posts = [
        {"week": w, "date": d, "title": f"Chapter {w}", "url": f"/journal/posts/week-{w:02d}/", "label": f"Week {w}"}
        for w, d in ((1, "2026-09-08"), (2, "2026-09-15"), (3, "2026-09-22"), (4, "2026-09-29"), (5, "2026-10-06"), (6, "2026-10-13"))
    ]
    posts.append({"week": 10, "date": "2026-11-10", "title": "Chapter 10", "url": "/journal/posts/week-12/", "label": "Week 10"})
    doc = {"posts": posts}
    if marker:
        doc["pending"] = marker
    return doc


def _weeks(doc):
    return {w["week"]: w for w in doc["weeks"]}


# ── the wording ──────────────────────────────────────────────────────────────


def test_the_retired_line_is_the_ruled_fact_and_nothing_more():
    text = _ps().WEEK_STATE_TEXT["retired"]
    assert text.startswith("A draft was written for this week and did not meet the standard for publication.")
    low = text.lower()
    # no actor, no blame, no reason beyond the standard, nothing that describes the draft
    for word in ("matthew", "decided", "owner", "because", "rejected", "failed", "error", "quality", "weak", "invented", "privacy"):
        assert word not in low, (word, text)


def test_week_7_says_no_chapter_was_written_with_the_switch_on_and_is_unchanged_with_it_off():
    on = _weeks(chapters.compose(_rows(), _journal(), GENESIS, TODAY, retired_on=True))
    assert on[7]["status"] == "skipped" and on[7]["reason"] == chapters.NO_CHAPTER_WRITTEN == "no chapter was written"
    assert [w for w, e in on.items() if e["status"] == "retired"] == [8, 9, 11]
    assert on[10]["status"] == "published" and on[12]["status"] == "pending"
    assert SENTINEL not in json.dumps(list(on.values()))
    off = _weeks(chapters.compose(_rows(), _journal(), GENESIS, TODAY))
    assert off[7]["reason"] == chapters.NO_CHAPTER == "no chapter was published", "switch off: the wire is unchanged"
    assert [w for w, e in off.items() if e["status"] == "held"] == [8, 9, 11]


def test_a_held_marker_reason_still_wins_for_the_skipped_week_it_names():
    marker = {"week": 7, "reason": "budget_paused", "display": "Paused by the budget guard.", "noted_at": "x"}
    on = _weeks(chapters.compose(_rows(), _journal(marker), GENESIS, TODAY, retired_on=True))
    assert on[7]["reason"] == "Paused by the budget guard."


def test_the_snapshot_prints_the_skipped_and_retired_lines_as_served():
    ps = _ps()
    api = [
        {"week": 7, "status": "skipped", "reason": chapters.NO_CHAPTER_WRITTEN, "start": "2026-10-18"},
        {"week": 8, "status": "retired", "reason": SENTINEL, "title": SENTINEL, "start": "2026-10-25"},
    ]
    ctx = ps.LiveContext("https://example.invalid", {"edition": {"as_of": TODAY, "start_date": GENESIS}, "chapters": {"weeks": api}}, 1.0)
    ps._live_week_states(ctx)
    got = {o["week"]: o for o in ctx.objs["chapter"]}
    assert got[7]["absent_text"] == "No chapter was written."
    assert got[8]["absent_text"] == ps.WEEK_STATE_TEXT["retired"]
    assert SENTINEL not in json.dumps(list(got.values()))


# ── preservation: the writer never overwrites a retired row ──────────────────


class _CondFailed(Exception):
    pass


_CondFailed.__name__ = "ConditionalCheckFailedException"


class _Table:
    """Evaluates the two condition shapes store_installment writes against one existing row."""

    def __init__(self, existing_status):
        self.existing = {"sk": "DATE#2026-11-17", "status": existing_status, "content_markdown": "original"} if existing_status else None
        self.puts = []

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        if ConditionExpression and self.existing is not None:
            st = self.existing.get("status")
            vals = set((ExpressionAttributeValues or {}).values())
            if " IN (" in ConditionExpression and st in vals:
                raise _CondFailed("The conditional request failed")
            if "<> :retired" in ConditionExpression and st == ExpressionAttributeValues[":retired"]:
                raise _CondFailed("The conditional request failed")
        self.puts.append(Item)
        self.existing = Item


@pytest.fixture
def no_archive(monkeypatch):
    from common import qa_archive

    monkeypatch.setattr(qa_archive, "archive_text", lambda *a, **k: None)


def _store(table, force):
    g = {"table": table, "USER_ID": "matthew", "logger": logging.getLogger("t6194")}
    return chronicle_store.store_installment(
        "2026-11-17", 11, "New Title", "Day 67 to Day 73", "regenerated text", "<p>x</p>", [], False, status="draft",
        allow_overwrite=force, _g=g,
    )  # fmt: skip


def test_the_writer_never_overwrites_a_retired_row_even_when_forced(no_archive):
    for force in (False, True):
        t = _Table("retired")
        assert _store(t, force) is False, force
        assert t.puts == [] and t.existing["content_markdown"] == "original", force


def test_the_other_statuses_keep_their_existing_guard(no_archive):
    # draft / published: refused on a re-run, written under force (the documented regeneration hatch)
    for st in ("draft", "published"):
        assert _store(_Table(st), False) is False, st
        assert _store(_Table(st), True) is True, st
    # changes_requested is the documented signal to regenerate; a fresh week has no row
    assert _store(_Table("changes_requested"), False) is True
    assert _store(_Table(None), False) is True


def test_the_retired_status_is_one_name_across_the_writer_and_the_audit():
    assert chronicle_store.RETIRED_STATUS == autopublish_audit.RETIRED_STATUS == chapters.RETIRED_STATUS == "retired"
    assert chronicle_store.RETIRED_STATUS in chronicle_store.PROTECTED_STATUSES

"""tests/test_chronicle_manifest_published_only.py — a held installment never reaches the public reading list.

Week 10 (2026-11-14): publishing it wrote a manifest built at draft time from every row in the phase, so Weeks 8 and 9 —
both ``changes_requested`` — went onto /journal/posts.json (and, through it, /api/chapters as "published") with their
titles and excerpts. The same write rewrote Week 6's excerpt. Two layers now stop that:

  * the builder (``chronicle_render.publish_to_journal`` and ``deploy/restart_leadin_pages``) lists only published rows,
    plus the one row being published — while every URL slot is still sequenced over ALL rows, so no live link moves;
  * the publish step (``chronicle_approve_lambda._merge_manifest``) writes the LIVE manifest with only this post's entry
    added, never the draft-time snapshot whole.
"""

import importlib.util
import io
import json
import os
import sys
from unittest import mock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import pytest  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402
from content import chronicle_schema  # noqa: E402


def _row(title, date, status, week):
    return {
        "title": title,
        "week_number": week,
        "date": date,
        "sk": f"DATE#{date}",
        "status": status,
        "stats_line": "",
        "word_count": 100,
        "content_markdown": f"{title} body",
        "phase": "experiment",
    }


WK6 = _row("The Quiet Accumulation", "2026-10-13", "published", 6)
WK8 = _row("A held week", "2026-10-27", "changes_requested", 8)
WK9 = _row("Another held week", "2026-11-03", "draft", 9)
WK10 = _row("The Rate Flag", "2026-11-10", "draft", 10)  # being published: its row still reads draft
ROWS = [WK6, WK8, WK9, WK10]


class _NoS3:
    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _manifest(monkeypatch, rows=ROWS, current=WK10):
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: False)
    monkeypatch.setattr(chronicle_schema, "WITHDRAWN_SKS", frozenset())
    key, _h, js = chron.publish_to_journal(
        title=current["title"],
        stats_line="",
        body_html="<p>b</p>",
        week_num=current["week_number"],
        date_str=current["date"],
        all_installments=rows,
        write_to_s3=False,
    )
    return key, json.loads(js)["posts"]


def test_held_rows_stay_off_the_list(monkeypatch):
    _k, posts = _manifest(monkeypatch)
    titles = [p["title"] for p in posts]
    assert titles == ["The Rate Flag", "The Quiet Accumulation"]


def test_held_rows_keep_their_url_slots_so_no_link_moves(monkeypatch):
    key, posts = _manifest(monkeypatch)
    # Week 10 is the 4th row by date: its page key is week-04 with the two held rows in the sequence, exactly as before.
    assert key == "generated/journal/posts/week-04/index.html"
    assert {p["title"]: p["url"] for p in posts}["The Rate Flag"] == "/journal/posts/week-04/"


def test_mutation_control_a_published_week_9_is_listed(monkeypatch):
    rows = [WK6, WK8, {**WK9, "status": "published"}, WK10]
    _k, posts = _manifest(monkeypatch, rows)
    assert "Another held week" in [p["title"] for p in posts]
    assert "A held week" not in [p["title"] for p in posts]


def test_a_row_with_no_status_fails_closed():
    assert chronicle_schema.off_the_list({"sk": "DATE#2026-11-03"})
    assert not chronicle_schema.off_the_list({"sk": "DATE#2026-11-03"}, publishing=True)
    assert chronicle_schema.off_the_list({"sk": "DATE#2026-11-03", "unlisted": True}, publishing=True)


# ── the publish-time merge ────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def approve():
    path = os.path.join(_REPO, "lambdas", "emails", "chronicle_approve_lambda.py")
    spec = importlib.util.spec_from_file_location("chronicle_approve_manifest_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LIVE = {
    "posts": [
        {"url": "/journal/posts/week-09/", "title": "The Quiet Accumulation", "date": "2026-10-13", "sequence": 9, "excerpt": "approved"},
        {"url": "/journal/posts/week-08/", "title": "Park's Blind Spot", "date": "2026-10-06", "sequence": 8, "excerpt": "x"},
    ]
}
STAGED = {
    "posts": [
        {"url": "/journal/posts/week-12/", "title": "The Rate Flag", "date": "2026-11-10", "sequence": 12},
        {"url": "/journal/posts/week-11/", "title": "Another held week", "date": "2026-11-03", "sequence": 11},
        {"url": "/journal/posts/week-10/", "title": "A held week", "date": "2026-10-27", "sequence": 10},
        {"url": "/journal/posts/week-09/", "title": "The Quiet Accumulation", "date": "2026-10-13", "sequence": 9, "excerpt": "rewritten"},
    ]
}
KEY = "generated/journal/posts/week-12/index.html"


def _merge(approve, live=LIVE, staged=STAGED, key=KEY, get=None):
    failures = []
    body = {"Body": io.BytesIO(json.dumps(live).encode())}
    with mock.patch.object(approve.s3, "get_object", side_effect=get, return_value=body):
        out = approve._merge_manifest(json.dumps(staged), key, failures)
    return (json.loads(out)["posts"] if out else None), failures


def test_the_merge_adds_only_this_post_to_the_live_list(approve):
    posts, failures = _merge(approve)
    assert [p["title"] for p in posts] == ["The Rate Flag", "The Quiet Accumulation", "Park's Blind Spot"]
    assert posts[1]["excerpt"] == "approved"  # a published record is not rewritten by a draft-time snapshot
    assert failures == []


def test_a_republish_replaces_its_own_entry_once(approve):
    live = {"posts": [{"url": "/journal/posts/week-12/", "title": "Old", "date": "2026-11-10", "sequence": 12}] + LIVE["posts"]}
    posts, _f = _merge(approve, live=live)
    assert [p["title"] for p in posts].count("The Rate Flag") == 1 and "Old" not in [p["title"] for p in posts]


def test_an_unreadable_live_list_is_left_alone(approve):
    posts, failures = _merge(approve, get=RuntimeError("AccessDenied"))
    assert posts is None and failures and "could not be read" in failures[0]


def test_a_missing_live_list_starts_one(approve):
    class _NoKey(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    posts, failures = _merge(approve, get=_NoKey())
    assert [p["title"] for p in posts] == ["The Rate Flag"] and failures == []


def test_no_entry_for_this_post_writes_nothing(approve):
    posts, failures = _merge(approve, key="generated/journal/posts/week-13/index.html")
    assert posts is None and "no entry" in failures[0]

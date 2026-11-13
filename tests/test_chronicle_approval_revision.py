"""tests/test_chronicle_approval_revision.py — an approve link approves only the text it showed (owner ruling 2026-11-06).

"Old approval links must not authorize a different revision." The approve path recomputes the revision id from the row at
click time, so a stored draft that changed — and a link minted before ids existed — publishes nothing.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from content import chronicle_revision as cr  # noqa: E402
from emails import (
    chronicle_approve_lambda as approve,  # noqa: E402
    chronicle_store,  # noqa: E402
)

TOKEN = "t" * 64


def _row(**over):
    row = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2099-01-06",
        "date": "2099-01-06",
        "status": "draft",
        "week_number": 3,
        "approval_token": TOKEN,
        "title": "A Title",
        "stats_line": "Day 3",
        "content_markdown": "Original text.",
        "content_html": "<p>Original text.</p>",
        "draft_journal_post_html": "<p>page</p>",
        "draft_email_html": "<p>mail</p>",
        "desk_findings_json": '{"post": [], "episode": []}',  # owner ruling 2026-11-13: an approval needs a passing audit
    }
    row.update(over)
    return row


@pytest.fixture
def harness(monkeypatch):
    calls = {"published": [], "changes": []}
    state = {"row": _row()}
    monkeypatch.setattr(approve, "_get_draft", lambda _d: state["row"])
    monkeypatch.setattr(approve, "publish_side_effects", lambda item, d, **k: calls["published"].append(item["content_markdown"]))
    monkeypatch.setattr(approve, "_mark_changes_requested", lambda d: calls["changes"].append(d))
    return state, calls


def _click(rev, action="approve"):
    qs = {"date": "2099-01-06", "token": TOKEN, "action": action}
    if rev is not None:
        qs["rev"] = rev
    return approve._handle({"queryStringParameters": qs})


def test_a_link_for_this_revision_publishes(harness):
    state, calls = harness
    resp = _click(cr.revision_id(state["row"]))
    assert resp["statusCode"] == 200 and calls["published"] == ["Original text."]


@pytest.mark.parametrize(
    "field",
    [f for f in cr.REVISION_FIELDS],
)
def test_a_change_to_any_publishable_field_retires_the_old_link(harness, field):
    state, calls = harness
    old = cr.revision_id(state["row"])
    state["row"] = _row(**{field: "edited after the link was mailed"})
    resp = _click(old)
    assert resp["statusCode"] == 409 and calls["published"] == []


def test_a_link_with_no_revision_is_refused(harness):
    """Every link mailed before this shipped, and a link minted when the read-back failed."""
    _state, calls = harness
    assert _click(None)["statusCode"] == 409
    assert _click("")["statusCode"] == 409
    assert calls["published"] == []


def test_a_stale_request_changes_link_changes_nothing(harness):
    state, calls = harness
    old = cr.revision_id(state["row"])
    state["row"] = _row(content_markdown="Revised.")
    assert _click(old, action="request_changes")["statusCode"] == 409
    assert calls["changes"] == []


def test_a_wrong_token_is_still_refused_first(harness):
    state, calls = harness
    resp = approve._handle(
        {"queryStringParameters": {"date": "2099-01-06", "token": "x" * 64, "action": "approve", "rev": cr.revision_id(state["row"])}}
    )
    assert resp["statusCode"] == 403 and calls["published"] == []


def test_the_id_ignores_fields_that_publish_nothing():
    base = cr.revision_id(_row())
    assert cr.revision_id(_row(status="changes_requested", revisions=[{"at": "x"}], approval_token="other", generated_at="y")) == base
    assert cr.revision_id({**_row(), "draft_recap_json": ""}) == base  # absent and empty hash alike


class _Ses:
    def __init__(self):
        self.sent = {}

    def send_email(self, **kw):
        self.sent.update(kw)


class _Log:
    def info(self, *a, **k):
        pass

    warning = error = info


class _Table:
    def __init__(self, item):
        self.item = item

    def get_item(self, Key, **_):
        return {"Item": self.item} if self.item else {}


def _send(item, revision=None):
    ses = _Ses()
    g = {
        "APPROVE_LAMBDA_URL": "https://approve.test/",
        "ses": ses,
        "SENDER": "a@b",
        "RECIPIENT": "c@d",
        "logger": _Log(),
        "table": _Table(item),
        "USER_ID": "matthew",
    }
    chronicle_store._send_preview_email("T", 3, "2099-01-06", TOKEN, "<html><body>x</body></html>", revision=revision, _g=g)
    return ses.sent["Content"]["Simple"]["Body"]["Html"]["Data"].replace("&amp;", "&")


def test_the_preview_email_links_carry_the_revision():
    html = _send(None, revision="abc123")
    assert "action=approve&rev=abc123" in html and "action=request_changes&rev=abc123" in html


def test_the_preview_binds_to_the_row_as_stored():
    """By default the id is read from the stored row (desk artifacts included) — exactly the text the email shows."""
    stored = _row(desk_episode_json='{"turns": []}')
    assert f"action=approve&rev={cr.revision_id(stored)}" in _send(stored)
    assert 'action=approve&rev="' in _send(None)  # a failed read-back mints an empty id, which the approve path refuses

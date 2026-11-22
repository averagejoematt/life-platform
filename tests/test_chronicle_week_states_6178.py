"""tests/test_chronicle_week_states_6178.py — the Story page tells the truth about each week: published, held, skipped,
and (new, owner-set) retired (#6178, owner ruling 2026-11-22 §4).

What is pinned:
  * HELD is one neutral state with no reason: the stored statuses cannot say whether the owner sent a week back or
    whether it only awaits his approval, so neither is claimed (the API, the exporter's line, the QA wording).
  * RETIRED exists as a status the owner can set, behind ``CHAPTERS_RETIRED_STATE`` (default off). With the switch off
    a retired row is served as held — never as skipped. A row in an unknown status is held, never skipped.
  * Nothing publishes a retired row: the approve click (either action) refuses it before anything else, the stale
    sweep never selects it, and the publish audit refuses it.
  * NO LEAK: no title, teaser, excerpt, body or reason a held or retired draft carries reaches the served document or
    the publication snapshot, even when the upstream document is malformed and carries them.
  * The constants every layer uses agree.
"""

from __future__ import annotations

import importlib.util
import json
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

from content import autopublish_audit, chronicle_revision  # noqa: E402
from operational import story_season_qa  # noqa: E402
from web import site_api_chapters as chapters  # noqa: E402

GENESIS, TODAY = "2026-09-06", "2026-10-31"
SENTINEL = "HELD-SENTINEL-6178"  # planted in every private field; it must appear nowhere public


def _ps():
    spec = importlib.util.spec_from_file_location("publish_snapshot_6178", _REPO / "scripts" / "publish_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(status8="changes_requested", status7=None):
    rows = [
        {"date": f"2026-09-{d:02d}", "week_number": str(w), "status": "published", "generated_at": f"2026-09-{d:02d}T15:00:00+00:00"}
        for w, d in ((1, 8), (2, 15), (3, 22), (4, 29))
    ]
    rows.append(
        {"date": "2026-10-27", "week_number": "8", "status": status8, "generated_at": "2026-10-28T15:03:53+00:00", "title": SENTINEL}
    )
    if status7:
        rows.append(
            {"date": "2026-10-20", "week_number": "7", "status": status7, "generated_at": "2026-10-21T15:00:00+00:00", "title": SENTINEL}
        )
    return rows


def _journal(marker_week=8):
    posts = [
        {"week": w, "date": d, "title": f"Chapter {w}", "url": f"/journal/posts/week-{w:02d}/", "label": f"Week {w}"}
        for w, d in ((1, "2026-09-08"), (2, "2026-09-15"), (3, "2026-09-22"), (4, "2026-09-29"))
    ]
    pending = {"week": marker_week, "reason": "awaiting_approval", "display": f"{SENTINEL} waiting for Matthew's approval", "noted_at": "x"}
    return {"posts": posts, "pending": pending}


def _weeks(doc):
    return {w["week"]: w for w in doc["weeks"]}


# ── the served document ──────────────────────────────────────────────────────


def test_held_is_one_neutral_state_with_no_reason_whoever_set_it():
    for status in ("draft", "changes_requested"):
        doc = chapters.compose(_rows(status), _journal(8), GENESIS, TODAY)
        w8 = _weeks(doc)[8]
        assert w8["status"] == "held" and w8["reason"] is None, (status, w8)
    assert SENTINEL not in json.dumps([w for w in doc["weeks"]]), "a held draft's title or the marker's words leaked into a week"


def test_retired_is_served_only_behind_its_switch_and_never_as_skipped():
    off = _weeks(chapters.compose(_rows("retired"), _journal(None), GENESIS, TODAY))
    assert off[8]["status"] == "held", "switch off: a retired row is an unpublished draft — held, never skipped"
    on_doc = chapters.compose(_rows("retired"), _journal(None), GENESIS, TODAY, retired_on=True)
    on = _weeks(on_doc)
    assert on[8]["status"] == "retired" and on[8]["reason"] is None and on[8]["title"] is None
    assert on_doc["counts"]["retired"] == 1
    assert "retired" not in chapters.compose(_rows(), _journal(None), GENESIS, TODAY)["counts"], "the wire is unchanged while off"
    assert SENTINEL not in json.dumps(on_doc["weeks"])


def test_a_row_in_an_unknown_status_is_held_never_skipped():
    for status in ("superseded", "archived", "", "RETIRED-ish"):
        w = _weeks(chapters.compose(_rows(status), _journal(None), GENESIS, TODAY, retired_on=True))[8]
        assert w["status"] == "held", (status, w)


def test_the_switch_defaults_off():
    assert chapters.retired_state_on({}) is False
    assert chapters.retired_state_on({chapters.RETIRED_SWITCH_ENV: "on"}) is True
    assert chapters.retired_state_on({chapters.RETIRED_SWITCH_ENV: "yes"}) is False


# ── the publication snapshot ─────────────────────────────────────────────────


def _snapshot_weeks(weeks_api):
    ps = _ps()
    ctx = ps.LiveContext(
        "https://example.invalid", {"edition": {"as_of": TODAY, "start_date": GENESIS}, "chapters": {"weeks": weeks_api}}, 1.0
    )
    ps._live_week_states(ctx)  # (week_start/week_end are added later in the pipeline; the enum is pinned below)
    return ps, {o["week"]: o for o in ctx.objs["chapter"]}


def test_each_state_reads_its_own_plain_line_and_no_draft_detail_leaks():
    leaky = {"title": SENTINEL, "excerpt": SENTINEL, "teaser": SENTINEL, "body": SENTINEL, "url": SENTINEL}
    api = [
        {"week": 7, "status": "skipped", "reason": "no chapter was published", "start": "2026-10-18"},
        {"week": 8, "status": "held", "reason": f"{SENTINEL} waiting for Matthew's approval", "start": "2026-10-25", **leaky},
        {"week": 9, "status": "retired", "reason": SENTINEL, "start": "2026-11-01", **leaky},
        {"week": 10, "status": "some-future-state", "reason": SENTINEL, "start": "2026-11-08", **leaky},
    ]
    ps, got = _snapshot_weeks(api)
    assert got[7]["status"] == "skipped" and got[7]["absent_text"] == "No chapter was published."
    assert got[8]["status"] == "held" and got[8]["absent_text"] == ps.WEEK_STATE_TEXT["held"]
    assert got[9]["status"] == "retired" and got[9]["absent_text"] == ps.WEEK_STATE_TEXT["retired"]
    assert got[10]["status"] == "held", "an unknown state is an unpublished draft: held, never dropped or skipped"
    for o in got.values():
        assert o["title"] == f"Week {o['week']}" and o["excerpt"] is None and o["body_html"] is None and o["url_legacy"] is None
    assert SENTINEL not in json.dumps(list(got.values())), "a held or retired draft's words reached the snapshot"
    assert "waiting for" not in json.dumps(list(got.values())) and "sent back" not in json.dumps(list(got.values()))


def test_the_contract_and_the_site_schema_accept_retired():
    contract = (_REPO / "scripts" / "publish_snapshot_contract.py").read_text(encoding="utf-8")
    zod = (_REPO / "www" / "src" / "content.config.ts").read_text(encoding="utf-8")
    assert '"enum:published|held|skipped|pending|retired"' in contract
    assert 'status: z.enum(["published", "held", "skipped", "pending", "retired"])' in zod
    url = (_REPO / "www" / "src" / "lib" / "url.js").read_text(encoding="utf-8")
    assert 'obj.status !== "retired"' in url, "a retired week has no page: it is listed in words, like a held one"


# ── nothing publishes a retired row ──────────────────────────────────────────

TOKEN = "t" * 64


def _row(**over):
    row = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2099-01-06",
        "date": "2099-01-06",
        "status": "retired",
        "week_number": 9,
        "approval_token": TOKEN,
        "title": "A Title",
        "stats_line": "Day 3",
        "content_markdown": "Original text.",
        "content_html": "<p>Original text.</p>",
        "draft_journal_post_html": "<p>page</p>",
        "draft_email_html": "<p>mail</p>",
        "desk_findings_json": '{"post": [], "episode": []}',
    }
    row.update(over)
    return row


@pytest.fixture
def approve(monkeypatch):
    from emails import chronicle_approve_lambda as m

    calls = {"published": [], "changes": []}
    state = {"row": _row()}
    monkeypatch.setattr(m, "_get_draft", lambda _d: state["row"])
    monkeypatch.setattr(m, "publish_side_effects", lambda item, d, **k: calls["published"].append(d))
    monkeypatch.setattr(m, "_mark_changes_requested", lambda d: calls["changes"].append(d))
    return m, state, calls


def test_a_retired_row_is_refused_by_both_link_actions_with_a_valid_token_and_revision(approve):
    m, state, calls = approve
    rev = chronicle_revision.revision_id(state["row"])
    for action in ("approve", "request_changes"):
        resp = m._handle({"queryStringParameters": {"date": "2099-01-06", "token": TOKEN, "action": action, "rev": rev}})
        assert resp["statusCode"] == 409 and "retired" in resp["body"], action
    assert calls == {"published": [], "changes": []}, "a retired row must never publish or change state from a link"
    # mutation control: the same row as a draft DOES publish through the same harness
    state["row"] = _row(status="draft")
    resp = m._handle(
        {
            "queryStringParameters": {
                "date": "2099-01-06",
                "token": TOKEN,
                "action": "approve",
                "rev": chronicle_revision.revision_id(state["row"]),
            }
        }
    )
    assert resp["statusCode"] == 200 and calls["published"] == ["2099-01-06"]


def test_the_sweep_never_selects_a_retired_row_and_the_audit_refuses_one(approve, monkeypatch):
    m, _state, _calls = approve
    import datetime as dt

    ga = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=60)).isoformat()
    items = [
        _row(status="retired", generated_at=ga, phase="experiment"),
        _row(sk="DATE#2099-01-13", status="draft", generated_at=ga, phase="experiment"),
    ]

    class T:
        def query(self, **k):
            return {"Items": items}

    monkeypatch.setattr(m, "table", T())
    monkeypatch.setattr(m, "_publishable", lambda it: True)
    picked = m._find_stale_drafts(48, 10)
    assert [it["status"] for it in picked] == ["draft"], "the sweep must not select a retired row"
    assert autopublish_audit.blocking_items(_row()) == ["retired by the owner: this draft is never published"]
    assert m.approval_refusal(_row()), "an approval refusal must name the retirement"


# ── QA and constants ─────────────────────────────────────────────────────────


def test_the_story_qa_recognises_retired_and_does_not_call_held_awaiting_approval():
    import datetime as dt

    doc = {"weeks": [{"week": 8, "status": "held", "drafted_at": "2026-10-28"}, {"week": 9, "status": "retired"}]}
    unexplained, _age, open_weeks = story_season_qa.door_findings(doc, dt.datetime(2026, 11, 21, tzinfo=dt.timezone.utc))
    assert unexplained == [] and open_weeks == ["week 8 drafted 2026-10-28, not approved"]


def test_every_layer_names_the_same_states():
    from emails import chronicle_approve_lambda as m

    assert chapters.RETIRED_STATUS == autopublish_audit.RETIRED_STATUS == m.RETIRED_STATUS == "retired"
    assert set(story_season_qa.WEEK_STATUSES) == set(chapters.WEEK_STATUSES)
    assert set(_ps().WEEK_STATE_TEXT) == set(chapters.WEEK_STATUSES) - {"published"}

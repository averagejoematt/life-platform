"""tests/test_horizons.py — Horizons weekly curation engine (#1705, epic #1686 S1).

Covers the four load-bearing pieces of S1:
  * the garden config parses + every entry is well-formed (name/category/domain),
  * the link-verification gate (ADR-104): a resolving URL verifies, a dead one is
    rejected fail-closed — with an INJECTED fetcher, no network,
  * the reading-rail storage extension (READING#HORIZON / PICK#<week>) round-trips
    against the FakeTable condition engine (no new partition/GSI),
  * the MCP tools: get_horizons empty state + curate_horizon's verify-then-store
    (verified commit stores; unverified is rejected and NEVER stored).
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import coach_checkin as cc  # noqa: E402
import pytest  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from reading import horizons_garden, horizons_verify, reading_keys as rk, reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402

from mcp import tools_reading as tr  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — the garden
# ══════════════════════════════════════════════════════════════════════════════
def test_garden_entries_are_well_formed():
    """Every garden entry parses and carries {name, category, base_url or domain}."""
    assert horizons_garden.GARDEN, "the garden must not be empty"
    for entry in horizons_garden.GARDEN:
        assert isinstance(entry, dict)
        assert entry.get("name"), f"entry missing name: {entry}"
        assert entry.get("category"), f"entry missing category: {entry}"
        assert entry.get("domain") or entry.get("base_url"), f"entry needs domain or base_url: {entry}"


def test_garden_is_grouped_by_category():
    cats = horizons_garden.categories()
    assert len(cats) >= 4, "the garden should span several categories (broad, not narrow)"
    grouped = horizons_garden.by_category()
    assert set(grouped) == set(cats)
    # the starter set spans at least these pillars
    for pillar in ("health", "mind", "news"):
        assert pillar in cats


def test_format_enum_is_the_owner_locked_set():
    assert horizons_garden.FORMATS == ("article", "podcast", "video", "paper", "news", "longform", "essay", "song")
    assert horizons_garden.RATIONALE_TAGS == ("topical", "experiment-relevant")
    assert horizons_garden.CURATOR == "mind"
    assert horizons_garden.is_valid_format("song") and not horizons_garden.is_valid_format("tweet")
    assert horizons_garden.is_valid_rationale("topical") and not horizons_garden.is_valid_rationale("random")


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — the link-verification gate (fail-closed)
# ══════════════════════════════════════════════════════════════════════════════
def _ok_fetch(_url, _timeout):
    return 200, b"x" * 500  # a resolving page with real content


def _dead_fetch(_url, _timeout):
    raise TimeoutError("connection timed out")


def test_verify_accepts_a_resolving_url():
    v = horizons_verify.verify_url("https://example.com/real", fetcher=_ok_fetch)
    assert v["verified"] is True
    assert v["status"] == 200
    assert v["url"] == "https://example.com/real"


def test_verify_rejects_a_dead_url_fail_closed():
    v = horizons_verify.verify_url("https://example.com/gone", fetcher=_dead_fetch)
    assert v["verified"] is False
    assert "fetch failed" in v["reason"]


def test_verify_rejects_non_2xx():
    v = horizons_verify.verify_url("https://example.com/404", fetcher=lambda u, t: (404, b"x" * 500))
    assert v["verified"] is False
    assert "404" in v["reason"]


def test_verify_rejects_empty_body():
    v = horizons_verify.verify_url("https://example.com/blank", fetcher=lambda u, t: (200, b"  "))
    assert v["verified"] is False
    assert "too small" in v["reason"]


def test_verify_rejects_non_http_scheme():
    v = horizons_verify.verify_url("ftp://example.com/x", fetcher=_ok_fetch)
    assert v["verified"] is False
    assert "scheme" in v["reason"]


def test_verify_rejects_empty_url():
    assert horizons_verify.verify_url("", fetcher=_ok_fetch)["verified"] is False


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — storage: extend the reading rail (READING#HORIZON / PICK#<week>)
# ══════════════════════════════════════════════════════════════════════════════
def test_horizon_key_shape_reuses_reading_pk():
    key = rk.horizon_key("2026-W30")
    assert key == {"pk": "READING#HORIZON", "sk": "PICK#2026-W30"}
    assert key["pk"].startswith("READING#")  # CROSS_PHASE via the READING# prefix rule


@pytest.fixture()
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    monkeypatch.setattr(tr, "table", t)
    return t


def _pick(week, title="A Piece", url="https://ok/x"):
    return {
        "week": week,
        "format": "essay",
        "url": url,
        "title": title,
        "source": "Somewhere",
        "pitch": "worth your time",
        "rationale_tag": "topical",
        "curator": "mind",
        "verification": {"verified": True, "status": 200},
    }


def test_store_roundtrip_and_newest_first(fake_table):
    rs.put_horizon_pick(_pick("2026-W28", title="Older"))
    rs.put_horizon_pick(_pick("2026-W30", title="Newest"))
    rs.put_horizon_pick(_pick("2026-W29", title="Middle"))

    assert rs.get_horizon_pick("2026-W29")["title"] == "Middle"

    picks = rs.horizon_picks()
    assert [p["week"] for p in picks] == ["2026-W30", "2026-W29", "2026-W28"]  # ISO-week sorts chronologically
    assert rs.current_horizon_pick()["title"] == "Newest"


def test_store_overwrites_same_week(fake_table):
    rs.put_horizon_pick(_pick("2026-W30", title="First take"))
    rs.put_horizon_pick(_pick("2026-W30", title="Re-curated"))
    picks = rs.horizon_picks()
    assert len(picks) == 1 and picks[0]["title"] == "Re-curated"


def test_current_horizon_pick_empty(fake_table):
    assert rs.current_horizon_pick() is None


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — the MCP authoring + read tools
# ══════════════════════════════════════════════════════════════════════════════
def test_get_horizons_empty_state(fake_table):
    out = tr.tool_get_horizons({})
    assert out["current"] is None and out["past"] == [] and out["count"] == 0
    assert "note" in out


def test_curate_horizon_verified_commit_stores(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(
        {
            "url": "https://example.com/great-essay",
            "title": "A Great Essay",
            "format": "essay",
            "rationale_tag": "experiment-relevant",
            "pitch": "this reframes rest",
            "source": "The Marginalian",
            "week": "2026-W30",
            "dry_run": False,
        }
    )
    assert out["status"] == "committed"
    assert out["pick"]["curator"] == "mind"
    assert out["pick"]["verification"]["verified"] is True
    # actually persisted + readable through the read tool
    got = tr.tool_get_horizons({})
    assert got["current"]["title"] == "A Great Essay"


def test_curate_horizon_dry_run_verifies_but_does_not_store(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(
        {
            "url": "https://example.com/x",
            "title": "Preview Only",
            "format": "article",
            "rationale_tag": "topical",
            "dry_run": True,
        }
    )
    assert out["status"] == "preview"
    assert out["would_write"]["verification"]["verified"] is True
    assert rs.current_horizon_pick() is None  # nothing written on a dry run


def test_curate_horizon_unverified_is_rejected_not_stored(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _dead_fetch)
    out = tr.tool_curate_horizon(
        {
            "url": "https://example.com/fabricated",
            "title": "Does Not Resolve",
            "format": "article",
            "rationale_tag": "topical",
            "dry_run": False,  # even on a commit, a dead link never lands
        }
    )
    assert out.get("error_code") == "LINK_UNVERIFIED"
    assert rs.current_horizon_pick() is None  # fail-closed: not stored


def test_curate_horizon_rejects_bad_format(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(
        {"url": "https://example.com/x", "title": "T", "format": "tweet", "rationale_tag": "topical", "dry_run": False}
    )
    assert out.get("error_code") == "INVALID_ARG"


def test_curate_horizon_requires_url_and_title(fake_table):
    out = tr.tool_curate_horizon({"format": "article", "rationale_tag": "topical"})
    assert out.get("error_code") == "MISSING_ARG"


# ══════════════════════════════════════════════════════════════════════════════
# #1706 (epic #1686) — the Prescription follow-up hook: a pick threads into the
# coaching loop as a coach check-in item (question to Matthew, or cross-coach
# hand-off) instead of sitting inert. No follow-up is also valid.
# ══════════════════════════════════════════════════════════════════════════════
def _checkins(table, coach_id):
    """The CHECKIN# items surfaced under a coach, via the fake table."""
    got = table.query(KeyConditionExpression=Key("pk").eq(cc.checkin_pk(coach_id)) & Key("sk").begins_with("CHECKIN#"))
    return got.get("Items", [])


def test_followup_builder_question_surfaces_under_curating_coach():
    item = cc.build_prescription_followup_item(
        "2026-W30", "mind", {"type": "question", "text": "Did this land?"}, now="2026-07-26T00:00:00Z"
    )
    assert item["pk"] == "COACH#mind_coach"
    assert item["question"] == "Did this land?"
    assert item["status"] == cc.STATUS_OPEN
    assert item["prescription_week"] == "2026-W30"
    assert item["generated_by"] == "prescription_followup"
    assert "handoff_from" not in item


def test_followup_builder_handoff_surfaces_under_target_coach():
    item = cc.build_prescription_followup_item(
        "2026-W30", "mind", {"type": "handoff", "text": "Raise this in training", "to_coach": "training"}, now="x"
    )
    assert item["pk"] == "COACH#training_coach"  # surfaced under the TARGET coach
    assert item["handoff_from"] == "mind"
    assert item["prescription_followup_type"] == "handoff"


def test_followup_builder_returns_none_when_empty_or_typeless():
    assert cc.build_prescription_followup_item("2026-W30", "mind", None) is None
    assert cc.build_prescription_followup_item("2026-W30", "mind", {}) is None
    assert cc.build_prescription_followup_item("2026-W30", "mind", {"type": "question", "text": "  "}) is None
    assert cc.build_prescription_followup_item("2026-W30", "mind", {"type": "bogus", "text": "hi"}) is None
    # handoff without a target is not surfaceable
    assert cc.build_prescription_followup_item("2026-W30", "mind", {"type": "handoff", "text": "hi"}) is None


def _commit_args(**extra):
    base = {
        "url": "https://example.com/great-essay",
        "title": "A Great Essay",
        "format": "essay",
        "rationale_tag": "experiment-relevant",
        "week": "2026-W30",
        "dry_run": False,
    }
    base.update(extra)
    return base


def test_curate_with_question_writes_checkin_under_mind(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(_commit_args(follow_up_question="Did the essay reframe your rest?"))
    assert out["status"] == "committed" and out["follow_up_surfaced"] is True
    # recorded on the pick + cross-referenced
    assert out["pick"]["follow_up"]["type"] == "question"
    assert out["pick"]["follow_up"]["surfaced_checkin_sk"].startswith("CHECKIN#")
    # surfaced in the Mind coach's check-in queue
    items = _checkins(fake_table, "mind")
    assert len(items) == 1 and items[0]["question"] == "Did the essay reframe your rest?"
    assert _checkins(fake_table, "training") == []


def test_curate_handoff_writes_checkin_under_target(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(_commit_args(follow_up_question="Worth a training angle?", handoff_to_coach="training"))
    assert out["status"] == "committed" and out["follow_up_surfaced"] is True
    assert out["pick"]["follow_up"]["type"] == "handoff" and out["pick"]["follow_up"]["to_coach"] == "training"
    assert _checkins(fake_table, "training") and not _checkins(fake_table, "mind")
    assert _checkins(fake_table, "training")[0]["handoff_from"] == "mind"


def test_curate_handoff_to_unknown_coach_is_rejected(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(_commit_args(follow_up_question="x", handoff_to_coach="wizard"))
    assert out.get("error_code") == "INVALID_ARG"
    assert rs.current_horizon_pick() is None  # nothing written on the rejected call


def test_curate_dry_run_previews_followup_without_writing(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(_commit_args(dry_run=True, follow_up_question="preview?"))
    assert out["status"] == "preview"
    assert out["would_write"]["follow_up"]["text"] == "preview?"
    assert rs.current_horizon_pick() is None
    assert _checkins(fake_table, "mind") == []  # no check-in written on a dry run


def test_curate_without_followup_is_unchanged(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    out = tr.tool_curate_horizon(_commit_args())
    assert out["status"] == "committed" and out["follow_up_surfaced"] is False
    assert "follow_up" not in out["pick"]
    assert _checkins(fake_table, "mind") == []

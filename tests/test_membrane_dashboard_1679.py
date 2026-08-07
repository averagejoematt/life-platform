"""tests/test_membrane_dashboard_1679.py — the bidirectional membrane dashboard (#1679, epic #1668, S11).

Proves the acceptance criteria against the actual code (offline, fakes only):

  AC1  ONE payload unifies outbound (the BROADCAST_ORIGIN# ledger) and inbound
       (origin:human ingested posts) with the origin membrane as the visible join.
  AC2  it reads through the SHARED membrane helpers — the same query and the same
       predicate /api/broadcast uses — never a second copy that could drift.
  AC3  platform-origin echoes are reported as echoes and are NEVER counted as inbound.
  AC4  no vanity metrics: the payload carries no follower/like/reach/impression field.
  AC5  ADR-104 honest absence — a channel that is not wired reports state "dormant"
       (the absence of a pipe), distinct from a wired channel with no rows.
  AC6  the sensitivity gate's HELD set is not published — not the content, not the
       count, and not derivable by subtraction from any total the payload returns.
  AC7  fail-soft: a DDB error on one partition degrades that side, never the endpoint.

Plus the outbound-recording gap this story closes (#1670's ledger had no live writer):
  AC8  scripts/post_social.py records a BROADCAST_ORIGIN# row after a successful post,
       fail-soft, so "what I said → where it went" can ever be non-empty.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402


class _FakeTable:
    """Routes queries by the pk the KeyConditionExpression carries, so the ingested-post
    partitions and the BROADCAST_ORIGIN# ledger partitions return different rows (the
    real handler queries both)."""

    def __init__(self, by_pk=None, raise_on=()):
        self._by_pk = by_pk or {}
        self._raise_on = tuple(raise_on)

    @staticmethod
    def _literals(expr):
        """Every string operand in a boto3 KeyConditionExpression tree."""
        out = []
        stack = [expr]
        while stack:
            node = stack.pop()
            if isinstance(node, str):
                out.append(node)
            elif hasattr(node, "_values"):
                stack.extend(node._values)
        return out

    def query(self, **kw):
        literals = self._literals(kw.get("KeyConditionExpression"))
        for pk in self._raise_on:
            if any(lit.startswith(pk) for lit in literals):
                raise RuntimeError(f"simulated DDB failure on {pk}")
        for pk, items in self._by_pk.items():
            if pk in literals:
                return {"Items": list(items)}
        return {"Items": []}


def _body(resp):
    return json.loads(resp["body"])


def _post(post_id, *, origin="human", sensitivity="cleared", channel="youtube", date="2026-08-01"):
    return {
        "sk": f"DATE#{date}#{post_id}",
        "date": date,
        "post_id": post_id,
        "channel": channel,
        "title": f"post {post_id}",
        "description": "",
        "thumbnail_url": f"https://img.example/{post_id}.jpg",
        "url": f"https://youtube.com/{post_id}",
        "origin": origin,
        "sensitivity_status": sensitivity,
    }


def _ledger(post_id, channel="bluesky", recorded_at="2026-08-05T12:00:00Z"):
    return {
        "pk": f"BROADCAST_ORIGIN#{channel}",
        "sk": f"POST#{post_id}",
        "channel": channel,
        "post_id": post_id,
        "url": f"https://bsky.app/profile/x/post/{post_id}",
        "origin": "platform",
        "recorded_at": recorded_at,
    }


INGEST_PK = "USER#matthew#SOURCE#youtube"
LEDGER_PK = "BROADCAST_ORIGIN#bluesky"


# ── AC1: one payload, all three stages ────────────────────────────────────────────────


def test_payload_unifies_outbound_inbound_and_the_membrane(monkeypatch):
    monkeypatch.setattr(
        social,
        "table",
        _FakeTable({LEDGER_PK: [_ledger("aaa")], INGEST_PK: [_post("v1")]}),
    )
    body = _body(social.handle_membrane())
    assert set(body) >= {"as_of_date", "outbound", "inbound", "membrane"}
    assert body["outbound"]["total"] == 1
    assert body["inbound"]["visible"] == 1
    assert "echoes_excluded" in body["membrane"]


def test_outbound_records_carry_channel_url_and_recorded_at(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable({LEDGER_PK: [_ledger("aaa")]}))
    post = _body(social.handle_membrane())["outbound"]["posts"][0]
    assert post["id"] == "aaa"
    assert post["channel"] == "bluesky"
    assert post["url"].startswith("https://bsky.app/")
    assert post["recorded_at"] == "2026-08-05T12:00:00Z"


# ── AC2: shared helpers, never a second membrane ──────────────────────────────────────


def test_inbound_reads_through_the_shared_membrane_predicate(monkeypatch):
    """The dashboard must not re-implement the gate: forcing _is_broadcast_visible to
    reject everything must empty the dashboard's inbound side too."""
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: [_post("v1"), _post("v2")]}))
    assert _body(social.handle_membrane())["inbound"]["visible"] == 2
    monkeypatch.setattr(social, "_is_broadcast_visible", lambda row: False)
    assert _body(social.handle_membrane())["inbound"]["visible"] == 0


def test_visible_rows_helper_is_the_source_rows_helper_plus_the_gate(monkeypatch):
    """_membrane_visible_rows must be a pure filter over _membrane_source_rows — one
    query, one gate. If a second query appeared, stubbing the source helper would not
    empty the visible set."""
    monkeypatch.setattr(social, "_membrane_source_rows", lambda: [])
    assert social._membrane_visible_rows() == []


def test_dashboard_and_broadcast_feed_agree_on_what_counts_as_voice(monkeypatch):
    rows = [_post("v1"), _post("v2", origin="platform"), _post("v3", sensitivity="pending")]
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: rows}))
    feed_ids = {c["id"] for c in _body(social.handle_broadcast())["items"]}
    dash_ids = {c["id"] for c in _body(social.handle_membrane())["inbound"]["items"]}
    assert feed_ids == dash_ids == {"v1"}


# ── AC3: echoes are echoes, never "what came back" ────────────────────────────────────


def test_platform_echoes_are_counted_separately_and_never_as_inbound(monkeypatch):
    rows = [_post("v1"), _post("v2", origin="platform"), _post("v3", origin="platform")]
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: rows}))
    body = _body(social.handle_membrane())
    assert body["membrane"]["echoes_excluded"] == 2
    assert body["inbound"]["visible"] == 1
    assert {c["id"] for c in body["inbound"]["items"]} == {"v1"}


def test_unstamped_row_follows_the_documented_membrane_default(monkeypatch):
    """#1670's origin default, pinned where the dashboard depends on it.

    The two provenance signals (ledger cross-reference and self-backlink) are applied at
    INGEST time by classify_post_origin, which STAMPS `origin` on the row. The read side
    — is_displayable_voice — only reads that stamp, and treats a missing one as human on
    purpose ("a legacy/unstamped row is a genuine human post, never a platform echo").
    The dashboard inherits that default rather than re-deriving provenance at serve time,
    so an unstamped row counts as voice and is NOT reported as an echo. Changing this
    should be a deliberate membrane decision, not a quiet dashboard-side divergence.
    """
    row = _post("v9")
    row.pop("origin")
    row["url"] = "https://averagejoematt.com/story/chronicle/"
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: [row]}))
    body = _body(social.handle_membrane())
    assert body["membrane"]["echoes_excluded"] == 0
    assert body["inbound"]["visible"] == 1
    # And the same row stamped platform at ingest IS an echo.
    row["origin"] = "platform"
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: [row]}))
    body = _body(social.handle_membrane())
    assert body["membrane"]["echoes_excluded"] == 1
    assert body["inbound"]["visible"] == 0


# ── AC4: no vanity metrics (#1402's no-gloss ethos) ───────────────────────────────────


def test_payload_carries_no_engagement_metric(monkeypatch):
    monkeypatch.setattr(
        social,
        "table",
        _FakeTable({LEDGER_PK: [_ledger("aaa")], INGEST_PK: [_post("v1")]}),
    )
    blob = json.dumps(_body(social.handle_membrane())).lower()
    for banned in ("follower", "likes", "like_count", "reach", "impression", "views", "engagement_rate"):
        assert banned not in blob, f"vanity metric {banned!r} leaked into /api/membrane"


# ── AC5: honest absence — dormant is not zero (ADR-104) ───────────────────────────────


def test_unwired_inbound_channel_reports_dormant_not_zero(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable({}))
    monkeypatch.setattr(social, "_inbound_channel_live", lambda s: False)
    inbound = _body(social.handle_membrane())["inbound"]
    assert inbound["state"] == "dormant"
    assert all(c["state"] == "dormant" and c["live"] is False for c in inbound["channels"])


def test_wired_but_quiet_inbound_channel_reports_live(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable({}))
    monkeypatch.setattr(social, "_inbound_channel_live", lambda s: True)
    inbound = _body(social.handle_membrane())["inbound"]
    assert inbound["state"] == "live"
    assert inbound["visible"] == 0


def test_inbound_liveness_is_read_from_the_source_registry(monkeypatch):
    """The live/dormant facet must come from the canonical registry, not be hand-stated
    here (the #2003 drift class)."""
    monkeypatch.setattr(social, "SOURCE_REGISTRY", {"youtube": {"active_api": True}})
    assert social._inbound_channel_live("youtube") is True
    monkeypatch.setattr(social, "SOURCE_REGISTRY", {"youtube": {"active_api": False}})
    assert social._inbound_channel_live("youtube") is False
    assert social._inbound_channel_live("not_a_source") is False


def test_empty_outbound_ledger_is_reported_as_empty_state(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable({}))
    outbound = _body(social.handle_membrane())["outbound"]
    assert outbound["state"] == "empty"
    assert outbound["total"] == 0
    assert outbound["posts"] == []


# ── AC6: the held set is never published, nor derivable ───────────────────────────────


def test_held_posts_are_neither_shown_nor_counted(monkeypatch):
    rows = [_post("v1"), _post("v2", sensitivity="flagged"), _post("v3", sensitivity="pending")]
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: rows}))
    body = _body(social.handle_membrane())
    blob = json.dumps(body)
    assert "v2" not in blob and "v3" not in blob
    assert "flagged" not in blob and "pending" not in blob
    # No raw ingested total anywhere: with one, held = total - visible - echoes.
    assert "total" not in body["inbound"]
    assert all("ingested" not in c for c in body["inbound"]["channels"])
    assert body["inbound"]["visible"] == 1 and body["membrane"]["echoes_excluded"] == 0


def test_per_channel_inbound_count_is_the_visible_count_only(monkeypatch):
    rows = [_post("v1"), _post("v2", sensitivity="flagged"), _post("v3", origin="platform")]
    monkeypatch.setattr(social, "table", _FakeTable({INGEST_PK: rows}))
    chan = _body(social.handle_membrane())["inbound"]["channels"][0]
    assert chan["visible"] == 1


# ── AC7: fail-soft ────────────────────────────────────────────────────────────────────


def test_ledger_query_failure_degrades_only_the_outbound_side(monkeypatch):
    monkeypatch.setattr(
        social,
        "table",
        _FakeTable({INGEST_PK: [_post("v1")]}, raise_on=("BROADCAST_ORIGIN#",)),
    )
    body = _body(social.handle_membrane())
    assert body["outbound"]["total"] == 0
    assert body["inbound"]["visible"] == 1


def test_ingest_query_failure_degrades_only_the_inbound_side(monkeypatch):
    monkeypatch.setattr(
        social,
        "table",
        _FakeTable({LEDGER_PK: [_ledger("aaa")]}, raise_on=(INGEST_PK,)),
    )
    body = _body(social.handle_membrane())
    assert body["outbound"]["total"] == 1
    assert body["inbound"]["visible"] == 0


def test_endpoint_is_registered_and_read_only():
    from web import site_api_lambda

    assert site_api_lambda.ROUTES["/api/membrane"] is social.handle_membrane
    assert "/api/membrane" not in site_api_lambda._SIMPLE_ROUTES


# ── AC8: the outbound path actually records (the gap this story closes) ───────────────


def _load_post_social():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    import post_social

    return post_social


def test_post_social_derives_the_post_id_from_the_at_uri():
    ps = _load_post_social()
    assert ps.bluesky_post_id({"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz"}) == "3kxyz"
    assert ps.bluesky_post_id({}) == ""
    assert ps.bluesky_post_id(None) == ""


class _FakeDDBResource:
    """Stands in for boto3.resource('dynamodb') so the real record_outbound path runs
    end-to-end without ever touching AWS."""

    def __init__(self, sink):
        self._sink = sink

    def Table(self, name):  # noqa: N802 — boto3's own casing
        self._sink["table_name"] = name
        sink = self._sink

        class _T:
            def put_item(self, Item):  # noqa: N803 — boto3's own casing
                sink["item"] = Item

        return _T()


def test_post_social_records_the_broadcast_origin_row(monkeypatch):
    """A successful post must land a BROADCAST_ORIGIN# row — without it the membrane
    cannot recognise the platform's own words coming back, and the dashboard's outbound
    side stays empty forever. Runs the REAL record_outbound over a fake resource."""
    import boto3

    ps = _load_post_social()
    sink: dict = {}
    monkeypatch.setattr(boto3, "resource", lambda *a, **k: _FakeDDBResource(sink))

    assert ps.record_outbound("bluesky", "3kxyz", "https://bsky.app/profile/x/post/3kxyz") is True
    assert sink["table_name"] == "life-platform"
    item = sink["item"]
    assert item["pk"] == "BROADCAST_ORIGIN#bluesky"
    assert item["sk"] == "POST#3kxyz"
    assert item["origin"] == "platform"
    assert item["url"] == "https://bsky.app/profile/x/post/3kxyz"


def test_post_social_ledger_write_is_fail_soft(monkeypatch, capsys):
    """The post is already sent by the time this runs: a provenance failure must warn,
    never raise, and never turn a successful post into a failed run."""
    import boto3

    ps = _load_post_social()

    def _boom(*a, **k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(boto3, "resource", _boom)
    assert ps.record_outbound("bluesky", "3kxyz", "https://bsky.app/x") is False
    assert "NOT written" in capsys.readouterr().out

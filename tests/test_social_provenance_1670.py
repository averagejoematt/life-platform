"""tests/test_social_provenance_1670.py — the provenance membrane (#1670, epic #1668).

The loop-breaker: inbound ingestion must never re-ingest / re-display / re-broadcast the
platform's OWN outbound posts. These tests pin the deterministic origin classification
(both signals, both kinds of fixture) and the read-side exclusion the membrane enforces.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import social_provenance as prov  # noqa: E402


# ── A faithful mini-ledger table (get_item / put_item by exact key) ──────────────
class _FakeLedgerTable:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item):
        self.rows[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key):
        item = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}


class _BrokenTable:
    def get_item(self, Key):
        raise RuntimeError("simulated DDB failure")


# ── The core classifier: a pure decision table ───────────────────────────────────
def test_classify_origin_decision_table():
    assert prov.classify_origin(in_ledger=False, self_backlink=False) == prov.ORIGIN_HUMAN
    assert prov.classify_origin(in_ledger=True, self_backlink=False) == prov.ORIGIN_PLATFORM
    assert prov.classify_origin(in_ledger=False, self_backlink=True) == prov.ORIGIN_PLATFORM
    assert prov.classify_origin(in_ledger=True, self_backlink=True) == prov.ORIGIN_PLATFORM


# ── Self-backlink signal (secondary; needs no AWS) ───────────────────────────────
def test_self_backlink_detected_across_fields():
    assert prov.has_self_backlink("check my site averagejoematt.com/story") is True
    assert prov.has_self_backlink("nothing here", "https://averagejoematt.com/x") is True
    assert prov.has_self_backlink("AVERAGEJOEMATT.COM") is True  # case-insensitive
    assert prov.has_self_backlink("just a normal caption", "https://youtube.com/watch?v=x") is False
    assert prov.has_self_backlink("", None) is False


def test_self_linking_post_caught_with_empty_ledger():
    """A platform echo that links back to the site is caught even when the ledger is
    empty (ledger write failed / predates #1402) — table=None means ledger not consulted."""
    origin = prov.classify_post_origin(
        None,
        channel="youtube",
        post_id="vid123",
        text_fields=["New dispatch up on averagejoematt.com"],
    )
    assert origin == prov.ORIGIN_PLATFORM


def test_plain_human_post_is_human_with_empty_ledger():
    origin = prov.classify_post_origin(
        None,
        channel="youtube",
        post_id="vid456",
        text_fields=["A day in the gym", "https://youtube.com/watch?v=vid456"],
    )
    assert origin == prov.ORIGIN_HUMAN


# ── The outbound-broadcast ledger (primary signal) ───────────────────────────────
def test_ledger_round_trip_marks_platform():
    table = _FakeLedgerTable()
    prov.record_broadcast_origin(table, "youtube", "vid789", url="https://youtube.com/watch?v=vid789")
    assert prov.is_in_broadcast_ledger(table, "youtube", "vid789") is True
    # A post recorded by the outbound path is classified platform even with no self-link.
    origin = prov.classify_post_origin(table, channel="youtube", post_id="vid789", text_fields=["neutral caption"])
    assert origin == prov.ORIGIN_PLATFORM
    # A different post absent from the ledger and not self-linking is human.
    assert prov.is_in_broadcast_ledger(table, "youtube", "other") is False
    assert prov.classify_post_origin(table, channel="youtube", post_id="other", text_fields=["hi"]) == prov.ORIGIN_HUMAN


def test_ledger_row_shape():
    table = _FakeLedgerTable()
    row = prov.record_broadcast_origin(table, "x", "tweet1", url="https://x.com/i/status/tweet1")
    assert row["pk"] == "BROADCAST_ORIGIN#x"
    assert row["sk"] == "POST#tweet1"
    assert row["origin"] == prov.ORIGIN_PLATFORM
    assert row["url"] == "https://x.com/i/status/tweet1"
    assert "recorded_at" in row


def test_ledger_lookup_is_fail_open():
    """A DDB read error must not force a post to platform — return False, let the
    self-backlink signal decide. (Fail-open: a broken lookup can't hide human posts.)"""
    assert prov.is_in_broadcast_ledger(_BrokenTable(), "youtube", "vid") is False


# ── Read-side exclusion (S3 enrichment, S4 feed, re-broadcast) ───────────────────
def test_platform_post_excluded_everywhere():
    platform_post = {"origin": prov.ORIGIN_PLATFORM, "post_id": "p1"}
    human_post = {"origin": prov.ORIGIN_HUMAN, "post_id": "h1"}
    unstamped = {"post_id": "u1"}  # legacy row with no origin — treated as human

    for pred in (prov.is_enrichable, prov.is_displayable_voice, prov.is_rebroadcast_candidate, prov.is_human_origin):
        assert pred(platform_post) is False, pred.__name__
        assert pred(human_post) is True, pred.__name__
        assert pred(unstamped) is True, pred.__name__

    assert prov.is_platform_origin(platform_post) is True
    assert prov.is_platform_origin(human_post) is False


def test_filter_human_drops_only_platform():
    posts = [
        {"origin": prov.ORIGIN_HUMAN, "post_id": "h1"},
        {"origin": prov.ORIGIN_PLATFORM, "post_id": "p1"},
        {"post_id": "u1"},
    ]
    kept = prov.filter_human(posts)
    assert [p["post_id"] for p in kept] == ["h1", "u1"]


def test_query_filter_expression_excludes_platform():
    expr = prov.human_origin_filter_expression()
    # boto3 Attr("origin").ne("platform") — assert it's the not-equal on origin.
    assert expr.get_expression()["operator"] == "<>"
    assert expr.get_expression()["values"][1] == prov.ORIGIN_PLATFORM

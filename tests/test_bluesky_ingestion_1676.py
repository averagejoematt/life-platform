"""tests/test_bluesky_ingestion_1676.py — inbound social spine, Bluesky (#1676, epic #1668).

Mirrors tests/test_youtube_ingestion_1669.py: because the source rides a FREE public
AppView API, the transform is proven end-to-end offline against a fixture feed response
(parse -> date-filter -> framework-shaped records with the suffixed sk and stamped
`channel`/`origin` provenance, #1670). A true live fetch still needs the owner-supplied
handle — that gap is asserted (placeholder -> no fetch), not faked.
"""

import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

import bluesky_lambda as bs  # noqa: E402
from privacy import social_provenance as prov  # noqa: E402

# A fixture author-feed response: two posts on 2026-07-20 PT (one plain/human, one whose
# embed links back to averagejoematt.com -> a platform echo), one on 2026-07-19 PT, and one
# repost (must be dropped).
_FIXTURE_FEED = {
    "feed": [
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/aaaaaaaaaaa",
                "cid": "cid1",
                "author": {"handle": "mattsusername.bsky.social"},
                "record": {"text": "Squats and a long walk. No links here.", "createdAt": "2026-07-20T18:00:00.000Z"},
                "likeCount": 12,
                "repostCount": 1,
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/bbbbbbbbbbb",
                "cid": "cid2",
                "author": {"handle": "mattsusername.bsky.social"},
                "record": {
                    "text": "New dashboard is live",
                    "createdAt": "2026-07-20T20:30:00.000Z",
                    "embed": {"external": {"uri": "https://averagejoematt.com/cockpit"}},
                },
            }
        },
        {
            "post": {
                "uri": "at://did:plc:test/app.bsky.feed.post/ccccccccccc",
                "cid": "cid3",
                "author": {"handle": "mattsusername.bsky.social"},
                "record": {"text": "A rainy ruck.", "createdAt": "2026-07-19T17:00:00.000Z"},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:other/app.bsky.feed.post/ddddddddddd",
                "cid": "cid4",
                "author": {"handle": "someoneelse.bsky.social"},
                "record": {"text": "not mine", "createdAt": "2026-07-20T12:00:00.000Z"},
            },
            "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
        },
    ]
}


def _offline(monkeypatch):
    """Force offline, deterministic classification (empty ledger, no S3, no Bedrock).

    Also stubs the #1673 sensitivity gate's off-topic classifier to a confident on-topic
    verdict so transform() stays fully offline while still exercising the real gate.
    """
    monkeypatch.setattr(bs, "_ledger_table", lambda: None)
    monkeypatch.setattr(bs, "_S3_BUCKET", "")
    monkeypatch.setattr(bs.gate, "bedrock_offtopic_classifier", lambda text: bs.gate.OfftopicResult(True, 0.95))


# ── Handle resolution (the owner input) ─────────────────────────────────────
def test_authenticate_reads_handle_from_secret():
    creds = bs.authenticate({"handle": "fromsecret.bsky.social"})
    assert creds["handle"] == "fromsecret.bsky.social"


def test_authenticate_reads_handle_from_env(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "fromenv.bsky.social")
    creds = bs.authenticate({})
    assert creds["handle"] == "fromenv.bsky.social"


def test_authenticate_falls_to_placeholder(monkeypatch):
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    # Secret unprovisioned → boto3 lookup raises → stays on the placeholder (no guess).
    monkeypatch.setattr(bs.boto3, "client", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no secret")))
    creds = bs.authenticate({})
    assert creds["handle"] == bs._PLACEHOLDER_HANDLE


# ── Fetch gating: no handle → no live fetch (the honest gap) ─────────────────
def test_fetch_day_noop_without_handle():
    assert bs.fetch_day({"handle": bs._PLACEHOLDER_HANDLE}, "2026-07-20") is None
    assert bs.fetch_day({}, "2026-07-20") is None


# ── Feed parse ────────────────────────────────────────────────────────────────
def test_parse_entries_drops_reposts():
    entries = bs._parse_entries(_FIXTURE_FEED["feed"], "mattsusername.bsky.social")
    assert [e["post_id"] for e in entries] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    a = entries[0]
    assert a["text"] == "Squats and a long walk. No links here."
    assert a["url"] == "https://bsky.app/profile/mattsusername.bsky.social/post/aaaaaaaaaaa"
    assert a["embed_url"] == ""
    assert entries[1]["embed_url"] == "https://averagejoematt.com/cockpit"


# ── Fetch-day date filtering (feed monkeypatched — no network) ────────────────────
def test_fetch_day_filters_to_pacific_date(monkeypatch):
    monkeypatch.setattr(bs, "_fetch_feed", lambda handle: _FIXTURE_FEED["feed"])
    raw = bs.fetch_day({"handle": "mattsusername.bsky.social"}, "2026-07-20")
    assert raw is not None
    assert {e["post_id"] for e in raw["entries"]} == {"aaaaaaaaaaa", "bbbbbbbbbbb"}
    # A day with no posts returns None (framework treats as no_data).
    assert bs.fetch_day({"handle": "mattsusername.bsky.social"}, "2026-07-18") is None


# ── Transform → framework records, with provenance stamped (#1676 + #1670) ───────
def test_transform_writes_suffixed_provenance_records(monkeypatch):
    _offline(monkeypatch)
    entries = bs._parse_entries(_FIXTURE_FEED["feed"], "mattsusername.bsky.social")[:2]
    raw = {"date": "2026-07-20", "handle": "mattsusername.bsky.social", "entries": entries}
    records = bs.transform(raw, "2026-07-20")
    assert len(records) == 2
    by_id = {r["post_id"]: r for r in records}

    human = by_id["aaaaaaaaaaa"]
    assert human["sk_suffix"] == "#aaaaaaaaaaa"  # → sk=DATE#2026-07-20#aaaaaaaaaaa
    assert human["source"] == "bluesky"
    assert human["channel"] == "bluesky"
    assert human["origin"] == prov.ORIGIN_HUMAN
    assert human["like_count"] == Decimal("12")
    assert isinstance(human["like_count"], Decimal)
    # #1673: a clean, on-topic human post is stamped cleared → eligible for the S4 feed.
    assert human["sensitivity_status"] == bs.gate.SENSITIVITY_CLEARED

    # The self-linking post (embed → averagejoematt.com) is stamped a platform echo even
    # with an empty ledger (#1670).
    platform = by_id["bbbbbbbbbbb"]
    assert platform["sk_suffix"] == "#bbbbbbbbbbb"
    assert platform["origin"] == prov.ORIGIN_PLATFORM
    # A platform echo is excluded by the membrane, so the gate never stamps it (#1673).
    assert "sensitivity_status" not in platform


def test_transform_empty_when_no_entries(monkeypatch):
    _offline(monkeypatch)
    assert bs.transform({"entries": []}, "2026-07-20") == []

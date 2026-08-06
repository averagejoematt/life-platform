"""tests/test_mastodon_ingestion_1676.py — inbound social spine, Mastodon (#1676, epic #1668).

Mirrors tests/test_youtube_ingestion_1669.py / test_bluesky_ingestion_1676.py: because the
source rides each instance's FREE public REST API, the transform is proven end-to-end
offline against fixture responses (account lookup + statuses -> date-filter ->
framework-shaped records with the suffixed sk and stamped `channel`/`origin` provenance,
#1670). A true live fetch still needs the owner-supplied instance/handle — that gap is
asserted (placeholder -> no fetch), not faked.
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

import mastodon_lambda as md  # noqa: E402
from privacy import social_provenance as prov  # noqa: E402

# A fixture statuses response: two public posts on 2026-07-20 PT (one plain/human, one
# whose HTML content links back to averagejoematt.com -> a platform echo), one on
# 2026-07-19 PT, a non-public one (must be dropped), and a boost (must be dropped).
_FIXTURE_STATUSES = [
    {
        "id": "111",
        "created_at": "2026-07-20T18:00:00.000Z",
        "content": "<p>Squats and a long walk. No links here.</p>",
        "url": "https://mastodon.social/@mattsusername/111",
        "visibility": "public",
        "reblog": None,
        "account": {"username": "mattsusername"},
        "favourites_count": 5,
        "reblogs_count": 2,
    },
    {
        "id": "222",
        "created_at": "2026-07-20T20:30:00.000Z",
        "content": '<p>New dashboard is live: <a href="https://averagejoematt.com/cockpit">link</a></p>',
        "url": "https://mastodon.social/@mattsusername/222",
        "visibility": "public",
        "reblog": None,
        "account": {"username": "mattsusername"},
    },
    {
        "id": "333",
        "created_at": "2026-07-19T17:00:00.000Z",
        "content": "<p>A rainy ruck.</p>",
        "url": "https://mastodon.social/@mattsusername/333",
        "visibility": "public",
        "reblog": None,
        "account": {"username": "mattsusername"},
    },
    {
        "id": "444",
        "created_at": "2026-07-20T13:00:00.000Z",
        "content": "<p>private thought</p>",
        "url": "https://mastodon.social/@mattsusername/444",
        "visibility": "unlisted",
        "reblog": None,
        "account": {"username": "mattsusername"},
    },
    {
        "id": "555",
        "created_at": "2026-07-20T14:00:00.000Z",
        "content": "<p>someone else's post</p>",
        "url": "https://mastodon.social/@someoneelse/555",
        "visibility": "public",
        "reblog": {"id": "999"},
        "account": {"username": "mattsusername"},
    },
]


def _offline(monkeypatch):
    """Force offline, deterministic classification (empty ledger, no S3, no Bedrock)."""
    monkeypatch.setattr(md, "_ledger_table", lambda: None)
    monkeypatch.setattr(md, "_S3_BUCKET", "")
    monkeypatch.setattr(md.gate, "bedrock_offtopic_classifier", lambda text: md.gate.OfftopicResult(True, 0.95))


# ── Instance/handle resolution (the owner input) ─────────────────────────────────────
def test_authenticate_reads_instance_and_handle_from_secret():
    creds = md.authenticate({"instance": "mastodon.social", "handle": "fromsecret"})
    assert creds == {"instance": "mastodon.social", "handle": "fromsecret"}


def test_authenticate_reads_instance_and_handle_from_env(monkeypatch):
    monkeypatch.setenv("MASTODON_INSTANCE", "fromenv.social")
    monkeypatch.setenv("MASTODON_HANDLE", "fromenv")
    creds = md.authenticate({})
    assert creds == {"instance": "fromenv.social", "handle": "fromenv"}


def test_authenticate_falls_to_placeholder(monkeypatch):
    monkeypatch.delenv("MASTODON_INSTANCE", raising=False)
    monkeypatch.delenv("MASTODON_HANDLE", raising=False)
    # Secret unprovisioned → boto3 lookup raises → stays on the placeholders (no guess).
    monkeypatch.setattr(md.boto3, "client", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no secret")))
    creds = md.authenticate({})
    assert creds["instance"] == md._PLACEHOLDER_INSTANCE
    assert creds["handle"] == md._PLACEHOLDER_HANDLE


# ── Fetch gating: no instance/handle → no live fetch (the honest gap) ─────────────────
def test_fetch_day_noop_without_instance_or_handle():
    assert md.fetch_day({"instance": md._PLACEHOLDER_INSTANCE, "handle": "x"}, "2026-07-20") is None
    assert md.fetch_day({"instance": "mastodon.social", "handle": md._PLACEHOLDER_HANDLE}, "2026-07-20") is None
    assert md.fetch_day({}, "2026-07-20") is None


# ── HTML stripping + status parse ────────────────────────────────────────────────────
def test_strip_html():
    assert md._strip_html("<p>Hello &amp; welcome</p>") == "Hello & welcome"


def test_parse_entries_drops_non_public_and_boosts():
    entries = md._parse_entries(_FIXTURE_STATUSES)
    assert [e["post_id"] for e in entries] == ["111", "222", "333"]
    a = entries[0]
    assert a["text"] == "Squats and a long walk. No links here."
    assert a["url"] == "https://mastodon.social/@mattsusername/111"
    assert "averagejoematt.com" not in a["raw_content"]
    b = entries[1]
    assert "averagejoematt.com" in b["raw_content"]
    assert "averagejoematt.com" not in b["text"]  # tags stripped, the link text alone wouldn't show the domain


# ── Fetch-day date filtering (statuses monkeypatched — no network) ────────────────────
def test_fetch_day_filters_to_pacific_date(monkeypatch):
    monkeypatch.setattr(md, "_fetch_statuses", lambda instance, handle: _FIXTURE_STATUSES)
    raw = md.fetch_day({"instance": "mastodon.social", "handle": "mattsusername"}, "2026-07-20")
    assert raw is not None
    assert {e["post_id"] for e in raw["entries"]} == {"111", "222"}
    # A day with no statuses returns None (framework treats as no_data).
    assert md.fetch_day({"instance": "mastodon.social", "handle": "mattsusername"}, "2026-07-18") is None


# ── Account resolution + statuses fetch (network stubbed) ─────────────────────────────
def test_fetch_statuses_resolves_account_then_fetches(monkeypatch):
    calls = []

    def fake_get_json(url):
        calls.append(url)
        if "lookup" in url:
            return {"id": "42"}
        return _FIXTURE_STATUSES

    monkeypatch.setattr(md, "_get_json", fake_get_json)
    md._account_id_cache.clear()
    md._statuses_cache.clear()
    statuses = md._fetch_statuses("mastodon.social", "mattsusername")
    assert statuses == _FIXTURE_STATUSES
    assert any("lookup" in c for c in calls)
    assert any("/statuses" in c for c in calls)
    # Cached on the second call — no new requests.
    calls.clear()
    md._fetch_statuses("mastodon.social", "mattsusername")
    assert calls == []


# ── Transform → framework records, with provenance stamped (#1676 + #1670) ───────
def test_transform_writes_suffixed_provenance_records(monkeypatch):
    _offline(monkeypatch)
    entries = md._parse_entries(_FIXTURE_STATUSES)[:2]
    raw = {"date": "2026-07-20", "instance": "mastodon.social", "handle": "mattsusername", "entries": entries}
    records = md.transform(raw, "2026-07-20")
    assert len(records) == 2
    by_id = {r["post_id"]: r for r in records}

    human = by_id["111"]
    assert human["sk_suffix"] == "#111"  # → sk=DATE#2026-07-20#111
    assert human["source"] == "mastodon"
    assert human["channel"] == "mastodon"
    assert human["origin"] == prov.ORIGIN_HUMAN
    assert human["favourites_count"] == Decimal("5")
    assert isinstance(human["favourites_count"], Decimal)
    assert "raw_content" not in human  # only the stripped text persists to DDB
    # #1673: a clean, on-topic human post is stamped cleared → eligible for the S4 feed.
    assert human["sensitivity_status"] == md.gate.SENSITIVITY_CLEARED

    # The self-linking post (HTML <a href> → averagejoematt.com) is stamped a platform
    # echo even with an empty ledger (#1670) — caught via raw_content, not the stripped text.
    platform = by_id["222"]
    assert platform["sk_suffix"] == "#222"
    assert platform["origin"] == prov.ORIGIN_PLATFORM
    # A platform echo is excluded by the membrane, so the gate never stamps it (#1673).
    assert "sensitivity_status" not in platform


def test_transform_empty_when_no_entries(monkeypatch):
    _offline(monkeypatch)
    assert md.transform({"entries": []}, "2026-07-20") == []

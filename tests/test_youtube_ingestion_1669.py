"""tests/test_youtube_ingestion_1669.py — inbound social spine, YouTube (#1669, epic #1668).

Because the source rides a FREE keyless RSS feed, the transform is proven end-to-end
offline against a fixture feed: parse → date-filter → framework-shaped records with the
suffixed sk and stamped `channel`/`origin` provenance (#1670). A true live fetch still
needs the owner-supplied channel id — that gap is asserted (placeholder → no fetch), not
faked.
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

import social_provenance as prov  # noqa: E402
import youtube_lambda as yt  # noqa: E402

# A fixture channel feed: two videos on 2026-07-20 PT (one plain/human, one that links
# back to averagejoematt.com → a platform echo), one on 2026-07-19 PT.
_FIXTURE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Average Joe Matt</title>
  <entry>
    <id>yt:video:AAAAAAAAAAA</id>
    <yt:videoId>AAAAAAAAAAA</yt:videoId>
    <yt:channelId>UCtest</yt:channelId>
    <title>Leg day, week 3</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/>
    <author><name>Average Joe Matt</name></author>
    <published>2026-07-20T18:00:00+00:00</published>
    <updated>2026-07-20T18:05:00+00:00</updated>
    <media:group>
      <media:title>Leg day, week 3</media:title>
      <media:description>Squats and a long walk. No links here.</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:statistics views="1234"/>
      </media:community>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:BBBBBBBBBBB</id>
    <yt:videoId>BBBBBBBBBBB</yt:videoId>
    <yt:channelId>UCtest</yt:channelId>
    <title>New dashboard is live</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=BBBBBBBBBBB"/>
    <author><name>Average Joe Matt</name></author>
    <published>2026-07-20T20:30:00+00:00</published>
    <updated>2026-07-20T20:35:00+00:00</updated>
    <media:group>
      <media:title>New dashboard is live</media:title>
      <media:description>Full write-up at averagejoematt.com/cockpit</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/BBBBBBBBBBB/hqdefault.jpg" width="480" height="360"/>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:CCCCCCCCCCC</id>
    <yt:videoId>CCCCCCCCCCC</yt:videoId>
    <yt:channelId>UCtest</yt:channelId>
    <title>Yesterday's ruck</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=CCCCCCCCCCC"/>
    <author><name>Average Joe Matt</name></author>
    <published>2026-07-19T17:00:00+00:00</published>
    <updated>2026-07-19T17:05:00+00:00</updated>
    <media:group>
      <media:title>Yesterday's ruck</media:title>
      <media:description>A rainy ruck.</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/CCCCCCCCCCC/hqdefault.jpg" width="480" height="360"/>
    </media:group>
  </entry>
</feed>
"""


def _offline(monkeypatch):
    """Force offline, deterministic origin classification (empty ledger, no S3)."""
    monkeypatch.setattr(yt, "_ledger_table", lambda: None)
    monkeypatch.setattr(yt, "_S3_BUCKET", "")


# ── Channel-id resolution (the owner input) ─────────────────────────────────────
def test_authenticate_reads_channel_id_from_secret():
    creds = yt.authenticate({"channel_id": "UCfromsecret"})
    assert creds["channel_id"] == "UCfromsecret"


def test_authenticate_reads_channel_id_from_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UCfromenv")
    creds = yt.authenticate({})
    assert creds["channel_id"] == "UCfromenv"


def test_authenticate_falls_to_placeholder(monkeypatch):
    monkeypatch.delenv("YOUTUBE_CHANNEL_ID", raising=False)
    # Secret unprovisioned → boto3 lookup raises → stays on the placeholder (no guess).
    monkeypatch.setattr(yt.boto3, "client", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no secret")))
    creds = yt.authenticate({})
    assert creds["channel_id"] == yt._PLACEHOLDER_CHANNEL_ID


# ── Fetch gating: no channel id → no live fetch (the honest gap) ─────────────────
def test_fetch_day_noop_without_channel_id():
    assert yt.fetch_day({"channel_id": yt._PLACEHOLDER_CHANNEL_ID}, "2026-07-20") is None
    assert yt.fetch_day({}, "2026-07-20") is None


# ── RSS parse ────────────────────────────────────────────────────────────────────
def test_parse_entries():
    entries = yt._parse_entries(_FIXTURE_FEED)
    assert [e["video_id"] for e in entries] == ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
    a = entries[0]
    assert a["title"] == "Leg day, week 3"
    assert a["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert a["thumbnail_url"] == "https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg"
    assert a["views"] == 1234
    assert entries[1]["views"] is None  # no statistics element


# ── Fetch-day date filtering (feed monkeypatched — no network) ────────────────────
def test_fetch_day_filters_to_pacific_date(monkeypatch):
    monkeypatch.setattr(yt, "_fetch_feed", lambda cid: _FIXTURE_FEED)
    raw = yt.fetch_day({"channel_id": "UCtest"}, "2026-07-20")
    assert raw is not None
    assert {e["video_id"] for e in raw["entries"]} == {"AAAAAAAAAAA", "BBBBBBBBBBB"}
    # A day with no videos returns None (framework treats as no_data).
    assert yt.fetch_day({"channel_id": "UCtest"}, "2026-07-18") is None


# ── Transform → framework records, with provenance stamped (#1669 + #1670) ───────
def test_transform_writes_suffixed_provenance_records(monkeypatch):
    _offline(monkeypatch)
    raw = {"date": "2026-07-20", "channel_id": "UCtest", "entries": yt._parse_entries(_FIXTURE_FEED)[:2]}
    records = yt.transform(raw, "2026-07-20")
    assert len(records) == 2
    by_id = {r["post_id"]: r for r in records}

    human = by_id["AAAAAAAAAAA"]
    assert human["sk_suffix"] == "#AAAAAAAAAAA"  # → sk=DATE#2026-07-20#AAAAAAAAAAA
    assert human["source"] == "youtube"
    assert human["channel"] == "youtube"
    assert human["origin"] == prov.ORIGIN_HUMAN
    assert human["views"] == Decimal("1234")
    assert isinstance(human["views"], Decimal)

    # The self-linking video is stamped a platform echo even with an empty ledger (#1670).
    platform = by_id["BBBBBBBBBBB"]
    assert platform["sk_suffix"] == "#BBBBBBBBBBB"
    assert platform["origin"] == prov.ORIGIN_PLATFORM


def test_transform_empty_when_no_entries(monkeypatch):
    _offline(monkeypatch)
    assert yt.transform({"entries": []}, "2026-07-20") == []

"""tests/test_closed_social_paste_1677.py — the closed-platform paste fallback (#1677, epic #1668).

#1677's second acceptance box: a pasted post must land through the **same**
transform/membrane path a framework-fetched post takes, **before any paid token exists**.
Boxes 1 and 3 (token-backed polling for X / Instagram / TikTok) are deliberately unbuilt —
provisioning the paid X tier and the IG/TikTok Graph tokens is an owner act that has been
declined for now (2026-08-12), so this file also guards the *absence*: no client, no
secret, no token read may creep in behind a "registered" registry entry.

The load-bearing assertion is end-to-end, not shape-checked: a paste is staged, the real
``run_ingestion()`` framework runs over it with AWS stubbed at ``_init_aws``, and the
stored record is checked for the S2 membrane's ``channel`` + ``origin`` provenance and
its RAW_TIMESERIES classification. Break the membrane hand-off in
``closed_social_paste_lambda._origin_for`` and this file goes red.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from experiment import phase_taxonomy  # noqa: E402
from ingestion import (
    closed_social_paste_lambda as paste,  # noqa: E402
    ingestion_framework as fw,  # noqa: E402
    social_paste_inbox as inbox,  # noqa: E402
    source_registry as reg,  # noqa: E402
)
from privacy import social_provenance as prov  # noqa: E402

_DATE = "2026-08-11"


# ── A DDB double that honours real boto3 key conditions ────────────────────────
# The staging read and the framework's gap detector both query with
# `boto3.dynamodb.conditions.Key(...)` objects, and the whole point of staging under a
# `PASTE#` sort key is that the two key spaces don't overlap — a fake that ignores the
# condition would assert nothing about that.
def _matches(cond, item):
    expr = cond.get_expression()
    op = expr["operator"]
    values = expr["values"]
    if op == "AND":
        return all(_matches(v, item) for v in values)
    actual = item.get(values[0].name, "")
    if op == "=":
        return actual == values[1]
    if op == "begins_with":
        return str(actual).startswith(values[1])
    if op == "BETWEEN":
        return values[1] <= actual <= values[2]
    raise AssertionError(f"unsupported condition operator in the fake table: {op}")


class FakeTable:
    def __init__(self):
        self.store = {}

    def put_item(self, Item=None, **kwargs):
        item = Item if Item is not None else kwargs.get("Item")
        self.store[(item["pk"], item["sk"])] = item
        return {}

    def get_item(self, Key=None, **kwargs):
        key = Key or kwargs.get("Key") or {}
        item = self.store.get((key.get("pk"), key.get("sk")))
        return {"Item": item} if item else {}

    def delete_item(self, Key=None, **kwargs):
        self.store.pop(((Key or {}).get("pk"), (Key or {}).get("sk")), None)
        return {}

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        items = [i for i in self.store.values() if cond is None or _matches(cond, i)]
        return {"Items": sorted(items, key=lambda i: i["sk"])}


class FakeS3:
    def __init__(self):
        self.keys = []

    def put_object(self, Bucket=None, Key=None, **kwargs):
        self.keys.append(Key)
        return {}


def _offline(monkeypatch, table, s3=None):
    """Run the real framework + transform with no AWS and no Bedrock."""
    s3 = s3 or FakeS3()
    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, s3, None))
    monkeypatch.setattr(paste, "_table", lambda: table)
    # Exercise the real #1673 gate, but with its Bedrock off-topic layer stubbed confident.
    monkeypatch.setattr(paste.gate, "bedrock_offtopic_classifier", lambda text: paste.gate.OfftopicResult(True, 0.95))
    return s3


def _stage(table, channel="x", **kwargs):
    defaults = dict(
        url="https://x.com/averagejoematt/status/1899000000000000001",
        text="Day 4 of the cut. The scale finally moved.",
        published_at="2026-08-11T18:04:00Z",
        author="averagejoematt",
    )
    defaults.update(kwargs)
    return inbox.stage_paste(table, channel, **defaults)


# ══════════════════════════════════════════════════════════════════════════════
# The registry: registered, and explicitly NOT polling
# ══════════════════════════════════════════════════════════════════════════════


def test_the_three_closed_platforms_are_registered_paste_only():
    assert reg.paste_only_source_ids() == ["instagram", "tiktok", "x"]
    for key in reg.paste_only_source_ids():
        entry = reg.SOURCE_REGISTRY[key]
        assert entry["inbound_mode"] == reg.INBOUND_PASTE_ONLY
        # "Registered" must never read as "polling": no active API, and off every
        # freshness/QA/liveness surface, where a source with no pipe would false-page.
        assert entry["active_api"] is False, key
        assert entry["freshness"] is False, key
        assert entry["monitored"] is False, key
        assert entry["qa_tier"] is None, key
        assert key not in reg.checker_sources() and key not in reg.public_board_sources(), key
        assert "paste" in entry["method"].lower(), f"{key}'s public method text must say how it actually arrives"
        # capture_channel drives the "you forgot to log" nudges and is reserved for
        # Matthew's three logging channels (#746/#1682) — a paste must not nag.
        assert "capture_channel" not in entry, key


def test_pasted_posts_are_raw_timeseries():
    for key in reg.paste_only_source_ids():
        assert phase_taxonomy.SOURCE_CLASS[key] == phase_taxonomy.RAW_TIMESERIES, key


def test_no_token_or_secret_path_exists_for_the_closed_platforms():
    """The guardrail, asserted rather than promised: an unused credential path is a claim
    that provisioning is imminent, and #1677's owner decision is that it isn't."""
    for channel, config in paste.CONFIGS.items():
        assert channel in inbox.PASTE_ONLY_CHANNELS
        assert config.secret_id is None, f"{channel} config names a secret — there is no token for it"
    forbidden = ("secretsmanager", "get_secret", "access_token", "authorization", "api.x.com", "graph.facebook", "tiktokapis")
    for module in (paste, inbox):
        source = open(module.__file__).read().lower()
        for needle in forbidden:
            assert needle.lower() not in source, f"{module.__name__} grew a token path: {needle!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Post ids: idempotent, permalink-derived
# ══════════════════════════════════════════════════════════════════════════════


def test_post_id_comes_from_the_permalink():
    assert inbox.derive_post_id("x", url="https://x.com/averagejoematt/status/1899000000000000001") == "1899000000000000001"
    assert inbox.derive_post_id("x", url="https://twitter.com/averagejoematt/status/42") == "42"
    assert inbox.derive_post_id("instagram", url="https://www.instagram.com/reel/C8xYzAbCdEf/") == "C8xYzAbCdEf"
    assert inbox.derive_post_id("tiktok", url="https://www.tiktok.com/@averagejoematt/video/7398765432109876543") == "7398765432109876543"


def test_post_id_without_a_permalink_is_hashed_and_stable():
    a = inbox.derive_post_id("x", text="no link here", date_str=_DATE)
    b = inbox.derive_post_id("x", text="no link here", date_str=_DATE)
    assert a == b and inbox.is_synthetic_post_id(a)
    assert a != inbox.derive_post_id("x", text="different words", date_str=_DATE)


# ══════════════════════════════════════════════════════════════════════════════
# THE acceptance: a paste lands through the framework and reaches the S2 membrane
# ══════════════════════════════════════════════════════════════════════════════


def test_pasted_post_reaches_the_membrane_through_the_framework(monkeypatch):
    table = FakeTable()
    s3 = _offline(monkeypatch, table)
    _stage(table)

    resp = paste.ingest_pasted_day("x", {"date_override": _DATE})
    assert resp["statusCode"] == 200, resp

    stored = [i for k, i in table.store.items() if k[1].startswith("DATE#")]
    assert len(stored) == 1, f"expected exactly one ingested record, got {[k for k in table.store]}"
    rec = stored[0]

    # Same write path as a fetched post: source partition + #{post_id}-suffixed sk.
    assert rec["pk"] == "USER#matthew#SOURCE#x"
    assert rec["sk"] == f"DATE#{_DATE}#1899000000000000001"
    # The S2 membrane's provenance, stamped by the SAME classifier the fetched sources use.
    assert rec["channel"] == "x"
    assert rec["origin"] == prov.ORIGIN_HUMAN
    assert rec["capture"] == inbox.CAPTURE_PASTE  # how it arrived, on the row itself
    assert rec["text"].startswith("Day 4 of the cut")
    # #1673: a clean human post is gate-cleared, so it is eligible for the S4 feed.
    assert rec["sensitivity_status"] == paste.gate.SENSITIVITY_CLEARED
    # ...and the record is RAW_TIMESERIES to the phase machinery.
    assert phase_taxonomy.classify(rec["pk"], rec["sk"]) == phase_taxonomy.RAW_TIMESERIES
    # The framework's own raw archive ran, under the prefix the registry documents.
    assert s3.keys == [f"{reg.SOURCE_REGISTRY['x']['raw_layout']['prefix']}/2026/08/{_DATE}.json"]


def test_membrane_handoff_passes_the_channel_and_the_posts_own_text(monkeypatch):
    """The hand-off itself: origin is CLASSIFIED per post, not assumed from 'it was pasted'."""
    table = FakeTable()
    _offline(monkeypatch, table)
    _stage(table)
    seen = {}

    def _spy(ledger_table, *, channel, post_id, text_fields):
        seen.update(channel=channel, post_id=post_id, text_fields=list(text_fields))
        return prov.ORIGIN_HUMAN

    monkeypatch.setattr(paste.prov, "classify_post_origin", _spy)
    paste.ingest_pasted_day("x", {"date_override": _DATE})

    assert seen["channel"] == "x"
    assert seen["post_id"] == "1899000000000000001"
    assert any("Day 4 of the cut" in (f or "") for f in seen["text_fields"])
    assert any("x.com/averagejoematt/status" in (f or "") for f in seen["text_fields"])


def test_pasted_platform_echo_is_caught_by_the_membrane(monkeypatch):
    """A paste is not proof of human authorship: the owner can paste the platform's own
    syndicated post. The self-backlink signal must still catch it (#1670)."""
    table = FakeTable()
    _offline(monkeypatch, table)
    _stage(
        table,
        channel="tiktok",
        url="https://www.tiktok.com/@averagejoematt/video/7398765432109876543",
        text="New cockpit is live: https://averagejoematt.com/cockpit",
    )

    paste.ingest_pasted_day("tiktok", {"date_override": _DATE})
    rec = [i for k, i in table.store.items() if k[1].startswith("DATE#")][0]
    assert rec["origin"] == prov.ORIGIN_PLATFORM
    # An echo never reaches the S4 feed, so the sensitivity gate never runs on it.
    assert "sensitivity_status" not in rec


def test_ingest_is_idempotent_across_a_repasted_post(monkeypatch):
    table = FakeTable()
    _offline(monkeypatch, table)
    _stage(table)
    _stage(table)  # same permalink pasted twice
    paste.ingest_pasted_day("x", {"date_override": _DATE})
    assert len([k for k in table.store if k[1].startswith("DATE#")]) == 1


def test_staging_rows_are_invisible_to_the_frameworks_day_query(monkeypatch):
    """The `PASTE#` sort key must not read as an ingested day, or the gap detector would
    consider a merely-staged post already ingested and never process it."""
    table = FakeTable()
    _offline(monkeypatch, table)
    item = _stage(table)
    assert item["sk"].startswith("PASTE#")

    class _Log:
        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

    monkeypatch.setattr(fw, "pacific_now", lambda: __import__("datetime").datetime(2026, 8, 12, 9, 0))
    missing = fw._find_missing_dates(table, paste.CONFIGS["x"], _Log())
    assert _DATE in missing, "a staged-but-not-ingested day must still look missing to the framework"


def test_unknown_channel_is_refused():
    import pytest

    with pytest.raises(ValueError):
        paste.ingest_pasted_day("bluesky", {"date_override": _DATE})
    with pytest.raises(ValueError):
        inbox.normalize_paste("bluesky", text="nope")

"""tests/test_notion_sync_476.py — #476 (E-6, X-7; epic #460).

Notion ingestion previously: never synced edits >2 days old, never reconciled deletions,
positionally renumbered multi-per-day entries (orphaning enrichment), and kept DynamoDB as
the ONLY copy of irreplaceable journal text. These pin the four fixes.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import notion_lambda as nl  # noqa: E402

# ── E-6: stable SK ────────────────────────────────────────────────────────────


def test_build_sk_stable_for_multi_per_day():
    sk = nl.build_sk("2026-07-01", "Stressor", page_id="abcd1234-ef56-7890-1234-56789abcdef0")
    # last 12 hex of the de-hyphenated id
    assert sk == "DATE#2026-07-01#journal#stressor#56789abcdef0"
    # idempotent — same page id → same SK regardless of ordering
    assert sk == nl.build_sk("2026-07-01", "Stressor", page_id="abcd1234-ef56-7890-1234-56789abcdef0")


def test_build_sk_single_per_day_unchanged():
    assert nl.build_sk("2026-07-01", "Morning") == "DATE#2026-07-01#journal#morning"


# ── E-6: last_edited_time OR-branch ───────────────────────────────────────────


def test_query_filter_includes_last_edited_time(monkeypatch):
    captured = {}

    def _fake_post(path, api_key, body):
        captured["body"] = body
        return {"results": [], "has_more": False, "next_cursor": None}

    monkeypatch.setattr(nl, "notion_post", _fake_post)
    nl.query_database("k", "db", start_date="2026-07-01", end_date="2026-07-03")
    or_clauses = captured["body"]["filter"]["or"]
    # Flatten every timestamp name referenced across the OR
    blob = str(or_clauses)
    assert "last_edited_time" in blob
    assert "created_time" in blob
    assert '"property": ' in blob or "'property'" in blob  # the Date-property window
    assert len(or_clauses) == 3


# ── E-6: deletion reconcile ───────────────────────────────────────────────────


def test_reconcile_removes_orphans_keeps_written(monkeypatch):
    existing = [
        {"sk": "DATE#2026-07-01#journal#stressor#aaaaaaaaaaaa"},  # kept (written)
        {"sk": "DATE#2026-07-01#journal#stressor#1"},  # legacy #seq orphan → delete
        {"sk": "DATE#2026-07-01#journal#stressor#bbbbbbbbbbbb"},  # deleted-in-notion → delete
    ]
    deleted = []
    monkeypatch.setattr(nl.table, "query", lambda **kw: {"Items": existing})
    monkeypatch.setattr(nl.table, "delete_item", lambda Key: deleted.append(Key["sk"]))

    nl._reconcile_deleted("2026-07-01", "Stressor", {"DATE#2026-07-01#journal#stressor#aaaaaaaaaaaa"})
    assert set(deleted) == {"DATE#2026-07-01#journal#stressor#1", "DATE#2026-07-01#journal#stressor#bbbbbbbbbbbb"}


# ── X-7: raw archive ──────────────────────────────────────────────────────────


def test_archive_writes_per_page_s3_key(monkeypatch):
    puts = {}

    def _fake_put(Bucket, Key, Body, ContentType):
        puts["Bucket"] = Bucket
        puts["Key"] = Key
        puts["Body"] = Body

    monkeypatch.setattr(nl.s3_client, "put_object", _fake_put)
    page = {"id": "abcd1234-ef56-7890-1234-56789abcdef0", "created_time": "2026-07-01T12:00:00Z"}
    item = {"body_text": "today I lifted heavy and slept well", "raw_text": "[journal]\n..."}
    nl._archive_page_raw(page, item, "2026-07-01")

    assert puts["Bucket"] == "matthew-life-platform"
    pid = "abcd1234-ef56-7890-1234-56789abcdef0".replace("-", "")
    assert puts["Key"] == f"raw/matthew/notion/2026/07/01-{pid}.json"
    import json

    body = json.loads(puts["Body"])
    assert body["notion_page_id"] == "abcd1234-ef56-7890-1234-56789abcdef0"
    assert "lifted heavy" in body["text"]
    assert body["raw_page"]["id"] == page["id"]


def test_archive_best_effort_never_raises(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(nl.s3_client, "put_object", _boom)
    # Must not raise — archival is best-effort and never blocks the write.
    nl._archive_page_raw({"id": "x"}, {"raw_text": "t"}, "2026-07-01")

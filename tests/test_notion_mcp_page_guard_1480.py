#!/usr/bin/env python3
"""tests/test_notion_mcp_page_guard_1480.py — #1480 (epic #1476).

notion_lambda.py is already schema-flexible — extract_all_properties() reads every
Notion property dynamically. The open question wasn't "does it need new production
code," it was "is it *proven* against a page shaped exactly as one created via the
Notion MCP `notion-create-pages` tool would come back on a subsequent read." These
tests pin that:

  1. A synthetic MCP-created page with Template (select) + Date (date) properties set
     ingests cleanly end-to-end through parse_page(): template recognized via
     TEMPLATE_SK, date extracted, body text landed in raw_text, notion_page_id set.
  2. An MCP-created page WITHOUT a Date property (simulating a connector call that
     only set Template + content — the Date property needs the expanded
     "date:Date:start" key convention per docs/coaching/CHAT_MODES.md, and a
     malformed/omitted key degrades to this case) still ingests via the
     created_time -> Pacific-Time fallback. This is the "OR'd query window" AC in
     miniature: the fallback that makes created_time-only pages still ingestible is
     exactly what the OR'd Date/created_time/last_edited_time query window (E-6/#476)
     is built to catch.
  3. A round-trip write: the parsed item fed through write_entries() against a
     mocked table lands a put_item with the expected pk/sk — the closest thing to a
     live round-trip that's safe to run in CI (no live Notion API, no live AWS).

Run: python3 -m pytest tests/test_notion_mcp_page_guard_1480.py -v
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import notion_lambda as nl  # noqa: E402

BODY_TEXT = "Solid day. Hit every set on the program and felt strong by the last superset."


def _mcp_page(page_id="abcd1234ef567890123456789abcdef", template="Evening", date_start=None, created_time=None, last_edited_time=None):
    """Builds a page object shaped exactly as the Notion MCP `notion-create-pages`
    tool's subsequent GET /pages/{id} (or database query) would return: id,
    created_time, last_edited_time are Notion-assigned regardless of creation
    method; properties carries whatever the connector call set."""
    props = {"Template": {"type": "select", "select": {"name": template}}}
    if date_start:
        props["Date"] = {"type": "date", "date": {"start": date_start}}
    return {
        "id": page_id,
        "created_time": created_time or "2026-07-19T20:00:00.000Z",
        "last_edited_time": last_edited_time or "2026-07-19T20:05:00.000Z",
        "properties": props,
    }


def _quiet_s3(monkeypatch):
    # parse_page's _archive_page_raw is best-effort S3 archival — mock it out so
    # tests never touch a real bucket (never invoke/mutate AWS, per task constraints).
    monkeypatch.setattr(nl.s3_client, "put_object", lambda **kw: None)


def _mock_body(monkeypatch, text=BODY_TEXT):
    monkeypatch.setattr(nl, "fetch_page_body", lambda page_id, api_key: text)


# ── 1. MCP-created page WITH Template + Date — end-to-end clean ingest ────────


def test_mcp_created_page_with_date_and_template_ingests_cleanly(monkeypatch):
    _quiet_s3(monkeypatch)
    _mock_body(monkeypatch)
    page = _mcp_page(template="Evening", date_start="2026-07-19")

    result = nl.parse_page(page, api_key="fake")
    assert result is not None
    date_str, template, item = result

    assert template == "Evening"
    assert date_str == "2026-07-19"
    # The Template select is recognized via the canonical TEMPLATE_SK map.
    assert nl.TEMPLATE_SK[template] == "evening"
    sk = nl.build_sk(date_str, template)
    assert sk == f"DATE#{date_str}#journal#evening"

    # Body text (the page's markdown content, fetched separately) landed in raw_text.
    assert BODY_TEXT in item["raw_text"]
    assert item["notion_page_id"] == page["id"]
    assert item["date"] == "2026-07-19"
    assert item["source"] == "notion"


# ── 2. MCP-created page WITHOUT Date — created_time -> PT fallback ────────────


def test_mcp_created_page_without_date_falls_back_to_created_time_pt(monkeypatch):
    """Simulates a connector call that only set Template + content (e.g. the Date
    property's expanded 'date:Date:start' key was omitted or malformed — see
    docs/coaching/CHAT_MODES.md). parse_page must still produce a valid item via
    the created_time -> Pacific-Time fallback (~notion_lambda.py L474-487) — this
    is the degraded-but-not-broken failure mode, not silent data loss."""
    _quiet_s3(monkeypatch)
    _mock_body(monkeypatch)
    # 2026-07-19T20:00:00Z -> PDT (UTC-7) = 2026-07-19 13:00 PT -> same calendar date.
    created = "2026-07-19T20:00:00.000Z"
    page = _mcp_page(template="Evening", date_start=None, created_time=created)

    result = nl.parse_page(page, api_key="fake")
    assert result is not None
    date_str, template, item = result

    expected_pt_date = (
        datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    )
    assert date_str == expected_pt_date
    assert template == "Evening"
    assert item["notion_page_id"] == page["id"]
    assert BODY_TEXT in item["raw_text"]
    # No Date property was set on the page, and extract_all_properties skips it —
    # the item's own `date` field still carries the fallback-derived value.
    assert item["date"] == expected_pt_date


def test_mcp_created_page_without_date_crosses_utc_day_boundary(monkeypatch):
    """A late-night PT entry crosses into the next UTC day — pin the PT conversion
    handles that (the same UTC-offset subtlety query_database's ts_end already
    accounts for on the read side, #476/E-6)."""
    _quiet_s3(monkeypatch)
    _mock_body(monkeypatch)
    # 2026-07-20T04:30:00Z (just after UTC midnight) -> PDT = 2026-07-19 21:30 PT.
    created = "2026-07-20T04:30:00.000Z"
    page = _mcp_page(template="Evening", date_start=None, created_time=created)

    result = nl.parse_page(page, api_key="fake")
    date_str, template, item = result
    assert date_str == "2026-07-19"  # PT date, not the UTC calendar date (07-20)


# ── 3. Round-trip write against a mocked table ────────────────────────────────


def test_round_trip_write_lands_expected_sourcenotion_put(monkeypatch):
    """Feeds a parsed MCP-created-page item through write_entries() against a
    mocked nl.table (following tests/test_notion_sync_476.py's pattern of
    monkeypatching methods directly on the module-level `table` object) and
    confirms a put_item lands with the expected SOURCE#notion pk/sk. This is the
    closest thing to a live round-trip that's safe to run in CI — no live Notion
    API call, no live AWS. A real live round-trip is a manual post-merge step
    (see the PR description)."""
    _quiet_s3(monkeypatch)
    _mock_body(monkeypatch)
    page = _mcp_page(template="Evening", date_start="2026-07-19")
    date_str, template, item = nl.parse_page(page, api_key="fake")

    puts = []
    monkeypatch.setattr(nl.table, "get_item", lambda Key: {})  # no prior item to preserve enrichment from
    monkeypatch.setattr(nl.table, "put_item", lambda Item: puts.append(Item))

    written = nl.write_entries({date_str: [(template, item)]})

    assert written == 1
    assert len(puts) == 1
    put = puts[0]
    assert put["pk"] == "USER#matthew#SOURCE#notion"
    assert put["sk"] == f"DATE#{date_str}#journal#evening"
    assert put["sk"] == nl.build_sk(date_str, template)
    assert put["template"] == "Evening"
    assert BODY_TEXT in put["raw_text"]
    assert put["notion_page_id"] == page["id"]


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))

"""tests/test_manual_source_reliability_746.py — #746 manual-source reliability.

Covers the three moving parts of "staleness surfaced kindly, degraded modes honest":

  1. The manual-capture staleness FACETS in source_registry (capture_channel +
     the migrated per-HAE-datatype thresholds), including the drift guard that
     keeps freshness_checker's HAE_DATATYPES an alias of the registry, not a copy.
  2. The evening nudge's PURE gone-quiet selection — journal + manual HAE streams
     only, never a device stream or an MCP one-off, never an invented nag.
  3. The public DEGRADED-DISPLAY flag on /api/source_freshness — capture_channel,
     manual, and the honest "dark N days" count (ADR-104 behavioral-absence).
"""

import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
# evening_nudge reads these at import time.
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import evening_nudge_lambda as nudge  # noqa: E402
import freshness_checker_lambda as checker  # noqa: E402
import source_registry as reg  # noqa: E402
from web import site_api_data as sad  # noqa: E402

# ── 1. Facets ────────────────────────────────────────────────────────────────


def test_capture_channels_are_matthews_three():
    """Matthew's decision: the manual capture channels are HAE, Notion, MCP —
    and nothing else carries a capture_channel (a device pipe must not)."""
    got = {k: v["channel"] for k, v in reg.manual_capture_sources().items()}
    assert got == {
        "apple_health": "hae",
        "notion": "notion",
        "measurements": "mcp",
        "food_delivery": "mcp",
    }
    # No worn-device / scheduled-pull source leaks a capture_channel.
    for k in ("whoop", "garmin", "eightsleep", "strava", "withings", "habitify", "todoist", "weather"):
        assert reg.SOURCE_REGISTRY[k].get("capture_channel") is None, k


def test_channel_filter():
    assert set(reg.manual_capture_sources(channel="mcp")) == {"measurements", "food_delivery"}
    assert set(reg.manual_capture_sources(channel="hae")) == {"apple_health"}
    assert set(reg.manual_capture_sources(channel="notion")) == {"notion"}


def test_notion_threshold_derived_from_journaling_cadence():
    """Journaling cadence in DDB (median ~9-10d gaps) → a 14-day gentle-mention
    mark. It must never page: behavioral + not monitored."""
    n = reg.SOURCE_REGISTRY["notion"]
    assert n["stale_hours"] == 14 * 24
    assert n["behavioral"] is True
    assert n["monitored"] is False
    assert "notion" not in checker.SOURCES  # never on the paging surface


def test_hae_thresholds_migrated_not_duplicated():
    """The checker's HAE_DATATYPES is the registry list — a drift guard, so the
    per-datatype thresholds can't fork the way #392 warns lists always do."""
    assert checker.HAE_DATATYPES == reg.hae_datatype_thresholds()
    by = {d["key"]: d for d in reg.hae_datatype_thresholds()}
    # The issue's named manual HAE streams, with their derived cadences.
    assert by["cgm"]["stale_days"] == 3 and by["cgm"]["manual"] is True
    assert by["water"]["stale_days"] == 3 and by["water"]["manual"] is True
    assert by["blood_pressure"]["stale_days"] == 14 and by["blood_pressure"]["manual"] is True
    assert by["state_of_mind"]["stale_days"] == 14 and by["state_of_mind"]["manual"] is True
    # Passive device streams are present but NOT hand-captured.
    assert by["steps"]["manual"] is False
    assert by["workouts"]["manual"] is False


def test_manual_hae_keys_are_exactly_the_hand_captured_four():
    assert reg.manual_hae_datatype_keys() == {"cgm", "water", "blood_pressure", "state_of_mind"}


# ── 2. Nudge: pure gone-quiet selection ──────────────────────────────────────

_MANUAL = {
    "notion": {"label": "Notion", "channel": "notion", "stale_hours": 14 * 24},
    "measurements": {"label": "Tape measure", "channel": "mcp", "stale_hours": 60 * 24},
    "food_delivery": {"label": "Food delivery", "channel": "mcp", "stale_hours": 14 * 24},
    "apple_health": {"label": "Apple Health", "channel": "hae", "stale_hours": 48},
}
_TODAY = "2026-07-08"


def _select(latest, hae):
    return nudge.select_quiet_manual_sources(_MANUAL, latest, hae, _TODAY)


def test_journal_dark_past_threshold_is_mentioned():
    got = _select({"notion": "2026-05-25"}, None)  # 44 days dark, threshold 14
    assert [q["name"] for q in got] == ["Notion"]
    assert got[0]["days"] == 44
    assert "44 days" in got[0]["detail"]


def test_journal_within_threshold_is_silent():
    assert _select({"notion": "2026-07-01"}, None) == []  # 7 days, under 14


def test_no_history_is_never_an_invented_nag():
    assert _select({"notion": None}, None) == []


def test_mcp_oneoffs_are_not_nudged():
    """measurements/food_delivery carry a capture_channel for the public board,
    but a nightly 'log a delivery' nudge is nonsense — MCP is out of nudge scope."""
    old = {"measurements": "2026-01-01", "food_delivery": "2026-01-01"}
    assert _select(old, None) == []


def test_manual_hae_stream_dark_is_mentioned_device_stream_is_not():
    hae = [
        {"label": "CGM (glucose)", "age_days": 5, "dark": True, "manual": True},
        {"label": "Steps / activity", "age_days": 9, "dark": True, "manual": False},  # device — never nudge
        {"label": "Water", "age_days": 2, "dark": False, "manual": True},  # not dark
    ]
    got = _select({"notion": None}, hae)
    assert [q["name"] for q in got] == ["CGM (glucose)"]


def test_longest_dark_sorts_first():
    hae = [{"label": "CGM (glucose)", "age_days": 5, "dark": True, "manual": True}]
    got = _select({"notion": "2026-05-25"}, hae)  # journal 44d, CGM 5d
    assert [q["days"] for q in got] == [44, 5]


def test_quiet_section_empty_when_nothing_dark():
    assert nudge._build_quiet_section([]) == ""


# ── 3. Public degraded-display flag ──────────────────────────────────────────


def test_days_dark_pure_counts_whole_days():
    now = datetime(2026, 7, 8, tzinfo=timezone.utc)
    assert sad._days_dark("2026-06-08", now) == 30
    assert sad._days_dark("2026-07-08", now) == 0
    assert sad._days_dark(None, now) is None
    assert sad._days_dark("not-a-date", now) is None


class _FreshnessFakeTable:
    """Every source's latest DATE# is an ancient date → definitively stale; no
    stored HAE datatype-liveness sentinel."""

    def query(self, **kwargs):
        return {"Items": [{"sk": "DATE#2020-01-01"}]}

    def get_item(self, Key=None):
        return {}


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def test_source_freshness_stamps_manual_darkness(monkeypatch):
    monkeypatch.setattr(sad, "table", _FreshnessFakeTable())
    body = _body(sad.handle_source_freshness())
    by = {s["id"]: s for s in body["sources"]}

    # A manual MCP source that's long dark: honest capture_channel + days_dark.
    md = by["measurements"]
    assert md["manual"] is True
    assert md["capture_channel"] == "mcp"
    assert md["status"] == "behavioral-stale"  # behavioral — never a broken-pipe stamp
    assert isinstance(md["days_dark"], int) and md["days_dark"] > 0

    # apple_health carries the hae channel too (its manual sub-streams are the signal).
    assert by["apple_health"]["capture_channel"] == "hae"
    assert by["apple_health"]["manual"] is True

    # A device pipe is untouched — no capture_channel, no manual flag, no days_dark.
    whoop = by["whoop"]
    assert "capture_channel" not in whoop
    assert "manual" not in whoop
    assert "days_dark" not in whoop

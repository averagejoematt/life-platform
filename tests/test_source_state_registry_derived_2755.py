"""#2755 — `resolve_source_state` must derive its staleness threshold from the
REGISTRY's `stale_hours` facet, not from a hardcoded 2-day default.

Measured live on 2026-08-16: `get_freshness_status {"sources": ["withings"]}` returned
one row with two contradictory labels — `{"last_date": "2026-08-11", "age_days": 5,
"threshold_days": 7, "status": "fresh", "source_state": "stale"}`. `get_sources`
independently called withings/notion/supplements `stale` on their normal slow cadence
(withings 5d old vs its 168h/7d registry threshold; notion 6d vs 336h/14d).

Cause: `resolve_source_state(..., stale_days=DEFAULT_STALE_DAYS)` with
`DEFAULT_STALE_DAYS=2` hardcoded — a SECOND copy of a fact the registry's `stale_hours`
facet already owns (charter primitive 1: the registry owns the vocabulary, consumers
derive). `mcp/tools_labs.py::tool_get_freshness_status` computes the correct
registry-derived `threshold_days` two lines above its own `resolve_source_state` call
and never passes it — so `status` (from the local threshold) and `source_state` (from
the resolver's hardcoded one) could disagree in the very same row.

The fix is RESOLVER-INTERNAL (`lambdas/ingestion/source_state.py::_registry_stale_days`):
`resolve_source_state` now reads the source's `stale_hours` facet itself when the caller
doesn't pass an explicit override, so every caller — `mcp/tools_data.py::tool_get_sources`,
`mcp/tools_labs.py::tool_get_freshness_status`, and
`intelligence/ai_expert_analyzer_lambda.py` (unmodified; it never passed `stale_days`
either) — agrees without threading a value through each call site.

This file has two halves:
  1. A DERIVATION GUARD over the whole registry SET (not one hand-picked source) —
     charter primitive 2. It fails on a reintroduced literal (a new hardcoded default,
     or a source-specific special case) exactly as readily as it fails on the original
     bug, because it is parametrized over every `SOURCE_REGISTRY` key.
  2. The withings-shaped reproduction, run through the real `tool_get_freshness_status`
     entry point, proving `status` and `source_state` can no longer disagree in one row.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from common.pacific_time import pacific_today  # noqa: E402  # #3222: the frame tools_labs ages against
from ingestion import source_state as ss  # noqa: E402
from ingestion.source_registry import DEFAULT_STALE_HOURS, SOURCE_REGISTRY  # noqa: E402

from mcp import tools_labs  # noqa: E402

TODAY = "2026-08-16"


def _days_ago(n: int) -> str:
    return (date.fromisoformat(TODAY) - timedelta(days=n)).isoformat()


# ── 1. Derivation guard — the whole SET, not one instance ──────────────────────


def test_the_registry_carries_more_than_one_distinct_threshold():
    """Vacuity guard: if every source used the same threshold, the boundary test below
    could pass by accident (a resolver that ignores the registry entirely would still
    agree with a registry that never varies)."""
    thresholds = {(v.get("stale_hours") if v.get("stale_hours") is not None else DEFAULT_STALE_HOURS) for v in SOURCE_REGISTRY.values()}
    assert len(thresholds) > 1, "the registry's stale_hours facet is not actually varying — check the fixture, not the code"


@pytest.mark.parametrize("source", sorted(SOURCE_REGISTRY.keys()))
def test_resolver_threshold_matches_the_registry_facet(source):
    """Structural half of the guard: the resolver's derived threshold, in days, equals
    the registry's own facet for EVERY source — not the hand-picked withings example."""
    entry = SOURCE_REGISTRY[source]
    hours = entry.get("stale_hours")
    expected_days = (hours if hours is not None else DEFAULT_STALE_HOURS) / 24
    assert ss._registry_stale_days(source) == expected_days


@pytest.mark.parametrize("source", sorted(SOURCE_REGISTRY.keys()))
def test_boundary_gap_is_live_and_one_day_beyond_is_not(source):
    """Behavioral half of the guard, exercised through the public function: a gap AT the
    registry's own threshold resolves 'live'; one day past it does not. Run without an
    explicit `stale_days` — the default path is exactly what every real caller uses."""
    entry = SOURCE_REGISTRY[source]
    hours = entry.get("stale_hours")
    threshold_days = (hours if hours is not None else DEFAULT_STALE_HOURS) / 24
    at_boundary = math.floor(threshold_days)
    assert ss.resolve_source_state(source, _days_ago(at_boundary), TODAY) == ss.STATE_LIVE
    assert ss.resolve_source_state(source, _days_ago(at_boundary + 1), TODAY) != ss.STATE_LIVE


def test_an_explicit_override_still_wins_over_the_registry():
    """A caller with its own threshold (none exists today, but the parameter stays
    supported) must not be silently overridden by the registry-derived default."""
    # withings' registry threshold is 7 days; an explicit 1-day override must be honored.
    assert ss.resolve_source_state("withings", _days_ago(2), TODAY, stale_days=1) == ss.STATE_STALE
    assert ss.resolve_source_state("withings", _days_ago(2), TODAY) == ss.STATE_LIVE


def test_an_unreadable_registry_falls_back_to_the_conservative_default(monkeypatch):
    """Fail-soft in the safe direction, mirroring `_registry_paused`'s own contract:
    an unreadable registry must not invent a lenient (long) threshold."""
    monkeypatch.setattr("ingestion.source_registry.SOURCE_REGISTRY", {}, raising=True)
    assert ss._registry_stale_days("withings") == ss.DEFAULT_STALE_DAYS


# ── 2. The withings reproduction, through the real tool ────────────────────────


class _FreshnessTable:
    """Bounded double for the one `.query()` shape `tool_get_freshness_status` issues."""

    def __init__(self, rows_by_source):
        self.rows_by_source = rows_by_source

    def query(self, **kwargs):
        expr = kwargs["KeyConditionExpression"].get_expression()
        pk = expr["values"][0].get_expression()["values"][1]
        src = pk.rsplit("#", 1)[-1]
        return {"Items": self.rows_by_source.get(src, [])}

    def get_item(self, **_kwargs):
        return {}


def test_withings_status_and_source_state_agree_at_5_days_against_a_7_day_threshold(monkeypatch):
    """The live repro from the issue: withings 5 days old against its 168h/7d registry
    threshold must read 'fresh'/'live' on BOTH fields — never 'fresh' + 'stale' in the
    same row. Ages relative to the real wall clock (the tool has no injectable seam),
    matching the established pattern in test_paused_is_not_stale_2715.py."""
    # #3222: `date.today()` is the RUNNER's naive clock — Pacific on a laptop, UTC in CI.
    # The tool ages rows against `pacific_now().date()`, so the fixture reads that frame.
    last_date = (date.fromisoformat(pacific_today()) - timedelta(days=5)).isoformat()
    t = _FreshnessTable({"withings": [{"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{last_date}", "date": last_date}]})
    monkeypatch.setattr(tools_labs, "table", t)
    out = tools_labs.tool_get_freshness_status({"sources": ["withings"]})
    row = out["fresh_sources"][0]
    assert row["source"] == "withings"
    assert row["status"] == "fresh"
    assert row["source_state"] == "live", "status/source_state disagreed on the same row (#2755)"


def test_notion_at_6_days_against_its_14_day_threshold_also_agrees(monkeypatch):
    """The issue's second named example: notion 6d old vs 336h/14d threshold."""
    last_date = (date.fromisoformat(pacific_today()) - timedelta(days=6)).isoformat()
    t = _FreshnessTable({"notion": [{"pk": "USER#matthew#SOURCE#notion", "sk": f"DATE#{last_date}", "date": last_date}]})
    monkeypatch.setattr(tools_labs, "table", t)
    out = tools_labs.tool_get_freshness_status({"sources": ["notion"]})
    row = out["fresh_sources"][0]
    assert row["status"] == "fresh"
    assert row["source_state"] == "live"

"""
tests/test_citation_gate_758.py — #758 gate the PERMA/Seligman citation garnish until n exists.

Tool outputs cited Seligman/Holt-Lunstad/PERMA over n=1-day datasets — rigor-flavored
garnish that undermines the actual rigor bar (ADR-105: uncertainty + n on every statistical
claim). `mcp.tools_lifestyle.tool_get_social_connection_trend` returns a `perma_context`
field unconditionally regardless of how many real enriched_social_quality datapoints exist.

This pins: below `_SOCIAL_CITATION_MIN_N` the citation is OMITTED entirely (not hedged,
just absent); at/above threshold it's included verbatim. The rest of the output (counts,
streaks, correlations) is unaffected either way — only the citation garnish is gated.

All offline — DynamoDB/query_source mocked.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import mcp.tools_lifestyle as tl  # noqa: E402


def _social_entries(n, quality="meaningful"):
    """n distinct-day journal entries carrying an enriched_social_quality value."""
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return [{"date": (base + timedelta(days=i)).strftime("%Y-%m-%d"), "enriched_social_quality": quality} for i in range(n)]


def _patch_query_source(monkeypatch, journal_items):
    """Fake query_source: journal entries for 'notion', nothing for whoop/garmin health joins."""

    def fake_query_source(source, start_date, end_date, *args, **kwargs):
        if source == "notion":
            return journal_items
        return []

    monkeypatch.setattr(tl, "query_source", fake_query_source)


class TestSocialConnectionCitationGate:
    def test_below_threshold_omits_perma_citation(self, monkeypatch):
        n = tl._SOCIAL_CITATION_MIN_N - 1
        assert n > 0
        _patch_query_source(monkeypatch, _social_entries(n))

        result = tl.tool_get_social_connection_trend({})

        assert "error" not in result
        assert result["total_days_with_data"] == n
        assert "perma_context" not in result
        # The rest of the honest output still returns.
        assert result["distribution"] == {"meaningful": n}
        assert result["streaks"]["current_meaningful_streak"] == n

    def test_at_threshold_includes_perma_citation(self, monkeypatch):
        n = tl._SOCIAL_CITATION_MIN_N
        _patch_query_source(monkeypatch, _social_entries(n))

        result = tl.tool_get_social_connection_trend({})

        assert "error" not in result
        assert result["total_days_with_data"] == n
        assert "perma_context" in result
        assert "Seligman PERMA" in result["perma_context"]
        assert "Holt-Lunstad" in result["perma_context"]

    def test_above_threshold_includes_perma_citation(self, monkeypatch):
        n = tl._SOCIAL_CITATION_MIN_N + 10
        _patch_query_source(monkeypatch, _social_entries(n))

        result = tl.tool_get_social_connection_trend({})

        assert "error" not in result
        assert result["total_days_with_data"] == n
        assert "perma_context" in result

    def test_zero_data_still_fails_soft_no_citation(self, monkeypatch):
        """No journal data at all: existing error path, definitely no citation."""
        _patch_query_source(monkeypatch, [])

        result = tl.tool_get_social_connection_trend({})

        assert "error" in result
        assert "perma_context" not in result


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

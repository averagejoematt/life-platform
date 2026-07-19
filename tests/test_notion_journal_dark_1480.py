#!/usr/bin/env python3
"""
tests/test_notion_journal_dark_1480.py — #1480 Notion journal channel dark >7d guard.

The generic per-source freshness loop tolerates Notion for 14 days (#746 — a lenient
evening-nudge threshold for ad-hoc journaling) AND the notion registry entry is
`monitored: False`, which structurally excludes it from the checker's SNS/CloudWatch
paging path entirely (`_active_monitored()` → `checker_sources()`). That's the root
cause of "dark for weeks with no alarm" — the journal is a daily-practice SOT
(enrichment → PERMA flourishing → the Mind pillar), and its generic tolerance is too
loose. This is a NEW, separate, tighter (7-day) ops-facing guard, analogous to the
existing check_apple_health_activity (DI-1.6) and MacroFactor format-drift guards.

Run: python3 -m pytest tests/test_notion_journal_dark_1480.py -v
"""

import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "emails"))

import freshness_checker_lambda as fc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# Fixed golden date — not derived from wall clock (see the golden-tests-wallclock lesson).
NOW = datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc)


def FakeNotionTable(last_entry_date_str=None, template_suffix="evening"):
    """Builds a FakeDdbTable serving a single latest DATE# journal sk (or none)."""
    if last_entry_date_str is None:
        return FakeDdbTable(rows=[])
    sk = f"DATE#{last_entry_date_str}#journal#{template_suffix}"
    return FakeDdbTable(rows=[{"sk": sk}])


def test_healthy_recent_entry_no_alert():
    last = (NOW.date() - timedelta(days=1)).isoformat()
    msg, m = fc.check_notion_journal_staleness(FakeNotionTable(last), NOW, sick_suppress=False)
    assert msg is None
    assert m["degraded"] == 0.0
    assert m["dark_days"] == 1.0


def test_at_threshold_boundary_no_alert():
    # exactly NOTION_JOURNAL_DARK_ALERT_DAYS old — not yet "dark" (> threshold, not >=)
    last = (NOW.date() - timedelta(days=fc.NOTION_JOURNAL_DARK_ALERT_DAYS)).isoformat()
    msg, m = fc.check_notion_journal_staleness(FakeNotionTable(last), NOW, sick_suppress=False)
    assert msg is None
    assert m["degraded"] == 0.0
    assert m["dark_days"] == float(fc.NOTION_JOURNAL_DARK_ALERT_DAYS)


def test_over_threshold_alerts_with_causal_chain_and_doc_pointer():
    last = (NOW.date() - timedelta(days=fc.NOTION_JOURNAL_DARK_ALERT_DAYS + 1)).isoformat()
    msg, m = fc.check_notion_journal_staleness(FakeNotionTable(last), NOW, sick_suppress=False)
    assert msg is not None
    assert m["degraded"] == 1.0
    assert m["dark_days"] == float(fc.NOTION_JOURNAL_DARK_ALERT_DAYS + 1)
    # The causal chain that makes journal staleness matter beyond the journal itself.
    assert "enrichment" in msg.lower()
    assert "perma" in msg.lower() or "flourishing" in msg.lower()
    assert "mind" in msg.lower()
    # Points at the doc this same PR adds (where to act — chat-mode journal-interview).
    assert "docs/coaching/CHAT_MODES.md" in msg


def test_no_entries_at_all_is_maximally_dark_not_a_crash():
    msg, m = fc.check_notion_journal_staleness(FakeNotionTable(None), NOW, sick_suppress=False)
    assert msg is not None
    assert m["degraded"] == 1.0
    assert m["dark_days"] > fc.NOTION_JOURNAL_DARK_ALERT_DAYS  # honestly "very dark", not 0 or NaN
    assert "no" in msg.lower() and ("entries" in msg.lower() or "entry" in msg.lower())


def test_sick_day_suppresses_alert_but_still_flags_metric():
    last = (NOW.date() - timedelta(days=fc.NOTION_JOURNAL_DARK_ALERT_DAYS + 3)).isoformat()
    msg, m = fc.check_notion_journal_staleness(FakeNotionTable(last), NOW, sick_suppress=True)
    assert msg is None
    assert m["degraded"] == 1.0


def test_query_error_is_non_fatal():
    def _boom(**kwargs):
        raise RuntimeError("ddb down")

    table = FakeDdbTable(rows=[], query_hook=_boom)
    msg, m = fc.check_notion_journal_staleness(table, NOW, sick_suppress=False)
    assert msg is None
    assert m["degraded"] == 0.0


# ── wiring: lambda_handler surfaces the new fields ────────────────────────────


def test_lambda_handler_return_has_notion_journal_fields(monkeypatch):
    """Full lambda_handler wiring smoke: the new fields land in the return dict
    (mirrors apple_health_activity_degraded's existing style, per the acceptance
    criteria) without needing to stub out every other guard in this file."""
    import fakes

    # A single shared FakeDdbTable services every guard's query/get_item/put_item
    # in lambda_handler — none of the other guards' queries in this pristine test
    # need real data; they degrade gracefully on empty results (see each guard's
    # own non-fatal try/except).
    table = fakes.FakeDdbTable(rows=[])
    monkeypatch.setattr(fc.dynamodb, "Table", lambda name: table)
    monkeypatch.setattr(fc.sns, "publish", lambda **kw: {})
    monkeypatch.setattr(fc.cw, "put_metric_data", lambda **kw: {})

    class _FakeSM:
        def describe_secret(self, **kw):
            raise RuntimeError("no secret in test")

    monkeypatch.setattr(fc.boto3, "client", lambda service, **kw: _FakeSM() if service == "secretsmanager" else fc.cw)

    result = fc.lambda_handler({}, None)
    assert "notion_journal_dark_days" in result
    assert "notion_journal_degraded" in result


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))

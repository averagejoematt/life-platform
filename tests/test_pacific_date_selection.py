"""tests/test_pacific_date_selection.py — the UTC-vs-Pacific date-selection fix.

Covers AUDIT BUG-01/02/03: scheduled lambdas (and the nutrition MCP "latest complete
day" default) must derive "today" from the *Pacific* calendar day the data is keyed
by, not from a raw UTC ``now``. An evening-PT cron fires at ~02:00–03:00 UTC — i.e.
tomorrow in PT — so a UTC "today" selects an empty future day.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pacific_time  # noqa: E402  (lambdas/ on sys.path via conftest)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2026-07-01 02:30 UTC == 2026-06-30 19:30 PDT — squarely inside the 7/8 PM PT cron
# window. The Pacific day is 06-30; a naive UTC "today" is the wrong 07-01.
EVENING_PT = datetime(2026, 7, 1, 2, 30, tzinfo=timezone.utc)
# 2026-06-30 19:00 UTC == 2026-06-30 12:00 PDT — midday, both agree.
MIDDAY_PT = datetime(2026, 6, 30, 19, 0, tzinfo=timezone.utc)


def _freeze(monkeypatch, module, instant):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _Frozen)


# ── canonical helper: lambdas/pacific_time ──────────────────────────────────────


def test_pacific_today_evening_returns_prior_utc_day(monkeypatch):
    _freeze(monkeypatch, pacific_time, EVENING_PT)
    assert pacific_time.pacific_today() == "2026-06-30"
    # the old behavior (raw UTC) would have picked the wrong future PT day:
    assert EVENING_PT.strftime("%Y-%m-%d") == "2026-07-01"


def test_pacific_today_midday_agrees_with_utc(monkeypatch):
    _freeze(monkeypatch, pacific_time, MIDDAY_PT)
    assert pacific_time.pacific_today() == "2026-06-30"


def test_pacific_now_is_tz_aware_pacific(monkeypatch):
    _freeze(monkeypatch, pacific_time, EVENING_PT)
    now = pacific_time.pacific_now()
    assert now.tzinfo is not None
    assert now.hour == 19  # 02:30 UTC -> 19:30 PDT


# ── MCP single-source mirror: mcp.core.pacific_today ────────────────────────────


def test_mcp_core_pacific_today_matches(monkeypatch):
    import mcp.core as core

    _freeze(monkeypatch, core, EVENING_PT)
    assert core.pacific_today() == "2026-06-30"


# ── source-regression guards: consumers must not revert to a UTC default ────────


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def test_circadian_handler_uses_pacific_today():
    src = _read("lambdas/compute/circadian_compliance_lambda.py")
    assert "from pacific_time import pacific_today" in src
    assert 'today_str = event.get("date") or pacific_today()' in src
    # the buggy UTC default must be gone from the handler date derivation:
    assert 'event.get("date") or datetime.now(timezone.utc)' not in src


def test_evening_nudge_handler_uses_pacific_today():
    src = _read("lambdas/emails/evening_nudge_lambda.py")
    assert "from pacific_time import pacific_today" in src
    assert "today = pacific_today()" in src
    assert "datetime.now(timezone.utc).strftime" not in src


def test_nutrition_latest_complete_day_is_pacific():
    src = _read("mcp/tools_nutrition.py")
    assert "pacific_today" in src
    # the two cited "latest complete day" defaults must no longer use a UTC now-1d:
    assert "datetime.now(timezone.utc) - timedelta(days=1)" not in src
    # but the 30/90-day window starts are intentionally left (boundary-immaterial):
    assert re.search(r"timedelta\(days=29\)|timedelta\(days=89\)", src)

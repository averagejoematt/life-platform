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

from common import pacific_time  # noqa: E402  (lambdas/ on sys.path via conftest)

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
    """#1964: mcp.core.pacific_today is now a DELEGATE, not a mirror.

    It used to re-implement the derivation with its own inline
    ``ZoneInfo("America/Los_Angeles")``, and this test froze ``mcp.core``'s own
    ``datetime`` to check the copy agreed. Freezing the CANONICAL module instead
    is the stronger assertion: it can only pass if mcp.core actually resolves
    through ``common.pacific_time``, i.e. the two can no longer drift apart.
    """
    import mcp.core as core

    _freeze(monkeypatch, pacific_time, EVENING_PT)
    assert core.pacific_today() == "2026-06-30" == pacific_time.pacific_today()


# ── source-regression guards: consumers must not revert to a UTC default ────────


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def test_circadian_handler_uses_pacific_today():
    src = _read("lambdas/compute/circadian_compliance_lambda.py")
    # #1964: the import line now also pulls PACIFIC + parse_iso_utc (the module's
    # own `_PT`/inline ISO parse were forks of the same helper), so match the
    # imported NAME rather than one exact spelling of the import statement.
    assert re.search(r"^from common\.pacific_time import .*\bpacific_today\b", src, re.M)
    assert 'today_str = event.get("date") or pacific_today()' in src
    # the buggy UTC default must be gone from the handler date derivation:
    assert 'event.get("date") or datetime.now(timezone.utc)' not in src


def test_evening_nudge_handler_uses_pacific_today():
    src = _read("lambdas/emails/evening_nudge_lambda.py")
    assert "from common.pacific_time import pacific_today" in src
    assert "today = pacific_today()" in src
    assert "datetime.now(timezone.utc).strftime" not in src


def test_nutrition_latest_complete_day_is_pacific():
    src = _read("mcp/tools_nutrition.py")
    assert "pacific_today" in src
    # the two cited "latest complete day" defaults must no longer use a UTC now-1d:
    assert "datetime.now(timezone.utc) - timedelta(days=1)" not in src
    # CORRECTION: this used to require a surviving `timedelta(days=29)` on the premise that
    # the 30-day window START was "boundary-immaterial". It was not. Pairing a UTC-derived
    # start with the Pacific-anchored end made the window 30 dates in the PT morning and 29
    # in the UTC-evening window — the frame mismatch changed its LENGTH, which every average
    # and deficiency verdict is computed over. `_nutrition_default_range` derives the start
    # from the RESOLVED Pacific end, so NO window start may read the UTC wall clock at all.
    assert "_nutrition_default_range" in src
    # Structural, not textual: the module no longer imports `timezone` at all, so no default
    # in it CAN read the UTC wall clock. (`datetime.now(timezone.utc)` still appears in the
    # helper's docstring, describing the bug it replaced — a grep would match that prose.)
    assert re.search(r"^from datetime import datetime, timedelta$", src, re.M)

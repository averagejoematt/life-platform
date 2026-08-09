"""tests/test_budget_headroom.py — #822 (R22-COST-05) budget-headroom readout.

The cost governor persists its projection breakdown (mtd / projected / ai +
non-ai trailing daily burn) to SSM /life-platform/budget-breakdown alongside
the tier; the daily brief renders one code-derived line from it so a
dev-sprint-only burn that threatens the $75 ceiling is visible where Matthew
already looks — not just as a tier flip after the fact.

Covers: the governor's persisted payload shape, the fail-soft reader
(stale/missing/malformed → None, never raises), the line formatting at tier 0
and tier 2 (+ the tier-1 incident fixture from the issue), Decimal-safety, and
the footer render hook. No AWS calls.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import budget_guard  # noqa: E402


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


# ── Fixtures: real-shaped breakdowns ─────────────────────────────────────────
# Tier-1 numbers are the 2026-07-06 incident from the issue: mtd=$13.43,
# projected=$83.24 vs the $75 ceiling, ai $1.79/day of a $2.68/day burn —
# a dev sprint alone, 6 days into the month.

# #2223 disposition: CLEARED, not frozen. Read live at import time, but every
# downstream use (below and in budget_guard.read_breakdown, which compares
# `datetime.now(utc) - computed_at` against a 48h `max_age_s`) is an
# ELAPSED-SECONDS measurement, never a calendar-day IDENTITY comparison — see
# tests/test_wallclock_globals_2223.py's ALLOWED_WALLCLOCK_GLOBALS entry for
# this name, which is the authoritative statement of why this one is safe.
_NOW = datetime.now(timezone.utc)


def _breakdown(**overrides):
    b = {
        "tier": 0,
        "mtd": 18.40,
        "projected": 52.0,
        "ceiling": 75.0,
        "ai_daily": 1.10,
        "non_ai_daily": 0.70,
        "computed_at": _NOW.isoformat(),
    }
    b.update(overrides)
    return b


TIER0 = _breakdown()
TIER1_INCIDENT = _breakdown(tier=1, mtd=13.43, projected=83.24, ai_daily=1.79, non_ai_daily=0.89)
TIER2 = _breakdown(tier=2, mtd=48.0, projected=90.0, ai_daily=2.40, non_ai_daily=0.90)


# ── Governor: _write_breakdown persists a JSON payload with the full shape ───


class _FakeSSM:
    def __init__(self, fail=False):
        self.fail = fail
        self.puts = []

    def put_parameter(self, **kwargs):
        if self.fail:
            raise RuntimeError("ssm down")
        self.puts.append(kwargs)


def test_governor_persists_breakdown_payload(gov, monkeypatch):
    fake = _FakeSSM()
    monkeypatch.setattr(gov, "_ssm", fake)
    now = datetime(2026, 7, 6, 0, 0, 14, tzinfo=timezone.utc)
    gov._write_breakdown(tier=1, mtd=13.434, projected=83.239, ai_daily=1.789, non_ai_daily=0.894, now=now)
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["Name"] == gov.SSM_BREAKDOWN_PARAM
    assert put["Type"] == "String" and put["Overwrite"] is True
    payload = json.loads(put["Value"])
    assert payload == {
        "tier": 1,
        "mtd": 13.43,
        "projected": 83.24,
        "ceiling": gov.MONTHLY_CEILING,
        "ai_daily": 1.79,
        "non_ai_daily": 0.89,
        "computed_at": "2026-07-06T00:00:14+00:00",
        # ADR-133 (#739): surge-mode fields, defaulted when the caller doesn't
        # pass them (pre-surge call sites keep working unchanged).
        "surge_active": False,
        "recent_uniques": None,
        "surge_threshold": gov.SURGE_UNIQUES_THRESHOLD,
        # #1999: the ADR-133 envelope the effective ceiling was drawn from, so no
        # consumer has to hardcode the base literal to describe it.
        "base_ceiling": gov._active_ceilings()[0],
        "surge_ceiling": max(gov._active_ceilings()[1], gov._active_ceilings()[0]),
        "ceiling_window": gov._active_ceiling_window(),
        # #2381: the per-band crossing forecast, derived from this same call's
        # mtd/burn/ceiling so the payload and the forecast can never disagree.
        "tier_crossings": gov._tier_crossing_forecast(13.434, 83.239, 1.789 + 0.894, now, gov.MONTHLY_CEILING),
    }


# ── #1999: the payload carries the ADR-133 envelope, not just one number ─────
# The defect: the payload named the EFFECTIVE ceiling only, so every consumer
# hardcoded the base to describe it, and a dated temp window reached the public
# receipt as an unattributed $85 → $115 delta with surge_active false.


def _force_temp_window(gov, monkeypatch, base=115.0, surge=135.0):
    """Put today inside a dated temp-ceiling window, whatever today is.

    The real July-2026 window has already auto-reverted, so pinning the test to
    it would make this a test of the calendar rather than of the mechanism —
    green today for the wrong reason and silent on the next window.
    """
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(gov, "_CEILING_ENV_OVERRIDE", False)
    monkeypatch.setattr(gov, "_TEMP_CEILING_WINDOW", (today - timedelta(days=3), today + timedelta(days=4)))
    monkeypatch.setattr(gov, "_TEMP_CEILING_USD", base)
    monkeypatch.setattr(gov, "_TEMP_SURGE_CEILING_USD", surge)
    return today


def test_breakdown_carries_the_active_pair_outside_any_window(gov, monkeypatch):
    fake = _FakeSSM()
    monkeypatch.setattr(gov, "_ssm", fake)
    monkeypatch.setattr(gov, "_CEILING_ENV_OVERRIDE", False)
    # A window that closed before today — the auto-revert case.
    past = datetime.now(timezone.utc).date() - timedelta(days=40)
    monkeypatch.setattr(gov, "_TEMP_CEILING_WINDOW", (past, past + timedelta(days=5)))

    gov._write_breakdown(tier=0, mtd=1.0, projected=2.0, ai_daily=0.1, non_ai_daily=0.1, now=_NOW)
    payload = json.loads(fake.puts[0]["Value"])

    assert payload["base_ceiling"] == gov.MONTHLY_CEILING
    assert payload["surge_ceiling"] == max(gov.SURGE_CEILING_USD, gov.MONTHLY_CEILING)
    assert payload["ceiling_window"] is None, "a closed window must not be advertised as active"


def test_breakdown_carries_the_dated_window_when_one_is_active(gov, monkeypatch):
    fake = _FakeSSM()
    monkeypatch.setattr(gov, "_ssm", fake)
    _force_temp_window(gov, monkeypatch, base=115.0, surge=135.0)
    start, end = gov._TEMP_CEILING_WINDOW

    gov._write_breakdown(tier=1, mtd=40.0, projected=96.0, ai_daily=1.5, non_ai_daily=0.9, now=_NOW, ceiling=115.0)
    payload = json.loads(fake.puts[0]["Value"])

    assert (payload["base_ceiling"], payload["surge_ceiling"]) == gov._active_ceilings() == (115.0, 135.0)
    win = payload["ceiling_window"]
    assert win["start"] == start.isoformat() and win["end_exclusive"] == end.isoformat()
    assert win["base_ceiling"] == 115.0 and win["surge_ceiling"] == 135.0
    # What it reverts TO is the whole point — the delta is unexplained without it.
    assert win["reverts_to_base_ceiling"] == gov.MONTHLY_CEILING
    assert win["reverts_to_surge_ceiling"] == gov.SURGE_CEILING_USD
    assert win["reason"] and isinstance(win["reason"], str)


def test_operator_env_override_reports_no_window(gov, monkeypatch):
    """An explicit MONTHLY_CEILING_USD defeats the window in _active_ceilings, so
    the payload must not claim a window set today's ceiling — the same lie in the
    other direction."""
    fake = _FakeSSM()
    monkeypatch.setattr(gov, "_ssm", fake)
    _force_temp_window(gov, monkeypatch)
    monkeypatch.setattr(gov, "_CEILING_ENV_OVERRIDE", True)

    gov._write_breakdown(tier=0, mtd=1.0, projected=2.0, ai_daily=0.1, non_ai_daily=0.1, now=_NOW)
    payload = json.loads(fake.puts[0]["Value"])
    assert payload["ceiling_window"] is None
    assert payload["base_ceiling"] == gov.MONTHLY_CEILING


def test_published_surge_ceiling_is_never_below_the_base(gov, monkeypatch):
    """_effective_ceiling floors surge at the base; the payload must publish the
    same floored pair or it advertises an envelope enforcement would never use."""
    fake = _FakeSSM()
    monkeypatch.setattr(gov, "_ssm", fake)
    _force_temp_window(gov, monkeypatch, base=120.0, surge=90.0)

    gov._write_breakdown(tier=0, mtd=1.0, projected=2.0, ai_daily=0.1, non_ai_daily=0.1, now=_NOW)
    payload = json.loads(fake.puts[0]["Value"])
    assert payload["base_ceiling"] == 120.0
    assert payload["surge_ceiling"] == 120.0


def test_governor_breakdown_write_failure_is_nonfatal(gov, monkeypatch):
    """Display-only artifact: an SSM failure must never propagate into the
    handler (the tier write has already happened by the time this runs)."""
    monkeypatch.setattr(gov, "_ssm", _FakeSSM(fail=True))
    gov._write_breakdown(tier=0, mtd=1.0, projected=2.0, ai_daily=0.1, non_ai_daily=0.1, now=_NOW)  # must not raise


# ── budget_guard.read_breakdown: fail-soft reader ────────────────────────────


class _FakeGuardSSM:
    def __init__(self, value=None, exc=None):
        self._value = value
        self._exc = exc

    def get_parameter(self, Name):
        if self._exc:
            raise self._exc
        return {"Parameter": {"Value": self._value}}


def _with_param(monkeypatch, value=None, exc=None):
    monkeypatch.setattr(budget_guard, "_ssm", _FakeGuardSSM(value=value, exc=exc))


def test_read_breakdown_fresh_roundtrip(monkeypatch):
    _with_param(monkeypatch, value=json.dumps(TIER1_INCIDENT))
    assert budget_guard.read_breakdown() == TIER1_INCIDENT


def test_read_breakdown_stale_returns_none(monkeypatch):
    old = _breakdown(computed_at=(_NOW - timedelta(hours=49)).isoformat())
    _with_param(monkeypatch, value=json.dumps(old))
    assert budget_guard.read_breakdown() is None


def test_read_breakdown_missing_key_returns_none(monkeypatch):
    incomplete = {k: v for k, v in TIER0.items() if k != "ai_daily"}
    _with_param(monkeypatch, value=json.dumps(incomplete))
    assert budget_guard.read_breakdown() is None


def test_read_breakdown_unparseable_returns_none(monkeypatch):
    _with_param(monkeypatch, value="not json {")
    assert budget_guard.read_breakdown() is None


def test_read_breakdown_ssm_error_returns_none(monkeypatch):
    _with_param(monkeypatch, exc=RuntimeError("ParameterNotFound"))
    assert budget_guard.read_breakdown() is None


def test_read_breakdown_naive_timestamp_treated_as_utc(monkeypatch):
    naive = _breakdown(computed_at=_NOW.replace(tzinfo=None).isoformat())
    _with_param(monkeypatch, value=json.dumps(naive))
    assert budget_guard.read_breakdown() is not None


# ── budget_guard.format_headroom_line: tier fixtures ─────────────────────────


def test_format_tier0_shows_headroom():
    line = budget_guard.format_headroom_line(TIER0)
    assert line == "Budget: tier 0 · projected $52 vs $75 ceiling · AI $1.10/day of the $1.80/day burn — $23 headroom"


def test_format_tier1_incident_matches_issue_example():
    """The 2026-07-06 fixture: projected over the ceiling → the slack clause
    says plainly that reader growth has nowhere to land.

    #1927 appends the paused-feature clause after it: the tier number alone never
    told the reader of this line WHAT had been switched off, which is half of why
    a 26-day blackout of the cutoff-1 band went unnoticed."""
    line = budget_guard.format_headroom_line(TIER1_INCIDENT)
    head, sep, paused = line.partition(" · paused: ")
    assert head == "Budget: tier 1 · projected $83 vs $75 ceiling · AI $1.79/day of the $2.68/day burn — near-zero slack for reader growth"
    assert sep, "a tier-1 line must name what tier 1 paused (#1927)"
    assert paused.startswith("5 AI features (")


def test_format_tier2_over_ceiling():
    line = budget_guard.format_headroom_line(TIER2)
    assert line.startswith("Budget: tier 2 · projected $90 vs $75 ceiling")
    # DERIVED from the registry, not a hand-typed count: the literal 13 went stale the
    # first time a feature was registered (#1675 made it 14). What is under test is that
    # the line names the paused SET honestly, not that the set is a particular size.
    expected = sum(1 for cutoff in budget_guard._FEATURE_CUTOFF.values() if cutoff <= 2)
    assert f"near-zero slack for reader growth · paused: {expected} AI features (" in line


def test_format_thin_slack_flagged():
    """Under the ceiling but <10% slack → still flagged as thin, not 'headroom'."""
    line = budget_guard.format_headroom_line(_breakdown(projected=70.0))
    assert "$5 slack, thin for reader growth" in line


def test_format_tier0_has_no_paused_clause():
    """#1927: nothing is paused at tier 0, so the line stays exactly as it was —
    the readout is a disclosure, not decoration."""
    assert "paused" not in budget_guard.format_headroom_line(TIER0)


def test_format_is_decimal_safe():
    """DDB-sourced callers hand Decimals; the formatter must coerce, not crash."""
    b = _breakdown(
        tier=Decimal("2"),
        mtd=Decimal("48.0"),
        projected=Decimal("90.0"),
        ceiling=Decimal("75"),
        ai_daily=Decimal("2.4"),
        non_ai_daily=Decimal("0.9"),
    )
    line = budget_guard.format_headroom_line(b)
    assert "tier 2" in line and "$90 vs $75" in line and "$2.40/day of the $3.30/day burn" in line


def test_format_surge_active_appends_surge_note():
    """ADR-133 (#739): when the governor's breakdown marks surge_active, the
    headroom line says so explicitly (readers, not spend)."""
    b = _breakdown(ceiling=100.0, projected=60.0, surge_active=True, recent_uniques=1200)
    line = budget_guard.format_headroom_line(b)
    assert "vs $100 ceiling" in line
    assert "SURGE mode (1200 uniques/7d, readers not spend)" in line


def test_format_surge_absent_key_is_backward_compatible():
    """A pre-surge breakdown payload (no surge_active/recent_uniques keys at
    all) must still render — .get() keeps this fail-soft."""
    line = budget_guard.format_headroom_line(TIER0)
    assert "SURGE" not in line


def test_format_carries_the_next_tier_crossing_date():
    """#2381: the clause names the NEXT band's projected in-force date, so the
    posture decision date is visible in the brief ~two weeks out instead of
    arriving as a mid-month scramble (July 2026's shape)."""
    b = _breakdown(tier=1, projected=110.0, tier_crossings={"1": "2026-08-09", "2": "2026-08-17", "3": "2026-08-20"})
    line = budget_guard.format_headroom_line(b)
    assert "tier 2 ~2026-08-17 at this burn" in line
    assert "tier 3" not in line  # only the NEXT band — one clause, not a table


def test_format_without_crossings_key_is_backward_compatible():
    """Older payloads (pre-#2381) omit tier_crossings; the line renders without
    the clause rather than degrading to empty."""
    line = budget_guard.format_headroom_line(TIER0)
    assert line and "at this burn" not in line


def test_format_no_upcoming_crossing_renders_no_clause():
    """Every crossing at-or-below the current tier (or None) → no clause."""
    b = _breakdown(tier=2, tier_crossings={"1": "2026-08-01", "2": "2026-08-05", "3": None})
    line = budget_guard.format_headroom_line(b)
    assert "at this burn" not in line


def test_format_none_and_malformed_are_empty():
    assert budget_guard.format_headroom_line(None) == ""
    assert budget_guard.format_headroom_line({}) == ""
    assert budget_guard.format_headroom_line({"tier": "x"}) == ""


# ── Footer render hook: line present when passed, absent by default ─────────


def test_brief_footer_renders_line_when_present():
    from content.html_builder import _brief_footer

    line = budget_guard.format_headroom_line(TIER1_INCIDENT)
    html = _brief_footer("", False, {}, "2026-07-06", budget_headroom_line=line)
    assert line in html


def test_brief_footer_omits_line_by_default():
    from content.html_builder import _brief_footer

    html = _brief_footer("", False, {}, "2026-07-06")
    assert "Budget: tier" not in html
    # and the goldens stay stable: default None renders nothing new
    assert "near-zero slack" not in html

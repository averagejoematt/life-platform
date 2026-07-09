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

import budget_guard  # noqa: E402


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


# ── Fixtures: real-shaped breakdowns ─────────────────────────────────────────
# Tier-1 numbers are the 2026-07-06 incident from the issue: mtd=$13.43,
# projected=$83.24 vs the $75 ceiling, ai $1.79/day of a $2.68/day burn —
# a dev sprint alone, 6 days into the month.

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
    }


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
    says plainly that reader growth has nowhere to land."""
    line = budget_guard.format_headroom_line(TIER1_INCIDENT)
    assert line == "Budget: tier 1 · projected $83 vs $75 ceiling · AI $1.79/day of the $2.68/day burn — near-zero slack for reader growth"


def test_format_tier2_over_ceiling():
    line = budget_guard.format_headroom_line(TIER2)
    assert line.startswith("Budget: tier 2 · projected $90 vs $75 ceiling")
    assert line.endswith("near-zero slack for reader growth")


def test_format_thin_slack_flagged():
    """Under the ceiling but <10% slack → still flagged as thin, not 'headroom'."""
    line = budget_guard.format_headroom_line(_breakdown(projected=70.0))
    assert "$5 slack, thin for reader growth" in line


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


def test_format_none_and_malformed_are_empty():
    assert budget_guard.format_headroom_line(None) == ""
    assert budget_guard.format_headroom_line({}) == ""
    assert budget_guard.format_headroom_line({"tier": "x"}) == ""


# ── Footer render hook: line present when passed, absent by default ─────────


def test_brief_footer_renders_line_when_present():
    from html_builder import _brief_footer

    line = budget_guard.format_headroom_line(TIER1_INCIDENT)
    html = _brief_footer("", False, {}, "2026-07-06", budget_headroom_line=line)
    assert line in html


def test_brief_footer_omits_line_by_default():
    from html_builder import _brief_footer

    html = _brief_footer("", False, {}, "2026-07-06")
    assert "Budget: tier" not in html
    # and the goldens stay stable: default None renders nothing new
    assert "near-zero slack" not in html

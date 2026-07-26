"""tests/test_pulse_since_yesterday_1813.py — #1813: /api/pulse's self-vs-self delta.

`/api/pulse`'s "since yesterday" block compares resolve_vitals' latest FINALIZED
whoop record (which can be a day or more stale — a normal sync-lag/genesis-week
state) against a query for "yesterday's" whoop record specifically. When the latest
finalized record IS dated yesterday, both queries return the SAME item: the delta is
structurally 0 — "Recovery →0%" / "Sleep →0.0h" — a measurement that never happened
(ADR-104). Separately, the #931 pre-start contract nulls the journey delta/scale
glyph but not `since_yesterday`/`notable_signals`, so a stale prior-cycle low-recovery
reading could surface as a live coaching warning inside a pre-genesis countdown
payload.

All dates are derived from real now(PT) — never wall-clock-literal fixtures
(reference_golden_tests_wallclock).
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (
    site_api_common as common,  # noqa: E402
    site_api_intelligence as intel,  # noqa: E402
)

_WHOOP_PK = "USER#matthew#SOURCE#whoop"


class FakeTable:
    """Answers table.query() from a {pk: [items]} fixture — matches the Key("pk").eq(...)
    operand inside KeyConditionExpression (and, when present, a Key("sk").between(...)
    range) so a query scoped to a specific date doesn't leak items outside it; anything
    unknown returns no items."""

    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    @staticmethod
    def _find_sk_range(cond):
        """Walk the condition tree for a Key("sk").between(lo, hi) node → (lo, hi), or
        None if there isn't one (a bare pk-only query)."""
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        key = vals[0] if vals else None
        if getattr(key, "name", None) == "sk" and getattr(cond, "expression_operator", None) == "BETWEEN" and len(vals) == 3:
            return (vals[1], vals[2])
        for v in vals:
            if hasattr(v, "_values"):
                found = FakeTable._find_sk_range(v)
                if found:
                    return found
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        sk_range = self._find_sk_range(cond) if cond is not None else None
        items = list(self.by_pk.get(pk, []))
        if sk_range:
            lo, hi = sk_range
            items = [i for i in items if lo <= str(i.get("sk", "")) <= hi]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _set_genesis(iso, monkeypatch):
    monkeypatch.setattr(common, "EXPERIMENT_START", iso)
    monkeypatch.setattr(intel, "EXPERIMENT_START", iso)


def _mock_common_deps(monkeypatch):
    monkeypatch.setattr(intel, "_latest_item", lambda *a, **k: None)
    monkeypatch.setattr(intel, "_get_profile", lambda: {"journey_start_weight_lbs": 315.0})


def test_recovery_and_sleep_delta_suppressed_when_same_record(monkeypatch):
    """The latest finalized whoop record IS dated yesterday — the 'since yesterday'
    query for whoop returns that identical item. No delta should be published for
    either signal (they would otherwise both compute to a fabricated 0)."""
    _set_genesis(_iso(_today_pt() - timedelta(days=30)), monkeypatch)
    _mock_common_deps(monkeypatch)
    yesterday = _iso(_today_pt() - timedelta(days=1))
    monkeypatch.setattr(
        intel,
        "table",
        FakeTable({_WHOOP_PK: [{"sk": f"DATE#{yesterday}", "recovery_score": 55, "sleep_duration_hours": 7.0}]}),
    )

    p = json.loads(intel.handle_pulse()["body"])["pulse"]
    signals = {s["signal"] for s in p["since_yesterday"]}
    assert "recovery" not in signals, "same-record comparison must not publish a fabricated 0% recovery delta"
    assert "sleep" not in signals, "same-record comparison must not publish a fabricated 0.0h sleep delta"


def test_recovery_and_sleep_delta_still_computed_across_distinct_days(monkeypatch):
    """Control: when 'current' and 'yesterday' really are two different records, the
    guard must not swallow a genuine delta."""
    _set_genesis(_iso(_today_pt() - timedelta(days=30)), monkeypatch)
    _mock_common_deps(monkeypatch)
    today = _iso(_today_pt())
    yesterday = _iso(_today_pt() - timedelta(days=1))
    monkeypatch.setattr(
        intel,
        "table",
        FakeTable(
            {
                _WHOOP_PK: [
                    {"sk": f"DATE#{today}", "recovery_score": 70, "sleep_duration_hours": 8.0},
                    {"sk": f"DATE#{yesterday}", "recovery_score": 55, "sleep_duration_hours": 7.0},
                ]
            }
        ),
    )

    p = json.loads(intel.handle_pulse()["body"])["pulse"]
    by_signal = {s["signal"]: s for s in p["since_yesterday"]}
    assert by_signal["recovery"]["delta"] == 15
    assert by_signal["sleep"]["delta"] == 1.0


def test_pre_start_clears_since_yesterday_and_notable_signals(monkeypatch):
    """A prior-cycle low-recovery reading exists in DDB (resolve_vitals has no genesis
    clamp by design) — but the countdown payload must carry NEITHER a since-yesterday
    delta NOR a notable-signal coaching warning; the experiment hasn't started."""
    start = _today_pt() + timedelta(days=2)
    _set_genesis(_iso(start), monkeypatch)
    _mock_common_deps(monkeypatch)
    stale = _iso(_today_pt() - timedelta(days=10))
    monkeypatch.setattr(
        intel,
        "table",
        FakeTable({_WHOOP_PK: [{"sk": f"DATE#{stale}", "recovery_score": 29, "sleep_duration_hours": 5.0}]}),
    )

    p = json.loads(intel.handle_pulse()["body"])["pulse"]
    assert p["pre_start"] is True
    assert p["since_yesterday"] == []
    assert p["notable_signals"] == []

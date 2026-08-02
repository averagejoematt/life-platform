"""tests/test_predict_week_freshness.py — #1198 + #1953 nightly predict-the-week guard.

Proves qa_smoke_lambda.check_predict_week_freshness:

  * FAILs the nightly when /api/predict_week is live on a stale ISO week (the #1198
    direction — the site-api _predict_subject fail-closed guard regressing), and
    passes when the subject is current;
  * distinguishes the three inactive states (#1953): fail-closed with NO live cycle
    (pre-genesis countdown) stays ok; DARK during a live-cycle week is a visible
    WARN on the first day and a content_truth FAIL once the persisted streak
    reaches >= 2 consecutive dark days (the state that produced 6 green nightlies
    while the widget was invisible for 6 days of a fresh cycle);
  * persists the dark streak Decimal-safely (ints, never floats) in the DDB state
    row, idempotent for a same-day re-run, resetting after a non-consecutive gap;
  * fail-SOFTs (warns, never reds, never crashes) on an unreachable API and on a
    DDB blip during streak bookkeeping.

Non-vacuous: the stale-week case and the 2-consecutive-dark-days case both assert
.passed is False — a guard that never fails would not satisfy them. The dark
fixtures FAILED against the pre-#1953 code (active:false was unconditionally ok).
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeTable:
    """Minimal stand-in for the module-level DDB table (streak state row only)."""

    def __init__(self, item=None, raise_on=()):
        self.item = item
        self.puts = []
        self.raise_on = set(raise_on)

    def get_item(self, Key):
        if "get" in self.raise_on:
            raise RuntimeError("ddb unavailable")
        assert Key["pk"] == qa.USER_PREFIX + "qa_predict_dark"
        return {"Item": self.item} if self.item else {}

    def put_item(self, Item):
        if "put" in self.raise_on:
            raise RuntimeError("ddb unavailable")
        self.puts.append(Item)
        return {}


def _patch(monkeypatch, payload=None, raise_exc=None, genesis="KEEP", table=None):
    def _urlopen(req, timeout=None):
        if raise_exc:
            raise raise_exc
        return _Resp(payload)

    monkeypatch.setattr(qa.urllib.request, "urlopen", _urlopen)
    # Pin "now" so the current ISO week is deterministic: 2026-07-16 -> 2026-W29.
    monkeypatch.setattr(qa, "pt_now", lambda: datetime(2026, 7, 16, 12, 0, 0))
    if genesis != "KEEP":
        monkeypatch.setattr(qa, "EXPERIMENT_START_DATE", genesis)
    monkeypatch.setattr(qa, "table", table if table is not None else _FakeTable())


# ── #1198 direction: live on a stale week — preserved unchanged ──────────────


def test_stale_week_fails_the_nightly(monkeypatch):
    _patch(monkeypatch, {"active": True, "week_id": "2026-W27"})
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is False
    assert "stale week" in c.message and "2026-W27" in c.message


def test_current_week_passes(monkeypatch):
    _patch(monkeypatch, {"active": True, "week_id": "2026-W29"})
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is True


def test_fetch_error_is_fail_soft(monkeypatch):
    _patch(monkeypatch, raise_exc=OSError("boom"))
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is None  # warn — a fetch blip must never red the nightly


# ── #1953 state (b): inactive with NO live cycle — fail-closed stays ok ──────


def test_inactive_before_genesis_passes(monkeypatch):
    """Pre-genesis countdown (cycle not started): a dark widget is the honest state."""
    _patch(monkeypatch, {"active": False}, genesis="2026-07-20")
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is True
    assert "no live cycle" in c.message


def test_inactive_with_unknown_genesis_passes(monkeypatch):
    """No genesis constant at all (import fallback) == no cycle running — stays ok."""
    _patch(monkeypatch, {"active": False}, genesis=None)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is True


# ── #1953 state (c): DARK during a live-cycle week ───────────────────────────


def test_dark_first_day_of_live_cycle_warns(monkeypatch):
    """First dark day mid-cycle: visible WARN (not green), streak row seeded at 1."""
    tbl = _FakeTable()
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is None  # WARN — never a silent green
    assert "DARK" in c.message
    assert len(tbl.puts) == 1
    item = tbl.puts[0]
    assert item["last_dark_date"] == "2026-07-16"
    assert item["streak"] == 1


def test_dark_two_consecutive_days_fails(monkeypatch):
    """>= 2 consecutive dark live-cycle days escalates to a content_truth FAIL.

    THE regression fixture from #1953: against the pre-fix code (active:false
    unconditionally ok) this asserted False on a check that returned True.
    """
    tbl = _FakeTable(item={"last_dark_date": "2026-07-15", "streak": Decimal("1")})
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is False
    assert c.partition == qa.CONTENT_TRUTH
    assert "2 consecutive" in c.message
    assert tbl.puts[0]["streak"] == 2


def test_dark_streak_is_decimal_safe(monkeypatch):
    """The persisted item must be DDB-safe: ints (or Decimal), never float."""
    tbl = _FakeTable(item={"last_dark_date": "2026-07-15", "streak": Decimal("4")})
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    qa.check_predict_week_freshness()
    item = tbl.puts[0]
    assert not any(isinstance(v, float) for v in item.values()), f"float in DDB item: {item}"
    assert isinstance(item["streak"], int) and item["streak"] == 5


def test_dark_same_day_rerun_is_idempotent(monkeypatch):
    """A manual re-invoke the same PT day must not double-count the streak."""
    tbl = _FakeTable(item={"last_dark_date": "2026-07-16", "streak": Decimal("3")})
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is False  # already >= 2
    assert tbl.puts[0]["streak"] == 3  # unchanged, not 4


def test_dark_streak_resets_after_gap(monkeypatch):
    """A non-consecutive dark day (widget was live in between) restarts at 1 -> WARN."""
    tbl = _FakeTable(item={"last_dark_date": "2026-07-10", "streak": Decimal("5")})
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is None  # back to first-day WARN
    assert tbl.puts[0]["streak"] == 1


def test_dark_ddb_blip_is_fail_soft(monkeypatch):
    """DDB read AND write failing (e.g. the IAM grant not yet deployed) degrades to
    the single-day WARN — never a crash, never a phantom FAIL, never a green."""
    tbl = _FakeTable(raise_on=("get", "put"))
    _patch(monkeypatch, {"active": False}, genesis="2026-07-13", table=tbl)
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is None
    assert "DARK" in c.message

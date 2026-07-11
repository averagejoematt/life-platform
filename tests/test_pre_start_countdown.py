"""tests/test_pre_start_countdown.py — the pre-start countdown contract (#931).

A reset can stage a FUTURE genesis (constants regenerate the night before Day 1),
leaving the whole site pre-genesis for a day or two. These tests pin the payload
contract for that window AND prove the feature is structurally inert while genesis
is in the past (the state this code ships in — it activates only when the reset
pipeline regenerates EXPERIMENT_START_DATE into the future):

  * pre_start_meta(): {pre_start, days_until_start, start_date} only when
    genesis > today (PT); None for today / past genesis.
  * /api/journey: carries the countdown fields, keeps day_n = 0, and suppresses
    every delta / progress / projection claim (no baseline exists before Day 1's
    weigh-in — ADR-104).
  * /api/journey with past genesis: pre_start is False and the numbers flow
    exactly as before (the inert-path proof).
  * /api/snapshot: the contract at the top level.
  * /api/pulse: the contract + the deterministic countdown narrative, no
    from-start scale delta.

The genesis dates are derived FROM the real now(PT) (future = today+2, past =
today-30), so there is no wall-clock time bomb (reference_golden_tests_wallclock).
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (
    site_api_common as common,  # noqa: E402
    site_api_intelligence as intel,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
)


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


FUTURE_GENESIS_DAYS = 2  # the real reset window: constants regenerate ~2 days ahead


def _set_genesis(monkeypatch, iso):
    """Point every module's imported EXPERIMENT_START at the same genesis."""
    for mod in (common, vitals, intel):
        monkeypatch.setattr(mod, "EXPERIMENT_START", iso)


def _mock_journey_deps(monkeypatch):
    """Minimal deterministic world for handle_journey: no weigh-ins (the wiped,
    pre-start state — the baseline fallback engages), a plain profile."""
    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: [])
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: None)
    monkeypatch.setattr(vitals, "_get_profile", lambda: {"journey_start_weight_lbs": 315.0, "goal_weight_lbs": 185.0})


class _EmptyTable:
    """DynamoDB table stub — every query returns no items (the wiped world)."""

    @staticmethod
    def query(**_kwargs):
        return {"Items": []}


# ── pre_start_meta ────────────────────────────────────────────────────────────


def test_pre_start_meta_future_genesis(monkeypatch):
    start = _today_pt() + timedelta(days=FUTURE_GENESIS_DAYS)
    _set_genesis(monkeypatch, _iso(start))
    meta = common.pre_start_meta()
    assert meta == {"pre_start": True, "days_until_start": FUTURE_GENESIS_DAYS, "start_date": _iso(start)}


def test_pre_start_meta_tomorrow_is_one_day(monkeypatch):
    start = _today_pt() + timedelta(days=1)
    _set_genesis(monkeypatch, _iso(start))
    assert common.pre_start_meta()["days_until_start"] == 1


def test_pre_start_meta_inert_for_today_and_past(monkeypatch):
    for delta in (0, -1, -30):
        _set_genesis(monkeypatch, _iso(_today_pt() + timedelta(days=delta)))
        assert common.pre_start_meta() is None, f"genesis today{delta:+d}d must be inert"


# ── /api/journey ──────────────────────────────────────────────────────────────


def test_journey_pre_start_contract(monkeypatch):
    start = _today_pt() + timedelta(days=FUTURE_GENESIS_DAYS)
    _set_genesis(monkeypatch, _iso(start))
    _mock_journey_deps(monkeypatch)

    j = json.loads(vitals.handle_journey()["body"])["journey"]

    # The countdown fields are ON.
    assert j["pre_start"] is True
    assert j["days_until_start"] == FUTURE_GENESIS_DAYS
    assert j["start_date"] == _iso(start)
    assert j["day_n"] == 0

    # Every delta / progress / projection claim is OFF — no baseline exists yet.
    for k in (
        "lost_lbs",
        "remaining_lbs",
        "progress_pct",
        "weekly_rate_lbs",
        "weekly_rate_ci_low",
        "weekly_rate_ci_high",
        "projected_goal_date",
        "projected_goal_date_earliest",
        "projected_goal_date_latest",
        "days_to_goal",
        "last_weighin_date",
        # #948: the weight and its as-of anchor travel together — a stale
        # prior-cycle weigh-in with a nulled last_weighin_date was an
        # unattributable ghost weight (and contradicted /api/vitals).
        "current_weight_lbs",
    ):
        assert j[k] is None, f"journey.{k} must be suppressed pre-start (got {j[k]!r})"

    # The non-claim anchors survive: start/goal (the staged baseline + the target).
    assert j["start_weight_lbs"] == 315.0
    assert j["goal_weight_lbs"] == 185.0


def test_journey_inert_when_genesis_past(monkeypatch):
    """The proof this PR can ship BEFORE the reset: with genesis in the past the
    pre_start path is a no-op — pre_start=False, and the claims flow untouched."""
    start = _today_pt() - timedelta(days=30)
    _set_genesis(monkeypatch, _iso(start))
    _mock_journey_deps(monkeypatch)

    # One real weigh-in series so lost_lbs is a real number.
    series = [{"sk": f"DATE#{_iso(start + timedelta(days=i))}", "weight_lbs": 315.0 - i * 0.5} for i in range(0, 28, 3)]
    monkeypatch.setattr(vitals, "_query_source", lambda source, *a, **k: series if source == "withings" else [])

    j = json.loads(vitals.handle_journey()["body"])["journey"]
    assert j["pre_start"] is False
    assert "days_until_start" not in j
    assert "start_date" not in j
    assert j["lost_lbs"] is not None and j["lost_lbs"] > 0
    assert j["progress_pct"] is not None
    assert j["day_n"] == 31  # 30 days ago, 1-indexed
    assert j["last_weighin_date"] is not None


# ── /api/snapshot ─────────────────────────────────────────────────────────────


def test_snapshot_pre_start_top_level(monkeypatch):
    start = _today_pt() + timedelta(days=FUTURE_GENESIS_DAYS)
    _set_genesis(monkeypatch, _iso(start))
    # The sub-handlers are exercised by their own tests — stub them here.
    ok_stub = {"statusCode": 200, "body": "{}"}
    monkeypatch.setattr(vitals, "handle_vitals", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "handle_journey", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "handle_character", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "_latest_readiness", lambda *a, **k: None)

    body = json.loads(vitals.handle_snapshot()["body"])
    assert body["pre_start"] is True
    assert body["days_until_start"] == FUTURE_GENESIS_DAYS
    assert body["start_date"] == _iso(start)


def test_snapshot_inert_when_genesis_past(monkeypatch):
    _set_genesis(monkeypatch, _iso(_today_pt() - timedelta(days=30)))
    ok_stub = {"statusCode": 200, "body": "{}"}
    monkeypatch.setattr(vitals, "handle_vitals", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "handle_journey", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "handle_character", lambda *a, **k: dict(ok_stub))
    monkeypatch.setattr(vitals, "_latest_readiness", lambda *a, **k: None)

    body = json.loads(vitals.handle_snapshot()["body"])
    assert body["pre_start"] is False
    assert "days_until_start" not in body
    assert "start_date" not in body


# ── /api/pulse ────────────────────────────────────────────────────────────────


def _mock_pulse_deps(monkeypatch):
    monkeypatch.setattr(intel, "table", _EmptyTable())
    monkeypatch.setattr(intel, "_latest_item", lambda *a, **k: None)
    monkeypatch.setattr(intel, "_get_profile", lambda: {"journey_start_weight_lbs": 315.0})


def test_pulse_pre_start_countdown(monkeypatch):
    start = _today_pt() + timedelta(days=FUTURE_GENESIS_DAYS)
    _set_genesis(monkeypatch, _iso(start))
    _mock_pulse_deps(monkeypatch)

    p = json.loads(intel.handle_pulse()["body"])["pulse"]
    assert p["pre_start"] is True
    assert p["days_until_start"] == FUTURE_GENESIS_DAYS
    assert p["start_date"] == _iso(start)
    assert p["day_number"] == 0

    # Deterministic countdown narrative — the anticipated launch, not "no data".
    start_dt = datetime.strptime(_iso(start), "%Y-%m-%d")
    assert p["narrative"] == (
        f"T−{FUTURE_GENESIS_DAYS} days. The instruments are on; the experiment begins "
        f"{start_dt.strftime('%A, %B')} {start_dt.day}. First baseline: that morning's weigh-in."
    )
    # No from-start weight delta — there is no baseline until Day 1's weigh-in.
    assert p["glyphs"]["scale"]["delta"] is None
    assert p["glyphs"]["scale"]["delta_label"] is None


def test_pulse_inert_when_genesis_past(monkeypatch):
    _set_genesis(monkeypatch, _iso(_today_pt() - timedelta(days=30)))
    _mock_pulse_deps(monkeypatch)

    p = json.loads(intel.handle_pulse()["body"])["pulse"]
    assert p["pre_start"] is False
    assert "days_until_start" not in p
    assert "start_date" not in p
    assert p["day_number"] == 31
    assert "instruments are on" not in p["narrative"]

"""
tests/test_benchmark_views.py — BENCH-1.3/1.4 get_benchmark view tests.

Mocks query_source so the views are exercised without AWS. Pins the board guardrails:
forward-framed strings (Nathan: never a failure tally), run gate above 240 lb (pace),
and confidence/n on every numeric block.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in ("AWS_REGION", "USER_ID", "TABLE_NAME", "DYNAMODB_TABLE", "S3_BUCKET"):
    os.environ.setdefault(k, "x")

import mcp.tools_benchmark as tb  # noqa: E402

# A failure-tally looks like "0 of 16", "15 regains", "0 held", "reversed N times".
_FAILURE_TALLY = re.compile(r"\b\d+\s*(?:of|/)\s*\d+\b|\bregain(?:ed|s)?\b|\bheld\b|\breversed\b|\bfail", re.I)

_REF = {
    "date": "2026-06-19",
    "sk": "DATE#2026-06-19",
    "bands": {"300-309": {"walks_wk": 10.0, "walk_hr_wk": 8.5, "runs_wk": 0.0, "lift_sessions_wk": 3.0}},
    "proven_curve": [
        {"weight": 307.0, "days_from_start": 0, "cum_lost": 0.0, "walks_wk": 10.0},
        {"weight": 300.0, "days_from_start": 14, "cum_lost": 7.0, "walks_wk": 11.0},
    ],
    "source_window": "2024-09-05..2025-04-30",
    "n_episodes_with_covariates": 6,
}


def _mock_query(monkeypatch, *, withings, strava, reference=_REF):
    def fake(source, start, end, *a, **k):
        if source == "training_reference":
            return [reference] if reference else []
        if source == "withings":
            return withings
        if source == "strava":
            return strava
        return []

    monkeypatch.setattr(tb, "query_source", fake)


def test_pace_run_gate_false_above_240_and_forward_framed(monkeypatch):
    withings = [
        {"date": "2026-06-05", "weight_lbs": 309.0},
        {"date": "2026-06-19", "weight_lbs": 305.0},
    ]
    strava = [{"date": "2026-06-15", "sport_type": "Walk"}]  # ~0.5 walks/wk over 14d
    _mock_query(monkeypatch, withings=withings, strava=strava)

    r = tb.tool_get_benchmark({"view": "pace", "date": "2026-06-19"})

    assert r["view"] == "pace"
    assert r["current"]["current_weight"] == 305.0
    assert r["run_gate_ok"] is False, "above 240 lb → run gate closed"
    assert r["proven"]["walks_wk_proven"] == 10.0
    assert r["walk_gap"] is not None and r["walk_gap"] > 0  # behind the proven walk volume
    # confidence + n on every numeric block
    assert r["current"]["confidence"] == "low" and "n" in r["current"]
    assert r["proven"]["confidence"] == "low" and "n" in r["proven"]
    # Forward-framed: mentions the lever, never tallies failures.
    assert "walking is" in r["signal"].lower()
    assert not _FAILURE_TALLY.search(r["signal"]), f"failure tally leaked: {r['signal']!r}"


def test_pace_run_gate_true_under_240(monkeypatch):
    withings = [{"date": "2026-06-19", "weight_lbs": 232.0}]
    _mock_query(monkeypatch, withings=withings, strava=[])
    r = tb.tool_get_benchmark({"view": "pace", "date": "2026-06-19"})
    assert r["run_gate_ok"] is True


def test_pace_no_reference_yet(monkeypatch):
    _mock_query(monkeypatch, withings=[{"date": "2026-06-19", "weight_lbs": 305.0}], strava=[], reference=None)
    r = tb.tool_get_benchmark({"view": "pace"})
    assert "status" in r and "reference" in r["status"].lower()


def test_unknown_view_lists_valid():
    r = tb.tool_get_benchmark({"view": "bogus"})
    assert "error" in r and "pace" in r["valid_views"]


# ── episodes view ──────────────────────────────────────────────────────────────

_EPISODES = [
    {
        "sk": "DATE#2025-04-30",
        "type": "loss",
        "rate_lb_wk": 3.0,
        "magnitude_lb": 118.0,
        "post_trough_8wk": {"walks_wk": 4.4},
        "outcome": "reversed",
    },
    {"sk": "DATE#2026-06-01", "type": "regain", "rate_lb_wk": 2.37, "magnitude_lb": 116.0},
]


def test_episodes_view_summary_and_asymmetry(monkeypatch):
    def fake(source, start, end, *a, **k):
        return _EPISODES if source == "weight_episodes" else []

    monkeypatch.setattr(tb, "query_source", fake)
    r = tb.tool_get_benchmark({"view": "episodes"})
    s = r["summary"]
    assert s["n_loss"] == 1 and s["n_regain"] == 1
    assert s["mean_loss_rate_lb_wk"] == 3.0 and s["mean_regain_rate_lb_wk"] == 2.37
    assert s["regain_to_loss_ratio"] == 0.79  # the ~0.79x asymmetry
    assert s["confidence"] == "low" and s["n"] == 2


# ── maintenance view (Nathan: forward only, no failure tally) ──────────────────


def test_maintenance_not_applicable_far_from_goal(monkeypatch):
    monkeypatch.setattr(tb, "get_profile", lambda: {"goal_weight_lbs": 185})
    _mock_query(monkeypatch, withings=[{"date": "2026-06-19", "weight_lbs": 305.0}], strava=[])
    r = tb.tool_get_benchmark({"view": "maintenance", "date": "2026-06-19"})
    assert r["applicable"] is False
    assert not _FAILURE_TALLY.search(r["signal"]), f"failure tally leaked: {r['signal']!r}"


def test_maintenance_near_goal_forward_framed_no_failure_tally(monkeypatch):
    monkeypatch.setattr(tb, "get_profile", lambda: {"goal_weight_lbs": 185})
    monkeypatch.setattr(tb, "_gate_signals", lambda: {"deficit_sustainability": {"available": False}})

    def fake(source, start, end, *a, **k):
        if source == "training_reference":
            return [_REF | {"bands": {"190-199": {"walks_wk": 12.0}}}]
        if source == "withings":
            return [{"date": "2026-06-19", "weight_lbs": 196.0}]
        if source == "weight_episodes":
            return _EPISODES
        return []

    monkeypatch.setattr(tb, "query_source", fake)
    r = tb.tool_get_benchmark({"view": "maintenance", "date": "2026-06-19"})
    assert r["applicable"] is True
    assert r["proven_floor_walks_wk"] == 12.0
    assert r["post_trough_signature_walks_wk"] == 4.4
    assert r["confidence"] == "low" and "n" in r
    # Nathan guardrail: the rendered signal must never tally failures/regains.
    assert not _FAILURE_TALLY.search(r["signal"]), f"failure tally leaked: {r['signal']!r}"
    assert "walking" in r["signal"].lower()

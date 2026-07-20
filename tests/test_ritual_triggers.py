"""tests/test_ritual_triggers.py — #1578 checkpoint triggers: the platform proposes the ritual.

Every trigger is DETERMINISTIC (ADR-105 — no LLM in the trigger) and HONEST about
absence (ADR-104 — a dark/thin source proposes nothing). These tests are hermetic:
the DDB reads (`_weight_series`/`_valence_series`/`_recovery_series`/`_active_experiments`)
and the cycle anchor (`_const.EXPERIMENT_START_DATE`) are monkeypatched at the point
mcp.ritual_triggers holds them, so no live AWS is touched. Coverage: each trigger's
fire and no-fire boundaries, the once-per-episode key shape, the personal-variance
thresholds (mood p25 / recovery p10), and the fail-soft orchestrator.
"""

import os
import sys
from datetime import date

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import mcp.ritual_triggers as rt  # noqa: E402

TODAY = date(2026, 8, 15)


def _anchor(monkeypatch, start_iso):
    monkeypatch.setattr(rt._const, "EXPERIMENT_START_DATE", start_iso)


# ── cycle_milestone (edge trigger, zero-AWS) ─────────────────────────────────
def test_cycle_milestones(monkeypatch):
    _anchor(monkeypatch, TODAY.isoformat())  # genesis == today
    g = rt._cycle_milestone(TODAY, None)
    assert len(g) == 1 and g[0]["fired_by"]["milestone"] == "genesis"
    assert g[0]["ritual"] == "/interview"
    assert g[0]["episode_key"] == f"cycle:{TODAY.isoformat()}:day1"

    _anchor(monkeypatch, "2026-08-08")  # 7 days before -> day_n 8 -> week-2
    w = rt._cycle_milestone(TODAY, None)
    assert w[0]["fired_by"]["milestone"] == "week-2"

    _anchor(monkeypatch, "2026-07-17")  # 29 days before -> day_n 30
    d = rt._cycle_milestone(TODAY, None)
    assert d[0]["fired_by"]["milestone"] == "day-30"


def test_cycle_pregenesis_and_nonmilestone_propose_nothing(monkeypatch):
    _anchor(monkeypatch, "2026-08-20")  # future genesis -> pre-genesis countdown
    assert rt._cycle_milestone(TODAY, None) == []
    _anchor(monkeypatch, "2026-08-13")  # day_n 3, not a milestone
    assert rt._cycle_milestone(TODAY, None) == []


# ── journal_dark (window trigger, reuses freshness) ──────────────────────────
def test_journal_dark_fires_on_stale_journal():
    fresh = {"flags": [{"source": "notion", "label": "Notion journal", "days_dark": 9}]}
    out = rt._journal_dark(TODAY, fresh)
    assert len(out) == 1
    s = out[0]
    assert s["ritual"] == "/journal-interview"
    assert s["episode_key"] == "journal_dark:notion:2026-08-06"  # 9 days before TODAY
    assert s["fired_by"]["days_dark"] == 9


def test_journal_dark_no_fire_under_threshold_or_absent():
    assert rt._journal_dark(TODAY, {"flags": [{"source": "notion", "days_dark": 3}]}) == []
    # A non-journaling stale source proposes nothing.
    assert rt._journal_dark(TODAY, {"flags": [{"source": "garmin", "days_dark": 20}]}) == []
    # ADR-104: no freshness data at all -> nothing.
    assert rt._journal_dark(TODAY, None) == []


# ── weight_milestone (band-crossing) ─────────────────────────────────────────
def test_weight_milestone_crossing_fires(monkeypatch):
    monkeypatch.setattr(rt, "_weight_series", lambda today: [("2026-08-10", 322.0), ("2026-08-15", 317.0)])
    out = rt._weight_milestone(TODAY, None)
    assert len(out) == 1
    assert out[0]["episode_key"] == "weight_milestone:320"
    assert out[0]["fired_by"]["band_lbs"] == 320


def test_weight_milestone_no_crossing_and_upward(monkeypatch):
    monkeypatch.setattr(rt, "_weight_series", lambda today: [("2026-08-10", 319.0), ("2026-08-15", 317.0)])
    assert rt._weight_milestone(TODAY, None) == []  # dropped but crossed no 5-lb band
    monkeypatch.setattr(rt, "_weight_series", lambda today: [("2026-08-10", 317.0), ("2026-08-15", 319.0)])
    assert rt._weight_milestone(TODAY, None) == []  # gained -> never celebrated
    monkeypatch.setattr(rt, "_weight_series", lambda today: [("2026-08-15", 317.0)])
    assert rt._weight_milestone(TODAY, None) == []  # one point -> no delta


# ── mood_slide (3-day decline + personal p25) ────────────────────────────────
def test_mood_slide_fires_when_declining_and_below_personal_p25(monkeypatch):
    series = [("d1", 5.0), ("d2", 3.0), ("d3", 4.0), ("d4", 3.0), ("d5", 2.0)]  # run d3>d4>d5, current 2
    monkeypatch.setattr(rt, "_valence_series", lambda today: series)
    out = rt._mood_slide(TODAY, None)
    assert len(out) == 1
    assert out[0]["coach"] == "mind" and out[0]["ritual"] == "/speak-to-coaches"
    assert out[0]["fired_by"]["run_days"] == 3
    assert out[0]["episode_key"] == "mood_slide:d3"


def test_mood_slide_no_fire_when_current_not_low(monkeypatch):
    # Declining run but current sits above his own p25 -> not low enough to matter.
    series = [("d1", 1.0), ("d2", 1.0), ("d3", 5.0), ("d4", 4.0), ("d5", 3.0)]
    monkeypatch.setattr(rt, "_valence_series", lambda today: series)
    assert rt._mood_slide(TODAY, None) == []


def test_mood_slide_no_fire_when_not_three_days(monkeypatch):
    series = [("d1", 5.0), ("d2", 4.0), ("d3", 5.0)]  # last step is up
    monkeypatch.setattr(rt, "_valence_series", lambda today: series)
    assert rt._mood_slide(TODAY, None) == []


# ── readiness_cliff (edge below personal p10) ────────────────────────────────
def test_readiness_cliff_fires_on_drop_below_p10(monkeypatch):
    series = [("d%02d" % i, 70.0) for i in range(17)] + [("d17", 40.0)]  # n=18, last below p10, prev above
    monkeypatch.setattr(rt, "_recovery_series", lambda today: series)
    out = rt._readiness_cliff(TODAY, None)
    assert len(out) == 1
    assert out[0]["coach"] == "mind"
    assert out[0]["fired_by"]["current_recovery"] == 40.0
    assert out[0]["episode_key"] == "readiness_cliff:d17"


def test_readiness_cliff_no_refire_when_already_below(monkeypatch):
    series = [("d%02d" % i, 70.0) for i in range(16)] + [("d16", 40.0), ("d17", 40.0)]  # prev already below
    monkeypatch.setattr(rt, "_recovery_series", lambda today: series)
    assert rt._readiness_cliff(TODAY, None) == []


def test_readiness_cliff_no_fire_when_thin_history(monkeypatch):
    series = [("d%02d" % i, 70.0) for i in range(9)] + [("d09", 40.0)]  # n=10 < MIN_N
    monkeypatch.setattr(rt, "_recovery_series", lambda today: series)
    assert rt._readiness_cliff(TODAY, None) == []


# ── experiment_midpoint (edge, planned end required) ─────────────────────────
def test_experiment_midpoint_fires_on_midpoint_day(monkeypatch):
    exp = {"experiment_id": "EXP#abc", "name": "Creatine", "start_date": "2026-08-10", "end_date": "2026-08-20"}
    monkeypatch.setattr(rt, "_active_experiments", lambda: [exp])
    out = rt._experiment_midpoint(TODAY, None)  # span 10, midpoint 2026-08-15 == TODAY
    assert len(out) == 1
    assert out[0]["ritual"] == "/vlog"
    assert out[0]["episode_key"] == "experiment_midpoint:EXP#abc"


def test_experiment_midpoint_no_fire_off_day_or_no_end(monkeypatch):
    off = {"experiment_id": "EXP#x", "name": "x", "start_date": "2026-08-01", "end_date": "2026-08-20"}
    monkeypatch.setattr(rt, "_active_experiments", lambda: [off])
    assert rt._experiment_midpoint(TODAY, None) == []
    open_ended = {"experiment_id": "EXP#y", "name": "y", "start_date": "2026-08-10", "end_date": None}
    monkeypatch.setattr(rt, "_active_experiments", lambda: [open_ended])
    assert rt._experiment_midpoint(TODAY, None) == []


# ── orchestrator ─────────────────────────────────────────────────────────────
def test_build_aggregates_and_is_fail_soft(monkeypatch):
    _anchor(monkeypatch, TODAY.isoformat())  # cycle genesis fires
    monkeypatch.setattr(rt, "_weight_series", lambda today: [])
    monkeypatch.setattr(rt, "_valence_series", lambda today: [])
    monkeypatch.setattr(rt, "_recovery_series", lambda today: [])

    def _boom():
        raise RuntimeError("simulated experiment read failure")

    monkeypatch.setattr(rt, "_active_experiments", _boom)  # one trigger explodes
    out = rt.build_suggested_rituals(TODAY, {"flags": [{"source": "notion", "days_dark": 10}]})
    rituals = {s["ritual"] for s in out["suggestions"]}
    assert "/interview" in rituals  # cycle genesis survived
    assert "/journal-interview" in rituals  # journal-dark survived
    assert out["count"] == len(out["suggestions"])  # the exploding trigger never took the section down
    assert "how_to_use" in out

"""
tests/test_episode_detect_algorithm.py — BENCH-1.2 reference-algorithm tests.

Two layers:
  1. Synthetic unit tests (CI-safe) — pin the pure turning-point / episode-detection /
     outcome / covariate functions on hand-built series with known answers.
  2. Real-validation test (datadrops-gated) — runs the SAME functions over the actual
     Withings/Strava history that produced PROVEN_BLUEPRINT.md and pins the workorder's
     validated values. `datadrops/` is gitignored, so this SKIPS in CI and runs locally.
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas" / "compute"))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")

import episode_detect_lambda as ed  # noqa: E402

DATADROPS = ROOT / "datadrops" / "training"


# ── Synthetic helpers ─────────────────────────────────────────────────────────


def _piecewise(legs, start="2021-01-01"):
    """legs = [(days, end_weight)]; builds daily (idx, vals) linear between leg ends."""
    from datetime import date, timedelta

    idx, vals = [], []
    cur = date.fromisoformat(start)
    w = legs[0][1]
    vals.append(w)
    idx.append(cur.isoformat())
    for days, target in legs[1:]:
        for k in range(1, days + 1):
            cur += timedelta(days=1)
            vals.append(w + (target - w) * k / days)
            idx.append(cur.isoformat())
        w = target
    return idx, vals


# ── 1. Synthetic unit tests ───────────────────────────────────────────────────


def test_turning_points_finds_peaks_and_troughs():
    # 300 → 275 → 295 → 280: P@300 (initial high locks), T@275, P@295. The final
    # T@280 isn't confirmed (series ends before a +min_swing rise off the new low).
    idx, vals = _piecewise([(0, 300.0), (70, 275.0), (70, 295.0), (70, 280.0)])
    tps = ed.turning_points(vals, idx)
    kinds = [k for _, k, _ in tps]
    assert kinds == ["P", "T", "P"], kinds
    assert round(tps[0][2]) == 300 and round(tps[1][2]) == 275 and round(tps[2][2]) == 295


def test_detect_episodes_loss_and_regain():
    idx, vals = _piecewise([(0, 300.0), (70, 275.0), (70, 295.0), (70, 280.0)])
    eps = ed.detect_episodes(idx, vals)
    types = [e["type"] for e in eps]
    assert types == ["loss", "regain"], types
    loss = eps[0]
    assert loss["w_start"] == 300.0 and loss["w_end"] == 275.0
    assert loss["magnitude_lb"] == 25.0
    assert loss["duration_wk"] == 10.0  # 70 days
    assert loss["rate_lb_wk"] == 2.5
    assert eps[1]["type"] == "regain" and eps[1]["magnitude_lb"] == 20.0


def test_min_episode_threshold_filters_small_swings():
    # 14-lb swing is above min_swing (12) but below min_episode (15) → no episode.
    idx, vals = _piecewise([(0, 300.0), (60, 286.0), (60, 300.0)])
    eps = ed.detect_episodes(idx, vals)
    assert eps == [], eps


def test_classify_loss_outcome_held_vs_reversed():
    # Lose 30 (300→270), then regain only 5 within 200d → held (< 30/3=10).
    idx, vals = _piecewise([(0, 300.0), (60, 270.0), (120, 275.0)])
    regain, outcome = ed.classify_loss_outcome(idx, vals, idx[60], 270.0, 30.0)
    assert outcome == "held" and regain < 10
    # Regain 20 within 200d → reversed (>= 10).
    idx2, vals2 = _piecewise([(0, 300.0), (60, 270.0), (120, 290.0)])
    _, outcome2 = ed.classify_loss_outcome(idx2, vals2, idx2[60], 270.0, 30.0)
    assert outcome2 == "reversed"


def test_weekly_covariates_normalizes_per_week():
    acts = [{"date": "2024-01-01", "kind": "walk", "hours": 1.0}] * 14  # 14 walks over 14 days = 7/wk
    cov = ed.weekly_covariates(acts, "2024-01-01", "2024-01-15", lift_sets=140.0)
    assert cov["walks_wk"] == 7.0
    assert cov["walk_hr_wk"] == 7.0
    assert cov["lift_sets_wk"] == 70.0  # 140 sets / 2 wk


def test_classify_activity_mapping():
    assert ed.classify_activity("Walk") == "walk"
    assert ed.classify_activity("Hike") == "walk"
    assert ed.classify_activity("Run") == "run"
    assert ed.classify_activity("Trail Run") == "run"
    assert ed.classify_activity("Weight Training") == "lift"
    assert ed.classify_activity("Elliptical") is None


def test_smooth_weight_interpolates_daily():
    idx, vals = ed.smooth_weight([("2024-01-01", 300.0), ("2024-01-11", 290.0)])
    assert len(idx) == 11  # 11 daily points inclusive
    assert idx[0] == "2024-01-01" and idx[-1] == "2024-01-11"


# ── 2. Real-validation (datadrops-gated; skips in CI) ─────────────────────────


def _load_weighins_from_csv():
    out = []
    with open(DATADROPS / "weight.csv") as f:
        for row in csv.DictReader(f):
            w = row.get("Weight (lb)")
            if w:
                out.append((row["Date"][:10], float(w)))
    return out


def _load_activities_from_csv():
    out = []
    with open(DATADROPS / "activities.csv") as f:
        for row in csv.DictReader(f):
            kind = ed.classify_activity(row.get("Activity Type"))
            if not kind:
                continue
            try:
                d = datetime.strptime(row["Activity Date"], "%b %d, %Y, %I:%M:%S %p").date().isoformat()
            except (ValueError, KeyError):
                continue
            secs = row.get("Moving Time") or row.get("Elapsed Time") or "0"
            out.append({"date": d, "kind": kind, "hours": (float(secs) if secs else 0.0) / 3600.0})
    return out


@pytest.mark.skipif(not (DATADROPS / "weight.csv").exists(), reason="datadrops/ not present (gitignored) — local-only validation")
def test_real_validation_reproduces_blueprint_values():
    """Pins the workorder's validated values against the real history (local-only)."""
    weigh_ins = _load_weighins_from_csv()
    activities = _load_activities_from_csv()
    idx, vals = ed.smooth_weight(weigh_ins)
    episodes = ed.enrich_episodes(idx, vals, ed.detect_episodes(idx, vals), activities, {})

    losses = [e for e in episodes if e["type"] == "loss"]
    regains = [e for e in episodes if e["type"] == "regain"]
    mean_loss = sum(e["rate_lb_wk"] for e in losses) / len(losses)
    mean_regain = sum(e["rate_lb_wk"] for e in regains) / len(regains) if regains else 0
    held = [e for e in losses if e.get("outcome") == "held"]
    print(f"\n[real] losses={len(losses)} regains={len(regains)} mean_loss={mean_loss:.2f} mean_regain={mean_regain:.2f} held={len(held)}")

    assert 14 <= len(losses) <= 18, f"expected ~16 loss episodes, got {len(losses)}"
    assert 2.5 <= mean_loss <= 3.6, f"mean loss rate ~3.0, got {mean_loss:.2f}"
    assert 1.9 <= mean_regain <= 3.0, f"mean regain rate ~2.4, got {mean_regain:.2f}"
    assert len(held) == 0, f"workorder: 0 episodes held, got {len(held)}"

    # The 2024-09 → 2025-04 reference cut: ~-118 lb / ~34 wk, covariate walks_wk ~11.4.
    big = max(losses, key=lambda e: e["magnitude_lb"])
    print(
        f"[real] biggest loss: {big['start_date']}→{big['end_date']} mag={big['magnitude_lb']} "
        f"dur_wk={big['duration_wk']} walks_wk={big['covariates_during'].get('walks_wk')} "
        f"post_trough_walks_wk={big.get('post_trough_8wk', {}).get('walks_wk')}"
    )
    assert big["start_date"] >= "2024-07-01" and big["end_date"] <= "2025-06-30"
    assert 108 <= big["magnitude_lb"] <= 125, f"reference cut ~118 lb, got {big['magnitude_lb']}"
    assert 28 <= big["duration_wk"] <= 40, f"reference cut ~34 wk, got {big['duration_wk']}"
    assert 8.0 <= big["covariates_during"]["walks_wk"] <= 15.0, big["covariates_during"]
    assert big["post_trough_8wk"]["walks_wk"] < big["covariates_during"]["walks_wk"], "post-trough walk collapse"

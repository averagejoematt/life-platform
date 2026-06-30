"""tests/test_what_changed.py — SS-08 monthly "what changed" (2026-06-30).

So a flat DAY still shows MOTION over the MONTH. Two real, low-fabrication halves,
both computed in weekly-correlation-compute:
  * deltas        — trailing-30d vs prior-30d averages, n>=10 real days each half,
                    never zero-filled/interpolated;
  * newly_unlocked — correlations FIRST FDR-significant within the trailing 30 days,
                    via a first-seen ledger so a pair is announced ONCE.
honest_null when both are empty (a calm "steady month", never fake motion).

All offline — pure helpers, no AWS.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "compute"))

import phase_taxonomy  # noqa: E402
import weekly_correlation_compute_lambda as wc  # noqa: E402


def _series(end="2026-06-30", cur_val=60.0, prior_val=50.0, key="recovery_score", days=15):
    """A 60-day series: `days` real values per half at cur_val (last 30d) / prior_val."""
    from datetime import datetime, timedelta

    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    s = {}
    for i in range(days):  # trailing-30d half (end .. end-14)
        s[(end_d - timedelta(days=i)).isoformat()] = {key: cur_val}
    for i in range(30, 30 + days):  # prior-30d half (end-30 .. end-44)
        s[(end_d - timedelta(days=i)).isoformat()] = {key: prior_val}
    return s


# ── deltas ────────────────────────────────────────────────────────────────────


def test_cumulative_delta_surfacing():
    s = _series(cur_val=60.0, prior_val=50.0)
    out = wc.compute_month_deltas(s, "2026-06-30")
    rec = next(d for d in out if d["metric"] == "recovery_score")
    assert rec["this_month_avg"] == 60.0 and rec["prior_month_avg"] == 50.0
    assert rec["delta"] == 10.0 and rec["direction"] == "improved"  # higher recovery is better
    assert rec["n_this"] >= 10 and rec["n_prior"] >= 10


def test_delta_direction_respects_higher_is_better():
    # resting_hr DOWN is an improvement.
    s = _series(cur_val=50.0, prior_val=58.0, key="resting_hr")
    rec = next(d for d in wc.compute_month_deltas(s, "2026-06-30") if d["metric"] == "resting_hr")
    assert rec["delta"] == -8.0 and rec["direction"] == "improved"


def test_delta_n_guard_omits_sparse_metric():
    # Only 5 real days per half (< min 10) → the metric is omitted, never fabricated.
    s = _series(days=5)
    assert wc.compute_month_deltas(s, "2026-06-30") == []


def test_flat_metric_omitted():
    s = _series(cur_val=55.0, prior_val=55.0)  # no movement
    assert all(d["metric"] != "recovery_score" for d in wc.compute_month_deltas(s, "2026-06-30"))


# ── newly-unlocked correlations ─────────────────────────────────────────────────


def _corr(sig=True, **extra):
    base = {
        "fdr_significant": sig,
        "metric_a": "hrv",
        "metric_b": "recovery_score",
        "pearson_r": 0.62,
        "n_days": 40,
        "direction": "positive",
    }
    base.update(extra)
    return base


def test_newly_unlocked_present_not_prior():
    fresh, ledger = wc.diff_newly_unlocked({"hrv_vs_recovery": _corr()}, {}, "2026-06-30")
    assert len(fresh) == 1 and fresh[0]["label"] == "hrv_vs_recovery"
    assert ledger["hrv_vs_recovery"] == "2026-06-30"  # stamped on first significance


def test_no_double_announce_outside_window():
    # First seen 60 days ago → significant now, but NOT freshly unlocked.
    prior = {"hrv_vs_recovery": "2026-05-01"}
    fresh, ledger = wc.diff_newly_unlocked({"hrv_vs_recovery": _corr()}, prior, "2026-06-30")
    assert fresh == []
    assert ledger["hrv_vs_recovery"] == "2026-05-01"  # date retained, not refreshed


def test_unlock_within_window_announced():
    prior = {"hrv_vs_recovery": "2026-06-20"}  # 10 days before end → within 30d
    fresh, _ = wc.diff_newly_unlocked({"hrv_vs_recovery": _corr()}, prior, "2026-06-30")
    assert len(fresh) == 1


def test_dropout_then_recross_not_readded():
    # significant (stamp old) → not significant → significant again: keeps old date, not re-announced.
    led = {"hrv_vs_recovery": "2026-05-01"}
    # not significant this run — ledger untouched, nothing fresh
    fresh, led = wc.diff_newly_unlocked({"hrv_vs_recovery": _corr(sig=False)}, led, "2026-06-15")
    assert fresh == [] and led["hrv_vs_recovery"] == "2026-05-01"
    # re-crosses later — still the original date, still not fresh
    fresh, led = wc.diff_newly_unlocked({"hrv_vs_recovery": _corr(sig=True)}, led, "2026-06-30")
    assert fresh == [] and led["hrv_vs_recovery"] == "2026-05-01"


def test_non_significant_never_unlocked():
    fresh, ledger = wc.diff_newly_unlocked({"x_vs_y": _corr(sig=False)}, {}, "2026-06-30")
    assert fresh == [] and "x_vs_y" not in ledger  # only FDR-significant pairs get stamped


# ── honest-null + reset safety ──────────────────────────────────────────────────


def test_honest_null_flat_month():
    # No deltas (sparse) + no significant correlations → honest-null condition.
    deltas = wc.compute_month_deltas(_series(days=5), "2026-06-30")
    fresh, _ = wc.diff_newly_unlocked({"x_vs_y": _corr(sig=False)}, {}, "2026-06-30")
    assert deltas == [] and fresh == []  # store_what_changed sets honest_null=True here


def test_what_changed_is_experiment_scoped():
    assert phase_taxonomy.classify("USER#matthew#SOURCE#what_changed", "SNAPSHOT#current") == phase_taxonomy.EXPERIMENT_SCOPED

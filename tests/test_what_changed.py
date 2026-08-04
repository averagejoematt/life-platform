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

import weekly_correlation_compute_lambda as wc  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402


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


# ── #1996: n-gate gloss (a downgraded label reads as a stats error without it) ──


def test_n_gate_gloss_present_on_downgrade():
    # r=0.88 alone earns "strong" (|r|>=0.6), but n=20 is below the n>=50 floor for
    # "strong" AND below the n>=30 floor for "moderate" — interpret_r downgrades
    # two levels to "weak". That downgrade is real and correct; it must be glossed.
    interp = wc.interpret_r(0.88, 20)
    assert interp == "weak"
    assert wc.n_gate_gloss(0.88, 20, interp) == "evidence still thin"


def test_n_gate_gloss_absent_when_label_matches_r():
    # r=0.65 at n=60 clears the "strong" floor outright — no downgrade, no gloss.
    interp = wc.interpret_r(0.65, 60)
    assert interp == "strong"
    assert wc.n_gate_gloss(0.65, 60, interp) is None


def test_n_gate_gloss_absent_for_genuinely_weak_r():
    # r=0.25 earns "weak" on magnitude alone (not a downgrade) — no gloss invented.
    interp = wc.interpret_r(0.25, 100)
    assert interp == "weak"
    assert wc.n_gate_gloss(0.25, 100, interp) is None


def test_n_gate_gloss_present_on_double_downgrade_to_insufficient():
    # r=0.5 alone earns "moderate", but n=5 is below even the "weak" floor (n>=10).
    interp = wc.interpret_r(0.5, 5)
    assert interp == "insufficient_data"
    assert wc.n_gate_gloss(0.5, 5, interp) == "evidence still thin"


def test_n_gate_gloss_tolerates_missing_inputs():
    assert wc.n_gate_gloss(None, 20, "weak") is None
    assert wc.n_gate_gloss(0.88, None, "weak") is None
    assert wc.n_gate_gloss(0.88, 20, None) is None
    assert wc.n_gate_gloss(0.88, 20, "") is None


def test_newly_unlocked_carries_gloss_for_high_r_weak_pair():
    # The regression guard's compute-layer half: a fresh high-r/small-n pair must
    # carry the gloss field in what diff_newly_unlocked hands the writer.
    pair = _corr(pearson_r=0.88, n_days=20, interpretation="weak")
    fresh, _ = wc.diff_newly_unlocked({"hrv_vs_recovery": pair}, {}, "2026-06-30")
    assert len(fresh) == 1
    assert fresh[0]["gloss"] == "evidence still thin"


def test_newly_unlocked_gloss_none_when_not_downgraded():
    pair = _corr(pearson_r=0.65, n_days=60, interpretation="strong")
    fresh, _ = wc.diff_newly_unlocked({"hrv_vs_recovery": pair}, {}, "2026-06-30")
    assert fresh[0]["gloss"] is None


def test_compute_correlations_results_carry_gloss_key():
    # The primary write path (compute_correlations' results[label]) sets "gloss"
    # directly from interpret_r's own verdict — proving the served payload's
    # SOURCE, not just the diff helper, carries the field. compute_correlations
    # always runs the full CORRELATION_PAIRS registry; a series that only carries
    # hrv/recovery_score leaves every other pair at r=None/gloss=None, harmlessly.
    from datetime import date, timedelta

    end = date(2026, 6, 30)
    series = {}
    for i in range(20):  # n=20 — below the n>=50 floor "strong" would need
        d = (end - timedelta(days=i)).isoformat()
        series[d] = {"hrv": 50.0 + i, "recovery_score": 40.0 + i}  # perfectly correlated → high |r|
    results = wc.compute_correlations(series)
    row = results["hrv_vs_recovery"]
    assert row["n_days"] == 20
    assert abs(row["pearson_r"]) >= 0.6  # earns "strong" on magnitude alone
    assert row["interpretation"] != "strong"  # n-gated down
    assert row["gloss"] == "evidence still thin"


# ── #1996 regression guard: served-label-matches-served-r invariant ─────────────
# A served entry where the n-gate demoted the label below what |r| alone earns
# MUST carry a non-empty `gloss` — otherwise a strong r next to a downgraded label
# reads as a stats error, not the rigor it is. Applies to every endpoint that
# serves a stored interpretation beside its r; /api/what_changed's newly_unlocked
# (read by both the home ribbon and the cockpit month view) is the first.


def _ngate_violations(entries):
    """Return the served entries that are n-gate-downgraded but missing `gloss`."""
    out = []
    for e in entries:
        r, n, interp = e.get("r"), e.get("n"), e.get("interpretation")
        if r is None or n is None or not interp:
            continue
        if wc.n_gate_gloss(r, n, interp) and not e.get("gloss"):
            out.append(e)
    return out


def test_ngate_gloss_invariant_flags_current_payload_shape():
    # The pre-#1996 payload shape: a high-r/'weak' pair with no gloss at all —
    # this is exactly "R=0.88, N=20, POSITIVE · WEAK" from the issue, and it
    # must trip the invariant.
    stale_entry = {"r": 0.88, "n": 20, "interpretation": "weak"}
    assert _ngate_violations([stale_entry]) == [stale_entry]


class _FakeTable:
    """Minimal DDB table stand-in for a get_item-only reader (site_api_ledger.what_changed)."""

    def __init__(self, item=None):
        self.item = item

    def get_item(self, Key=None, **kw):
        return {"Item": self.item} if self.item is not None else {}


def test_served_what_changed_satisfies_ngate_gloss_invariant():
    # End-to-end through the ACTUAL serving handler (site_api_ledger.what_changed) —
    # a high-r/small-n newly_unlocked entry, stored the way the fixed compute lambda
    # now writes it (with `gloss`), must reach the wire with the invariant satisfied.
    import json

    from web import site_api_ledger

    unlock = {
        "label": "hrv_vs_recovery",
        "metric_a": "hrv",
        "metric_b": "recovery_score",
        "r": 0.88,
        "n": 20,
        "direction": "positive",
        "interpretation": "weak",
        "gloss": "evidence still thin",
        "first_seen": "2026-06-30",
    }
    item = {
        "pk": "USER#matthew#SOURCE#what_changed",
        "sk": "SNAPSHOT#current",
        "week": "2026-W26",
        "window_start": "2026-06-01",
        "window_end": "2026-06-30",
        "deltas": [],
        "newly_unlocked": [unlock],
        "honest_null": False,
        "computed_at": "2026-06-30T18:30:00+00:00",
    }
    resp = site_api_ledger.what_changed(_g={"table": _FakeTable(item)})
    served = json.loads(resp["body"])["newly_unlocked"]
    assert served[0]["interpretation"] == "weak"  # the engine's own n-gated call, verbatim — never re-derived
    assert abs(served[0]["r"]) >= 0.6  # "strong" by magnitude alone — the mismatch that reads as an error
    assert _ngate_violations(served) == []


# ── honest-null + reset safety ──────────────────────────────────────────────────


def test_honest_null_flat_month():
    # No deltas (sparse) + no significant correlations → honest-null condition.
    deltas = wc.compute_month_deltas(_series(days=5), "2026-06-30")
    fresh, _ = wc.diff_newly_unlocked({"x_vs_y": _corr(sig=False)}, {}, "2026-06-30")
    assert deltas == [] and fresh == []  # store_what_changed sets honest_null=True here


def test_what_changed_is_experiment_scoped():
    assert phase_taxonomy.classify("USER#matthew#SOURCE#what_changed", "SNAPSHOT#current") == phase_taxonomy.EXPERIMENT_SCOPED

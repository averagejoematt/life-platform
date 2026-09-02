"""tests/test_calibration_accuracy_ci95_contract_3450.py — #3450.

ADR-105: every served accuracy must carry its uncertainty interval and n. Before
this fix, `calibration_core.score_pairs` served a bare `accuracy_pct` with no
interval anywhere — a 21.6% hit rate off n=37 (8 confirmed) reads as a precise
figure when the honest range is Wilson 95% [11.4%, 37.2%]. This is the contract
test the issue's acceptance box asks for: `accuracy_pct` never ships without
`accuracy_ci95` when there is anything resolved (n > 0), and the interval always
brackets the point estimate it accompanies.

Covers both the platform grader and the OSS extraction (`oss/calibration-core`)
so the contract holds on every implementation the parity suite pins together;
the JS port's numeric equality with the same fixture is already exercised by
tests/js/calibration_core.test.mjs.
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from experiment import calibration_core as platform_core  # noqa: E402

OSS_PY = os.path.join(ROOT, "oss", "calibration-core", "src", "calibration_core.py")


def _load_oss():
    spec = importlib.util.spec_from_file_location("oss_calibration_core_ci95_contract", OSS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oss_core = _load_oss()

IMPLEMENTATIONS = pytest.mark.parametrize("core", [platform_core, oss_core], ids=["platform", "oss"])

# (pairs, description) — deliberately spanning the edge cases a served interval
# must survive: nothing resolved, a single call either way, a perfect record
# (k=n, the case Wald normal-approximation collapses to zero width at), and the
# live DIL-039/040 specimen this issue names by number.
CASES = [
    ([], "empty — nothing resolved"),
    ([(0.8, 1)], "n=1, confirmed"),
    ([(0.8, 0)], "n=1, refuted"),
    ([(0.9, 1)] * 5, "n=5, k=n (perfect record — Wald would collapse to zero width)"),
    ([(0.9, 0)] * 5, "n=5, k=0"),
    ([(0.5, 1)] * 8 + [(0.5, 0)] * 29, "the DIL-039/040 specimen: 8 confirmed of 37"),
]


@IMPLEMENTATIONS
@pytest.mark.parametrize("pairs,desc", CASES, ids=[c[1] for c in CASES])
def test_accuracy_pct_never_ships_without_an_interval_when_n_gt_0(core, pairs, desc):
    summary = core.score_pairs(pairs)
    n = summary["n"]
    if n == 0:
        assert summary["accuracy_pct"] is None, desc
        assert summary["accuracy_ci95"] is None, desc
        return
    assert summary["accuracy_pct"] is not None, f"{desc}: n={n} but accuracy_pct is None"
    ci = summary["accuracy_ci95"]
    assert ci is not None, f"{desc}: n={n} but accuracy_ci95 is missing — ADR-105 violation"
    assert isinstance(ci, list) and len(ci) == 2, f"{desc}: accuracy_ci95 must be [lo, hi], got {ci!r}"
    lo, hi = ci
    assert 0.0 <= lo <= hi <= 100.0, f"{desc}: interval {ci} is not a valid [0,100] band"
    # The interval must bracket the point estimate it accompanies — an interval
    # that excludes its own headline number is worse than no interval at all.
    assert lo <= summary["accuracy_pct"] <= hi, f"{desc}: accuracy_pct {summary['accuracy_pct']} outside its own CI {ci}"


@IMPLEMENTATIONS
def test_the_dil_039_040_worked_specimen_matches_the_recorded_reading(core):
    """The exact number this issue was filed against: 8/37 -> 21.6%, Wilson 95%
    [11.4%, 37.2%] — pinned so a future scorer change that silently moves this
    number is caught here, not rediscovered by hand in a future review."""
    pairs = [(0.5, 1)] * 8 + [(0.5, 0)] * 29
    summary = core.score_pairs(pairs)
    assert summary["n"] == 37
    assert summary["confirmed"] == 8
    assert summary["accuracy_pct"] == 21.6
    assert summary["accuracy_ci95"] == [11.4, 37.2]


def test_the_two_implementations_agree_bit_for_bit():
    """Parity, restated for this specific field (test_calibration_core_parity.py
    already covers the whole dict via the committed vector fixture; this pins the
    new field explicitly so a future edit to just one copy is caught here too)."""
    for pairs, desc in CASES:
        p = platform_core.score_pairs(pairs)["accuracy_ci95"]
        o = oss_core.score_pairs(pairs)["accuracy_ci95"]
        assert p == o, f"{desc}: platform {p!r} != oss {o!r}"

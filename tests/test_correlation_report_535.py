"""Tests for helpers.correlation_report — #535 honesty-gated correlations.

Every correlation the tools report now carries r [CI], effective n, a two-sided p on
the effective n, a per-tool BH-FDR q-value, and a HARMFUL/BENEFICIAL verdict that is
only asserted when compute_confidence clears MEDIUM (else INCONCLUSIVE).
"""

import os
import random
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("DDB_TABLE", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from mcp.helpers import correlation_report  # noqa: E402


def _spec(key, xs, ys, direction="higher_is_better", label="Metric"):
    return {"key": key, "field": key, "xs": xs, "ys": ys, "direction": direction, "label": label}


def test_tiny_n_is_omitted():
    # n < 5 → no correlation reported at all (matches the old `if r_val is not None`).
    out = correlation_report([_spec("k", [1, 2, 3], [1, 2, 3])])
    assert out == {}


def test_every_reported_correlation_carries_its_uncertainty():
    random.seed(7)
    xs = [random.gauss(14, 2) for _ in range(25)]
    ys = [90 - 3 * x + random.gauss(0, 4) for x in xs]  # strong negative
    out = correlation_report([_spec("k", xs, ys)])
    c = out["k"]
    # r, CI, effective n, p, q all present.
    assert c["pearson_r"] is not None
    assert c["ci_low"] is not None and c["ci_high"] is not None
    assert c["ci_low"] <= c["pearson_r"] <= c["ci_high"]
    assert 0 < c["n_eff"] <= c["n"]
    assert c["p_value"] is not None
    assert c["q_value"] is not None
    assert c["confidence"] in ("LOW", "MEDIUM", "HIGH")


def test_strong_but_thin_correlation_is_not_called_harmful():
    # A big r on <30 effective days must NOT earn a HARMFUL verdict — that's the whole
    # point of #535. The r still stands; the causal-sounding label is withheld.
    random.seed(1)
    xs = [random.gauss(14, 2) for _ in range(20)]
    ys = [90 - 3 * x + random.gauss(0, 3) for x in xs]
    c = correlation_report([_spec("k", xs, ys)])["k"]
    assert abs(c["pearson_r"]) > 0.5  # genuinely strong
    assert c["confidence"] == "LOW"
    assert c["impact"] == "INCONCLUSIVE"  # withheld, not asserted


def test_noise_is_neutral_not_inconclusive():
    # A near-zero correlation is NEUTRAL regardless of confidence — there's no verdict to gate.
    random.seed(2)
    xs = [random.gauss(14, 2) for _ in range(25)]
    ys = [80 + random.gauss(0, 10) for _ in range(25)]  # no relationship
    c = correlation_report([_spec("k", xs, ys)])["k"]
    assert abs(c["pearson_r"]) < 0.15
    assert c["impact"] == "NEUTRAL"


def test_per_tool_fdr_inflates_q_above_p():
    # BH-FDR across a batch: q >= p for every entry (multiple-comparison correction).
    random.seed(5)
    specs = []
    for i in range(6):
        xs = [random.gauss(14, 2) for _ in range(22)]
        ys = [80 + random.gauss(0, 12) for _ in range(22)]
        specs.append(_spec(f"m{i}", xs, ys))
    out = correlation_report(specs)
    assert out  # some reported
    for c in out.values():
        assert c["q_value"] >= c["p_value"] - 1e-9

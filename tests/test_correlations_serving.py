"""tests/test_correlations_serving.py — /api/correlations serves p-values faithfully.

Replays the 2026-07-01 live bug: the compute lambda rounds p to 4 decimals, so a
highly-significant pair stores p_value=0.0 — and the serving layer's
`float(... or 1)` coerced that to 1.0, rendering the flagship FDR-significant
pair as "r 0.84 · p 1.000 · FDR ✓" on the one panel skeptics audit. Zero is a
value, not a missing value. Also pins the strength label to the served r
(the stored interpretation had r=0.843 labeled "weak").
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_data as sad  # noqa: E402


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


_RECORD = {
    "pk": "USER#matthew#SOURCE#weekly_correlations",
    "sk": "WEEK#2026-W26",
    "start_date": "2026-06-22",
    "end_date": "2026-06-28",
    "correlations": {
        "Habit Completion % ↔ Day Grade": {
            "metric_a": "habit_pct",
            "metric_b": "day_grade",
            "pearson_r": 0.843,
            "p_value": 0.0,  # rounded-to-zero at compute — maximally significant
            "n_days": 16,
            "fdr_significant": True,
            "interpretation": "weak",  # stored label disagrees with r — must not be served
        },
        "Steps ↔ Strain": {
            "metric_a": "steps",
            "metric_b": "strain",
            "pearson_r": 0.51,
            "p_value": 0.0412,
            "n_days": 14,
            "fdr_significant": False,
            "interpretation": "moderate",
        },
        "Protein ↔ Sleep Score": {
            "metric_a": "protein_g",
            "metric_b": "sleep_score",
            "pearson_r": 0.0,
            # no p_value at all — the degenerate insufficient-overlap case
            "n_days": 2,
            "fdr_significant": False,
            "interpretation": "insufficient_data",
        },
    },
}


def _pairs(event=None):
    sad.table = FakeDdbTable(rows=[_RECORD])
    resp = sad.handle_correlations(event)
    assert resp["statusCode"] == 200
    return _body(resp)


def _by_metrics(pairs, a, b):
    return next(p for p in pairs if p["field_a"] == a and p["field_b"] == b)


def test_p_zero_served_as_zero_not_one():
    body = _pairs()
    flagship = _by_metrics(body["correlations"]["pairs"], "habit_pct", "day_grade")
    assert flagship["p"] == 0.0, "p=0.0 must survive serving — `or 1` coerced it to 1.0"
    assert flagship["fdr_significant"] is True


def test_missing_p_served_as_none():
    body = _pairs()
    degenerate = _by_metrics(body["correlations"]["pairs"], "protein_g", "sleep_score")
    assert degenerate["p"] is None


def test_ordinary_p_passes_through():
    body = _pairs()
    mid = _by_metrics(body["correlations"]["pairs"], "steps", "strain")
    assert mid["p"] == 0.0412


def test_strength_label_agrees_with_r():
    body = _pairs()
    pairs = body["correlations"]["pairs"]
    assert _by_metrics(pairs, "habit_pct", "day_grade")["strength"] == "strong"
    assert _by_metrics(pairs, "steps", "strain")["strength"] == "moderate"
    # degenerate r=0 keeps the stored insufficient_data marker
    assert _by_metrics(pairs, "protein_g", "sleep_score")["strength"] == "insufficient_data"


def test_featured_filter_treats_p_zero_as_significant():
    body = _pairs({"queryStringParameters": {"featured": "true"}})
    metrics = {(p["field_a"], p["field_b"]) for p in body["correlations"]}
    assert ("habit_pct", "day_grade") in metrics
    assert ("steps", "strain") in metrics  # p=0.0412 < 0.05
    assert ("protein_g", "sleep_score") not in metrics  # p=None is not significant

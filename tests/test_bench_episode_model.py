"""
tests/test_bench_episode_model.py — BENCH-1.1 data-model shape tests.

Pins the weight_episodes / training_reference record shape + keying so the two new
computed sources stay readable via query_source exactly like computed_metrics:
PK = USER#{user}#SOURCE#{source}, SK = DATE#..., Decimal-typed numerics, and NO
`phase` attribute (cross-phase reference data that survives a reset).
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas" / "compute"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")

import episode_detect_lambda as ed  # noqa: E402

PK_EPISODES = "USER#matthew#SOURCE#weight_episodes"
PK_REFERENCE = "USER#matthew#SOURCE#training_reference"


def _sample_loss_episode():
    return {
        "episode_id": "2024-09-05_loss",
        "type": "loss",
        "start_date": "2024-09-05",
        "end_date": "2025-04-30",
        "w_start": 307.2,
        "w_end": 188.8,
        "magnitude_lb": 118.4,
        "duration_wk": 34.0,
        "rate_lb_wk": 3.48,
        "peak_rate_lb_wk": 4.9,
        "covariates_during": {"walks_wk": 11.4, "walk_hr_wk": 11.0, "runs_wk": 0.0, "lift_sessions_wk": 4.5, "lift_sets_wk": 128.0},
        "covariates_reliable": True,
        "post_trough_8wk": {"walks_wk": 4.4, "walk_hr_wk": 4.0},
        "regain_180d_lb": 42.0,
        "outcome": "reversed",
        "confidence": "low",
    }


def test_episode_record_keying_and_types():
    item = ed.build_episode_record(_sample_loss_episode())
    assert item["pk"] == PK_EPISODES
    assert item["sk"] == "DATE#2025-04-30"  # keyed by end_date (trough), query_source-readable
    assert item["episode_id"] == "2024-09-05_loss"
    assert item["type"] == "loss"
    # numerics are Decimal (boto3 rejects float)
    for f in ("w_start", "w_end", "magnitude_lb", "duration_wk", "rate_lb_wk", "peak_rate_lb_wk", "regain_180d_lb"):
        assert isinstance(item[f], Decimal), f"{f} must be Decimal"
    # nested covariates are Decimal too
    assert isinstance(item["covariates_during"]["walks_wk"], Decimal)
    assert isinstance(item["post_trough_8wk"]["walks_wk"], Decimal)
    # bool preserved (not coerced to Decimal)
    assert item["covariates_reliable"] is True
    assert item["outcome"] == "reversed"
    assert item["confidence"] == "low"


def test_episode_record_is_cross_phase():
    """No `phase` attribute → passes query_source's default filter + survives a reset."""
    item = ed.build_episode_record(_sample_loss_episode())
    assert "phase" not in item


def test_regain_episode_omits_loss_only_fields():
    regain = {
        "episode_id": "2025-05-01_regain",
        "type": "regain",
        "start_date": "2025-05-01",
        "end_date": "2026-06-01",
        "w_start": 188.8,
        "w_end": 305.0,
        "magnitude_lb": 116.2,
        "duration_wk": 56.0,
        "rate_lb_wk": 2.08,
        "covariates_during": {"walks_wk": 1.0},
        "covariates_reliable": True,
    }
    item = ed.build_episode_record(regain)
    assert item["type"] == "regain"
    assert "post_trough_8wk" not in item
    assert "regain_180d_lb" not in item
    assert "outcome" not in item


def test_training_reference_singleton_shape():
    ref = {
        "bands": {"300-309": {"walks_wk": 10, "walk_hr_wk": 8.5, "runs_wk": 0, "lift_sessions_wk": 3}},
        "proven_curve": [{"weight": 307.2, "days_from_start": 0, "cum_lost": 0.0, "walks_wk": 10.0}],
        "source_window": "2024-09-05..2025-04-30",
        "derived_at": "2026-06-19T10:00:00+00:00",
        "confidence": "low",
        "n_episodes_with_covariates": 6,
    }
    item = ed.build_training_reference_record(ref)
    assert item["pk"] == PK_REFERENCE
    assert item["sk"] == "DATE#2026-06-19"  # derived_date — newest-in-range read like computed_metrics
    assert isinstance(item["bands"]["300-309"]["walks_wk"], Decimal)
    assert isinstance(item["proven_curve"][0]["weight"], Decimal)
    assert isinstance(item["n_episodes_with_covariates"], Decimal)
    assert item["source_window"] == "2024-09-05..2025-04-30"
    assert "phase" not in item

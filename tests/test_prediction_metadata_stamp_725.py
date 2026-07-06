"""
tests/test_prediction_metadata_stamp_725.py — #725 code-stamped prediction metadata.

The legacy coach-thread path (`intelligence_common.extract_thread_from_narrative`)
used to let the LLM author `prediction_id` and `target_date` verbatim, so the live
ledger held 2024/2025-dated, duplicate, past-target predictions no evaluator could
grade (88 pending, 0 graded). This violated ADR-106 ("AI may sketch, only code
ships") at the exact point the platform's central claim depends on.

`stamp_thread_predictions` moves that authorship into code: the model writes only
claim text / confidence / metric / timeframe; code stamps a deterministic
`pred_{today}_{semantic-slug}` id and a strictly-future `target_date`, and carries
an open prior claim forward on its semantic key so daily re-emission updates one
record instead of minting a duplicate. These tests pin that contract.
"""

import os
import sys
from unittest.mock import patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import intelligence_common as ic  # noqa: E402

TODAY = "2026-07-05"


class TestStampIdentity:
    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_code_stamps_id_and_strips_model_authored_metadata(self, _r):
        # A hostile LLM output: a past-dated 2024 id AND a past target_date.
        out = ic.stamp_thread_predictions(
            "sleep",
            [
                {
                    "prediction_id": "pred_20240101_bogus",
                    "target_date": "2024-01-15",
                    "text": "HRV will rise",
                    "confidence": "high",
                    "metric": "hrv",
                }
            ],
            today=TODAY,
        )
        assert len(out) == 1
        rec = out[0]
        # id is code-stamped from today + a semantic slug, never the model's value
        assert rec["prediction_id"] == "pred_20260705_hrv_will_rise"
        assert rec["prediction_id"] != "pred_20240101_bogus"
        assert rec["semantic_key"] == "hrv_will_rise"

    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_wrong_date_is_repaired_to_strictly_future(self, _r):
        out = ic.stamp_thread_predictions(
            "sleep",
            [{"text": "sleep will improve", "confidence": "medium", "metric": "sleep_hours", "target_date": "2020-01-01"}],
            today=TODAY,
        )
        # the model's 2020 date is discarded; code stamps a strictly-future one
        assert out[0]["target_date"] > TODAY

    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_metric_bearing_claim_is_never_ungradeable_by_construction(self, _r):
        out = ic.stamp_thread_predictions(
            "sleep",
            [{"text": "recovery trends up", "confidence": "low", "metric": "recovery_score"}],  # no timeframe
            today=TODAY,
        )
        rec = out[0]
        assert rec["metric"] == "recovery_score"
        assert rec["target_date"] and rec["target_date"] > TODAY  # default window applied
        assert rec["status"] == "pending"


class TestTimeframeMapping:
    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_timeframe_windows(self, _r):
        cases = {
            "in 2 weeks": "2026-07-19",  # +14d
            "by next month": "2026-08-04",  # +30d
            "in 3 days": "2026-07-08",  # +3d
            "": "2026-07-19",  # default +14d
        }
        for tf, expected in cases.items():
            out = ic.stamp_thread_predictions("sleep", [{"text": f"claim {tf}", "metric": "hrv", "timeframe": tf}], today=TODAY)
            assert out[0]["target_date"] == expected, f"{tf!r} -> {out[0]['target_date']}, expected {expected}"


class TestDedup:
    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_within_batch_dedup_by_semantic_key(self, _r):
        out = ic.stamp_thread_predictions(
            "sleep",
            [
                {"text": "HRV will improve", "confidence": "high", "metric": "hrv"},
                {"text": "HRV will improve", "confidence": "low", "metric": "hrv"},  # same claim
            ],
            today=TODAY,
        )
        assert len(out) == 1  # collapsed to one record

    def test_daily_reemission_carries_prior_open_prediction_forward(self):
        # Yesterday the coach opened this prediction with a fixed deadline.
        prior = [
            {
                "predictions": [
                    {
                        "prediction_id": "pred_20260701_hrv_will_improve",
                        "semantic_key": "hrv_will_improve",
                        "text": "HRV will improve",
                        "target_date": "2026-07-15",
                        "first_seen": "2026-07-01",
                        "status": "pending",
                    }
                ]
            }
        ]
        with patch("intelligence_common.read_coach_thread", return_value=prior):
            out = ic.stamp_thread_predictions(
                "sleep",
                [{"text": "HRV will improve", "confidence": "medium", "metric": "hrv"}],
                today=TODAY,
            )
        rec = out[0]
        # re-emission UPDATES the same record: original id + deadline preserved,
        # not a fresh pred_20260705_* duplicate with a moving target.
        assert rec["prediction_id"] == "pred_20260701_hrv_will_improve"
        assert rec["target_date"] == "2026-07-15"
        assert rec["first_seen"] == "2026-07-01"
        assert rec["reaffirmed_on"] == TODAY

    def test_resolved_prior_prediction_is_not_carried_forward(self):
        # A prior prediction that already resolved must NOT block a fresh open one.
        prior = [
            {
                "predictions": [
                    {
                        "semantic_key": "hrv_will_improve",
                        "text": "HRV will improve",
                        "status": "confirmed",
                        "prediction_id": "pred_20260601_hrv_will_improve",
                    }
                ]
            }
        ]
        with patch("intelligence_common.read_coach_thread", return_value=prior):
            out = ic.stamp_thread_predictions("sleep", [{"text": "HRV will improve", "metric": "hrv"}], today=TODAY)
        # fresh stamp, not the resolved record's id
        assert out[0]["prediction_id"] == "pred_20260705_hrv_will_improve"


class TestSkips:
    @patch("intelligence_common.read_coach_thread", return_value=[])
    def test_empty_or_slugless_text_skipped(self, _r):
        out = ic.stamp_thread_predictions("sleep", [{"text": ""}, {"text": "   "}, {"confidence": "high"}], today=TODAY)
        assert out == []

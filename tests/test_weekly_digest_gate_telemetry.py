"""tests/test_weekly_digest_gate_telemetry.py — the Sunday-digest genesis-week crash.

2026-07-19 (the morning after cycle-8 genesis) the 16:00 UTC weekly-digest cron
crashed 10 retries into the ingestion DLQ: `data["this"]["withings"]` existed
WITH value None (the whole prior week phase-hidden by the reset), and
`.get("withings", {})` does not guard an existing-None key. Recurs every future
reset without the `or {}` guard — pinned here against the extracted pure helper.
"""

import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from emails import weekly_digest_lambda as wd  # noqa: E402

PROFILE = {"journey_start_weight_lbs": 315.65, "goal_weight_lbs": 185}


def test_genesis_week_none_withings_does_not_crash():
    # The literal crash shape: the key exists, holding None.
    gate = wd._gate_telemetry({"this": {"withings": None}}, PROFILE, 3)
    assert gate["current_weight"] is None  # honest absence, not a crash
    assert gate["real_subscribers"] == 3
    assert gate["start_weight"] == 315.65 and gate["goal_weight"] == 185


def test_missing_this_and_missing_withings_also_safe():
    assert wd._gate_telemetry({}, PROFILE, 0)["current_weight"] is None
    assert wd._gate_telemetry({"this": None}, PROFILE, 0)["current_weight"] is None
    assert wd._gate_telemetry({"this": {}}, PROFILE, 0)["current_weight"] is None


def test_normal_week_reads_the_weight():
    data = {"this": {"withings": {"weight_latest": 312.4}}}
    assert wd._gate_telemetry(data, PROFILE, 1)["current_weight"] == 312.4

"""tests/test_coach_daily_reflection.py — CC-08 writer guardrails (offline).

Verifies the PG-10 budget self-skip: at tier >= 2 the batch returns without
touching Bedrock or S3. (The generation path itself is integration-tested live;
here we prove the cost rail.)
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import budget_guard  # noqa: E402
from compute import coach_daily_reflection_lambda as writer  # noqa: E402


def test_self_skips_at_tier_2(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    out = writer.lambda_handler({}, None)
    assert out == {"skipped": True, "tier": 2}


def test_self_skips_at_tier_3(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    out = writer.lambda_handler({}, None)
    assert out.get("skipped") is True


def test_constants_sane():
    assert writer.SKIP_TIER == 2
    assert writer.OUTPUT_KEY == "generated/coach_daily.json"
    assert "haiku" in writer.MODEL.lower()

"""tests/test_inference_receipt_tier_4774.py — #4774 box 3: receipt rows carry the routing tier.

Each per-model and per-feature row of /api/inference_receipt names its model-routing registry
tier (`ai/model_routing.py`, #4770): `narrative` / `workhorse` / `economy`. A row the registry
cannot place carries tier null, and `attribution` counts those rows. The reconciliation
(models / features ratio) is untouched.

Mutation control: `test_mutation_control_*` drops the lookup and asserts the main test's
assertion would then fail — so the guard is proven able to fail.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from ai import model_routing  # noqa: E402
from web import site_api_intelligence as sad  # noqa: E402

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_DAY_START = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)

_MODELS = ["us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0", "mystery.model-9"]
_FNS = ["life-platform-chronicle", "daily-brief", "dev-session"]


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW.replace(tzinfo=None) if tz is None else _NOW.astimezone(tz)


class _CW:
    def list_metrics(self, Namespace, MetricName, **kw):
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": m}]} for m in _MODELS]}
        return {"Metrics": [{"Dimensions": [{"Name": "LambdaFunction", "Value": f}]} for f in _FNS]}

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        return {"MetricDataResults": [{"Id": q["Id"], "Timestamps": [_DAY_START], "Values": [100.0]} for q in MetricDataQueries]}


class _SSM:
    def get_parameter(self, Name):
        if Name == "/life-platform/budget-tier":
            return {"Parameter": {"Value": "0"}}
        return {"Parameter": {"Value": json.dumps({"ceiling": 85.0, "surge_active": False})}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(sad._budget, "datetime", _FrozenDateTime)
    monkeypatch.setattr(sad.boto3, "client", lambda service, **kw: _CW() if service == "cloudwatch" else _SSM())


def _receipt():
    resp = sad.handle_inference_receipt()
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _assert_tiers(p):
    by_model = {r["model"]: r for r in p["models"]}
    assert by_model["us.anthropic.claude-sonnet-4-6"]["tier"] == "narrative"
    haiku = by_model["us.anthropic.claude-haiku-4-5-20251001-v1:0"]
    assert haiku["tier"] == "workhorse" and haiku["tiers"] == ["workhorse", "economy", "vision"]
    assert by_model["mystery.model-9"]["tier"] is None
    by_fn = {r["lambda"]: r for r in p["features"]}
    assert by_fn["life-platform-chronicle"]["tier"] == "workhorse"
    assert by_fn["daily-brief"]["tier"] is None
    assert by_fn["dev-session"]["tier"] is None
    assert p["attribution"]["untiered_models"] == 1
    assert p["attribution"]["untiered_features"] == 2


def test_rows_carry_registry_tier_and_untiered_are_counted():
    _assert_tiers(_receipt())


def test_reconciliation_unchanged_by_tiering():
    p = _receipt()
    a = p["attribution"]
    assert a["models_est_cost_usd"] == p["ai_month_to_date_usd"]
    assert a["reconciliation_ratio"] == round(a["models_est_cost_usd"] / a["features_est_cost_usd"], 3)


def test_mutation_control_dropping_the_lookup_fails_the_tier_test(monkeypatch):
    monkeypatch.setattr(model_routing, "tier_for_model", lambda mid: None)
    monkeypatch.setattr(model_routing, "tier_for_feature", lambda name: None)
    with pytest.raises(AssertionError):
        _assert_tiers(_receipt())


def test_every_registry_model_resolves_to_its_tier():
    for tier, model in model_routing.TIER_MODELS.items():
        assert tier in model_routing.tiers_for_model(model)
        if model.startswith("claude-"):
            assert tier in model_routing.tiers_for_model("us.anthropic." + model + "-v1:0")

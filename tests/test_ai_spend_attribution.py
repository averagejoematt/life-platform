"""
tests/test_ai_spend_attribution.py — per-feature AI spend ranking (#808 · R22-COST-02).

Covers scripts/ai_spend_attribution.py with a fully stubbed CloudWatch client (no
AWS). Exercises the model back-solve, the window resolver, the month-end projection,
and one end-to-end main() render/JSON pass over canned metric data.

Run:  python3 -m pytest tests/test_ai_spend_attribution.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ai_spend_attribution as asa  # noqa: E402

# ── model back-solve ─────────────────────────────────────────────────────────


def _tok(cost, i=0, o=0, cr=0, cw=0):
    return {"cost": cost, "in": i, "out": o, "cache_read": cr, "cache_write": cw}


def test_guess_model_haiku():
    # 1M in @ $1 + 1M out @ $5 = $6.00 → haiku
    assert asa._guess_model(_tok(6.0, i=1_000_000, o=1_000_000)) == "haiku"


def test_guess_model_sonnet():
    # 1M in @ $3 + 1M out @ $15 = $18.00 → sonnet
    assert asa._guess_model(_tok(18.0, i=1_000_000, o=1_000_000)) == "sonnet"


def test_guess_model_mixed_when_no_tier_matches():
    # A cost between haiku ($6) and sonnet ($18) for the same tokens matches neither.
    assert asa._guess_model(_tok(12.0, i=1_000_000, o=1_000_000)) == "mixed"


def test_guess_model_no_signal():
    assert asa._guess_model(_tok(0.0)) == "-"
    assert asa._guess_model(_tok(5.0, i=0, o=0)) == "-"


# ── month-end projection ─────────────────────────────────────────────────────


def test_project_full_past_month_no_scaling():
    # A full June window (elapsed >= days_in_month) → factor clamped to 1.0.
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert asa._project(10.0, start, end) == pytest.approx(10.0)


def test_project_partial_month_scales_up():
    # 10 days into a 30-day month → ×3.
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 11, tzinfo=timezone.utc)
    assert asa._project(10.0, start, end) == pytest.approx(30.0, rel=1e-3)


# ── window resolver ──────────────────────────────────────────────────────────


class _Args:
    def __init__(self, month=None, days=None):
        self.month = month
        self.days = days


def test_window_month():
    start, end, label = asa._window(_Args(month="2026-06"))
    assert start == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert "2026-06" in label


def test_window_days():
    start, end, label = asa._window(_Args(days=7))
    assert (end - start).days == 7
    assert "trailing 7d" in label


def test_window_default_is_month_to_date():
    start, end, label = asa._window(_Args())
    assert start.day == 1
    assert "month-to-date" in label


# ── stubbed CloudWatch end-to-end ────────────────────────────────────────────


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        yield from self._pages


class _FakeCW:
    """Minimal CloudWatch stub: two features (one haiku, one sonnet) in
    LifePlatform/AI, plus one ModelId in AWS/Bedrock for the footer."""

    def get_paginator(self, op):
        if op == "list_metrics":
            return self  # dispatch in paginate via the last Namespace seen
        if op == "get_metric_data":
            return self
        raise AssertionError(op)

    # list_metrics + get_metric_data both route through paginate; branch on kwargs.
    def paginate(self, **kwargs):
        ns = kwargs.get("Namespace")
        if ns == asa.NAMESPACE:  # list_metrics for features
            yield {
                "Metrics": [
                    {"Dimensions": [{"Name": "LambdaFunction", "Value": "haiku-feat"}]},
                    {"Dimensions": [{"Name": "LambdaFunction", "Value": "sonnet-feat"}]},
                ]
            }
            return
        if ns == "AWS/Bedrock":  # list_metrics for ModelIds
            yield {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": "us.anthropic.claude-haiku-4-5"}]}]}
            return
        # get_metric_data (no Namespace kwarg — has MetricDataQueries)
        queries = kwargs["MetricDataQueries"]
        results = []
        for q in queries:
            metric = q["MetricStat"]["Metric"]
            name = metric["MetricName"]
            dims = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
            feat = dims.get("LambdaFunction")  # None for AWS/Bedrock ModelId queries
            results.append({"Id": q["Id"], "Values": [self._value(name, feat)]})
        yield {"MetricDataResults": results}

    @staticmethod
    def _value(name, feat):
        # per-feature LifePlatform/AI values
        if feat == "haiku-feat":
            return {
                "EstimatedCostUSD": 6.0,  # 1M in @1 + 1M out @5
                "AnthropicInputTokens": 1_000_000,
                "AnthropicOutputTokens": 1_000_000,
                "AnthropicCacheReadTokens": 0,
                "AnthropicCacheWriteTokens": 0,
            }.get(name, 0.0)
        if feat == "sonnet-feat":
            return {
                "EstimatedCostUSD": 18.0,  # 1M in @3 + 1M out @15
                "AnthropicInputTokens": 1_000_000,
                "AnthropicOutputTokens": 1_000_000,
                "AnthropicCacheReadTokens": 0,
                "AnthropicCacheWriteTokens": 0,
            }.get(name, 0.0)
        # AWS/Bedrock authoritative (feat is None; keyed on metric name)
        return {
            "InputTokenCount": 5_000_000,
            "OutputTokenCount": 1_000_000,
            "CacheReadInputTokenCount": 0,
            "CacheWriteInputTokenCount": 0,
        }.get(name, 0.0)


def test_list_and_fetch(monkeypatch):
    cw = _FakeCW()
    feats = asa._list_features(cw)
    assert feats == ["haiku-feat", "sonnet-feat"]
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    totals = asa._fetch(cw, feats, start, end)
    assert totals["haiku-feat"]["cost"] == pytest.approx(6.0)
    assert totals["sonnet-feat"]["out"] == pytest.approx(1_000_000)


def test_main_json_end_to_end(monkeypatch, capsys):
    monkeypatch.setattr(asa, "_cw", lambda: _FakeCW())
    rc = asa.main(["--month", "2026-06", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    feats = {f["feature"]: f for f in out["features"]}
    # ranked by cost desc: sonnet-feat ($18) before haiku-feat ($6)
    assert out["features"][0]["feature"] == "sonnet-feat"
    assert feats["haiku-feat"]["model"] == "haiku"
    assert feats["sonnet-feat"]["model"] == "sonnet"
    # authoritative footer: haiku ModelId → 5M in @1 + 1M out @5 = $10
    assert out["by_model_authoritative"]["haiku"] == pytest.approx(10.0)


def test_main_table_renders(monkeypatch, capsys):
    monkeypatch.setattr(asa, "_cw", lambda: _FakeCW())
    rc = asa.main(["--month", "2026-06"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "Per-feature AI spend" in text
    assert "haiku-feat" in text
    assert "Authoritative per-model" in text

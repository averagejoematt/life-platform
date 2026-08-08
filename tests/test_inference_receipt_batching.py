"""tests/test_inference_receipt_batching.py — #1911: the receipt must batch its metric reads.

/api/inference_receipt used to issue one `get_metric_statistics` per (metric, window,
dimension) — 6 models x 2 windows x 2 metrics + 19 lambdas x 2 metrics ~= 62 SEQUENTIAL
CloudWatch calls. Measured at the ORIGIN (not the edge), that cost:

    2026-07-29  ended 16:10:19.407 after 11,628 ms   (InitDuration absent — no cold start)
    2026-07-30  ended 18:00:15.636 after 14,934 ms   (InitDuration absent — no cold start)

Both align exactly with the site smoke's `curl --max-time 10` giving up, whose bare
`exit 28` auto-rolled-back a correct, merged, user-facing fix (#1891, then #1895).

The fix is GetMetricData — up to 500 queries in ONE round trip. Threads were rejected:
#1527 showed per-thread boto3 Sessions REGRESSED this fleet's origin latency 3.6s -> 12-16s.

These tests pin the CONTRACT that keeps it fast — call count, not wall-clock, so they
can't go flaky on a slow machine — plus the arithmetic, which must not change: `today` and
`month` now derive from ONE daily-bucketed series instead of two separately-fetched
windows, and the two must still agree with the old semantics.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from web import site_api_intelligence as sad  # noqa: E402  # #1911: batched GetMetricData sweep

# #2223: this used to be a live `datetime.now(timezone.utc)` read at import
# time — a genuine time bomb, not just latent. site_api_budget.inference_receipt()
# reads its own LIVE `datetime.now(timezone.utc)` again at call time
# (lambdas/web/site_api_budget.py:148 — that module takes no `_g` injection at
# all, per site_api_intelligence.py's own docstring) to classify "today" vs
# "month" buckets. A CI run whose EXECUTION crosses UTC midnight after this
# file's COLLECTION would reclassify every synthetic bucket below as
# yesterday's, and test_today_and_month_arithmetic_is_preserved's `today_total`
# would silently read 0 instead of 100. Fixed instant + freeze the handler's
# clock to match (`_freeze_budget_clock` below) instead.
_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_DAY_START = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)
_MONTH_START = _NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class _FrozenDateTime(datetime):
    """datetime whose now() is pinned to _NOW."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _NOW.replace(tzinfo=None)
        return _NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_budget_clock(monkeypatch):
    """Pin site_api_budget's live clock to the SAME instant _NOW / _DAY_START /
    _MONTH_START and every synthetic CloudWatch bucket below derive from."""
    monkeypatch.setattr(sad._budget, "datetime", _FrozenDateTime)


_MODELS = [f"us.anthropic.model-{i}" for i in range(6)]
_FNS = [f"life-platform-fn-{i}" for i in range(19)]


class _CountingCW:
    """Records every CloudWatch call so the test asserts on call COUNT."""

    def __init__(self, days_of_data=3):
        self.calls = {"list_metrics": 0, "get_metric_data": 0, "get_metric_statistics": 0}
        self.query_counts = []
        self.days = days_of_data

    def list_metrics(self, Namespace, MetricName, **kw):
        self.calls["list_metrics"] += 1
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": m}]} for m in _MODELS]}
        return {"Metrics": [{"Dimensions": [{"Name": "LambdaFunction", "Value": f}]} for f in _FNS]}

    def get_metric_statistics(self, **kw):
        self.calls["get_metric_statistics"] += 1
        raise AssertionError("#1911: the receipt must not fan out serial get_metric_statistics calls")

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        self.calls["get_metric_data"] += 1
        self.query_counts.append(len(MetricDataQueries))
        assert len(MetricDataQueries) <= 500, "GetMetricData accepts at most 500 queries per call"
        results = []
        for q in MetricDataQueries:
            # 100 tokens/day for `days` days ending today.
            ts, vals = [], []
            for d in range(self.days):
                day = _DAY_START - timedelta(days=d)
                if day < _MONTH_START:
                    continue
                ts.append(day)
                vals.append(100.0)
            results.append({"Id": q["Id"], "Timestamps": ts, "Values": vals})
        return {"MetricDataResults": results}


class _FakeSSM:
    def get_parameter(self, Name):
        if Name == "/life-platform/budget-tier":
            return {"Parameter": {"Value": "2"}}
        return {"Parameter": {"Value": json.dumps({"ceiling": 85.0, "surge_active": False})}}


@pytest.fixture
def cw(monkeypatch):
    fake = _CountingCW()

    def _client(service, **kw):
        return fake if service == "cloudwatch" else _FakeSSM()

    monkeypatch.setattr(sad.boto3, "client", _client)
    return fake


def _payload(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_metric_reads_are_batched_into_a_single_call(cw):
    """THE regression guard. 6 models x 4 metrics (in/out/cache_read/cache_write, #1997)
    + 19 lambdas x 2 metrics is 62 metric series; pre-#1911 fix that was ~62 SERIAL round
    trips. It must now be ONE batched call."""
    _payload(sad.handle_inference_receipt())
    assert cw.calls["get_metric_statistics"] == 0, "no serial per-metric fan-out may remain"
    assert cw.calls["get_metric_data"] == 1, f"expected exactly 1 batched read, got {cw.calls['get_metric_data']}"
    assert cw.calls["list_metrics"] == 2, "one discovery call per namespace"
    # 6 models x 4 metrics (in/out/cache_read/cache_write) + 19 lambdas x 2 metrics = 62
    # series, all in the one call.
    assert cw.query_counts == [62], f"all series must ride the single call, got {cw.query_counts}"


def test_total_cloudwatch_calls_stay_constant_as_metrics_grow(monkeypatch):
    """The old cost scaled with the number of models x lambdas — which grows through the
    month as more functions emit. The batched read must stay O(1) round trips."""
    fake = _CountingCW()
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: fake if s == "cloudwatch" else _FakeSSM())
    _payload(sad.handle_inference_receipt())
    small = sum(fake.calls.values())

    big = _CountingCW()
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: big if s == "cloudwatch" else _FakeSSM())
    monkeypatch.setattr(sys.modules[__name__], "_FNS", [f"life-platform-fn-{i}" for i in range(120)])
    _payload(sad.handle_inference_receipt())
    assert sum(big.calls.values()) == small, "round-trip count must not grow with the metric count"


def test_today_and_month_arithmetic_is_preserved(cw):
    """Semantics must not drift: `month` sums every daily bucket, `today` only the
    bucket at/after midnight UTC. The fake emits 100 tokens/day for 3 days."""
    body = _payload(sad.handle_inference_receipt())
    assert body["models"], "models must be present"
    row = body["models"][0]
    expected_days = min(3, (_DAY_START - _MONTH_START).days + 1)
    assert row["today"]["input_tokens"] == 100, "today = the current day's bucket only"
    assert row["month"]["input_tokens"] == 100 * expected_days, "month = every bucket in the window"
    assert row["month"]["input_tokens"] >= row["today"]["input_tokens"], "month can never be less than today"


def test_features_are_ranked_by_month_volume(cw):
    body = _payload(sad.handle_inference_receipt())
    totals = [f["month_input_tokens"] + f["month_output_tokens"] for f in body["features"]]
    assert totals == sorted(totals, reverse=True), "features must stay ranked by month volume"


def test_empty_metrics_makes_no_batched_call(monkeypatch):
    """GetMetricData rejects an empty query list — a platform with no AI usage yet (or a
    fresh genesis) must skip the call, not send an invalid one."""

    class _EmptyCW(_CountingCW):
        def list_metrics(self, Namespace, MetricName, **kw):
            self.calls["list_metrics"] += 1
            return {"Metrics": []}

    fake = _EmptyCW()
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: fake if s == "cloudwatch" else _FakeSSM())
    body = _payload(sad.handle_inference_receipt())
    assert fake.calls["get_metric_data"] == 0, "no metrics → no batched call"
    assert body["models"] == [] and body["features"] == []


# ── #1997: cache pricing, Titan exclusion, and the 1.15x buffer ────────────────
_SONNET_ID = "us.anthropic.claude-sonnet-4-6-v1:0"  # substring-matches "sonnet"
_TITAN_ID = "amazon.titan-embed-text-v2:0"  # matches no family key — must stay unpriced

# Governor prices as of this writing (lambdas/operational/cost_governor_lambda.py
# _PRICES["sonnet"] + _AI_SAFETY_BUFFER) — hand-copied here deliberately so this test
# fails loudly if either drifts, rather than silently tracking a moving target.
_SONNET_IN, _SONNET_OUT, _SONNET_CR, _SONNET_CW = 3.00, 15.00, 0.30, 3.75
_BUFFER = 1.15

_TOKENS = {
    (_SONNET_ID, "InputTokenCount"): 1000.0,
    (_SONNET_ID, "OutputTokenCount"): 200.0,
    (_SONNET_ID, "CacheReadInputTokenCount"): 500.0,
    (_SONNET_ID, "CacheWriteInputTokenCount"): 50.0,
    (_TITAN_ID, "InputTokenCount"): 400.0,
    (_TITAN_ID, "OutputTokenCount"): 0.0,
    (_TITAN_ID, "CacheReadInputTokenCount"): 10.0,
    (_TITAN_ID, "CacheWriteInputTokenCount"): 0.0,
}


class _PricingCW:
    """One sonnet-family model + one unmatched (Titan) model, no lambda features."""

    def __init__(self):
        self.calls = {"list_metrics": 0, "get_metric_data": 0, "get_metric_statistics": 0}

    def list_metrics(self, Namespace, MetricName, **kw):
        self.calls["list_metrics"] += 1
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": m}]} for m in (_SONNET_ID, _TITAN_ID)]}
        return {"Metrics": []}

    def get_metric_statistics(self, **kw):  # pragma: no cover
        raise AssertionError("must not fan out serial calls")

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        self.calls["get_metric_data"] += 1
        results = []
        for q in MetricDataQueries:
            stat = q["MetricStat"]["Metric"]
            key = (stat["Dimensions"][0]["Value"], stat["MetricName"])
            val = _TOKENS.get(key, 0.0)
            # A single reading today — keeps "today" and "month" identical, isolating
            # the pricing arithmetic from the day-bucketing logic (already covered above).
            results.append({"Id": q["Id"], "Timestamps": [_NOW], "Values": [val]})
        return {"MetricDataResults": results}


@pytest.fixture
def pricing_cw(monkeypatch):
    fake = _PricingCW()
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: fake if s == "cloudwatch" else _FakeSSM())
    return fake


def test_cache_tokens_and_buffer_priced_into_sonnet_row(pricing_cw):
    """Acceptance bullet 1 + 3: cache read/write tokens are priced at the governor's
    cache rates, and the x1.15 safety buffer is applied — matching cost_governor_lambda
    _ai_cost() exactly."""
    body = _payload(sad.handle_inference_receipt())
    sonnet_row = next(r for r in body["models"] if r["model"] == _SONNET_ID)

    expected_raw = (1000.0 * _SONNET_IN + 200.0 * _SONNET_OUT + 500.0 * _SONNET_CR + 50.0 * _SONNET_CW) / 1_000_000
    expected_cost = round(expected_raw * _BUFFER, 4)

    assert sonnet_row["today"]["est_cost_usd"] == expected_cost
    assert sonnet_row["month"]["est_cost_usd"] == expected_cost
    assert sonnet_row["today"]["cache_read_tokens"] == 500
    assert sonnet_row["today"]["cache_write_tokens"] == 50


def test_titan_shows_tokens_with_no_fabricated_price(pricing_cw):
    """Acceptance bullet 2: an unmatched model (Titan/embeddings) shows real token
    counts but est_cost_usd is None — never a silent Sonnet-rate guess."""
    body = _payload(sad.handle_inference_receipt())
    titan_row = next(r for r in body["models"] if r["model"] == _TITAN_ID)

    assert titan_row["today"]["input_tokens"] == 400
    assert titan_row["today"]["cache_read_tokens"] == 10
    assert titan_row["today"]["est_cost_usd"] is None
    assert titan_row["month"]["est_cost_usd"] is None


def test_month_total_reflects_only_priced_rows(pricing_cw):
    """ai_month_to_date_usd must never carry a Sonnet-rate guess for Titan's tokens —
    it should equal exactly the sonnet row's contribution (month_total is rounded to
    2dp for display, the per-row figure to 4dp — round before comparing)."""
    body = _payload(sad.handle_inference_receipt())
    sonnet_row = next(r for r in body["models"] if r["model"] == _SONNET_ID)
    assert body["ai_month_to_date_usd"] == round(sonnet_row["month"]["est_cost_usd"], 2)


def test_note_is_honest_about_unpriced_models(pricing_cw):
    """Acceptance bullet 2: the note must say, in-line, that an unpriced model was
    excluded and why — not silently omit it."""
    body = _payload(sad.handle_inference_receipt())
    assert _TITAN_ID in body["note"]
    assert "no verified per-token price" in body["note"]
    # the ceiling-figure substrings other tests pin must survive this change.
    assert "$75" not in body["note"]


def test_iam_grants_get_metric_data():
    """The batched read needs cloudwatch:GetMetricData. Without the grant the handler
    raises AccessDenied and the endpoint 503s — so the code and the policy must land
    together (an undeployed IAM change strands later CI deploys)."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "cdk", "stacks", "role_policies.py"), encoding="utf-8") as f:
        src = f.read()
    start = src.index('sid="InferenceReceiptMetrics"')
    block = src[start : start + 400]
    assert "cloudwatch:GetMetricData" in block, "#1911: site_api() must grant cloudwatch:GetMetricData"

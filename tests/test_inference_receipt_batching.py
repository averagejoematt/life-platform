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
from glob import glob
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
    + 19 lambdas x 3 metrics (in/out + #3555's EstimatedCostUSD) is 81 metric series;
    pre-#1911 fix each of those was a SERIAL round trip. It must be ONE batched call."""
    _payload(sad.handle_inference_receipt())
    assert cw.calls["get_metric_statistics"] == 0, "no serial per-metric fan-out may remain"
    assert cw.calls["get_metric_data"] == 1, f"expected exactly 1 batched read, got {cw.calls['get_metric_data']}"
    assert cw.calls["list_metrics"] == 2, "one discovery call per namespace"
    # 6 models x 4 metrics + 19 lambdas x 3 metrics = 81 series, all in the one call.
    # #3555 added the dollar series INSIDE this batch on purpose: publishing per-feature
    # cost must not cost a second round trip on the handler #1911 exists to keep at one.
    assert cw.query_counts == [81], f"all series must ride the single call, got {cw.query_counts}"


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
# #2883: Titan is a PRICED family now. `ai.bedrock_client.PRICES["titan"]` has carried the
# published $0.02/1M input rate since #1384, and the governor imports that registry instead
# of the hand-maintained copy that had no `titan` row (and therefore priced embedding tokens
# at the fable tier, $10/1M — 500x — into CostMetricDriftRatio's numerator).
_TITAN_ID = "amazon.titan-embed-text-v2:0"
# The unmatched-model negative control the Titan row used to provide. It has to be a model
# id that genuinely matches no family key, or "unmatched models stay unpriced" is asserted
# by nothing — a vacuous negative control passes exactly like a real one.
_UNPRICED_ID = "meta.llama3-70b-instruct-v1:0"

# Governor prices as of this writing (lambdas/operational/cost_governor_lambda.py
# _PRICES["sonnet"] + _AI_SAFETY_BUFFER) — hand-copied here deliberately so this test
# fails loudly if either drifts, rather than silently tracking a moving target.
_SONNET_IN, _SONNET_OUT, _SONNET_CR, _SONNET_CW = 3.00, 15.00, 0.30, 3.75
_TITAN_IN = 0.02  # #1384, published Titan Text Embeddings V2 rate
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
    (_UNPRICED_ID, "InputTokenCount"): 700.0,
    (_UNPRICED_ID, "OutputTokenCount"): 90.0,
    (_UNPRICED_ID, "CacheReadInputTokenCount"): 0.0,
    (_UNPRICED_ID, "CacheWriteInputTokenCount"): 0.0,
}


class _PricingCW:
    """One sonnet-family model + Titan (priced since #2883) + one genuinely unmatched
    model, no lambda features."""

    def __init__(self):
        self.calls = {"list_metrics": 0, "get_metric_data": 0, "get_metric_statistics": 0}

    def list_metrics(self, Namespace, MetricName, **kw):
        self.calls["list_metrics"] += 1
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": m}]} for m in (_SONNET_ID, _TITAN_ID, _UNPRICED_ID)]}
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


def test_unmatched_model_shows_tokens_with_no_fabricated_price(pricing_cw):
    """Acceptance bullet 2 (#1997), on a model that is actually unmatched: real token
    counts, `est_cost_usd is None` — never a silent Sonnet-rate guess."""
    body = _payload(sad.handle_inference_receipt())
    row = next(r for r in body["models"] if r["model"] == _UNPRICED_ID)

    assert row["today"]["input_tokens"] == 700
    assert row["today"]["est_cost_usd"] is None
    assert row["month"]["est_cost_usd"] is None


def test_titan_is_priced_at_its_published_rate(pricing_cw):
    """#2883: Titan stopped being the worked example of "unpriced". The rate is grounded
    (#1384, $0.02/1M input, embeddings have no output or cache tier) and the governor now
    imports the same registry the chokepoint prices with, so the receipt and
    CostMetricDriftRatio's two halves all agree on this model instead of disagreeing 500x."""
    body = _payload(sad.handle_inference_receipt())
    titan_row = next(r for r in body["models"] if r["model"] == _TITAN_ID)

    assert titan_row["today"]["input_tokens"] == 400
    assert titan_row["today"]["cache_read_tokens"] == 10
    expected = round((400.0 * _TITAN_IN) / 1_000_000 * _BUFFER, 4)
    assert titan_row["today"]["est_cost_usd"] == expected
    assert titan_row["month"]["est_cost_usd"] == expected
    # 400 embedding tokens is genuinely sub-cent. The point is the RATE, not the row:
    # at the fable tier the governor was using, the same tokens metered 500x higher.
    assert expected < round((400.0 * 10.00) / 1_000_000 * _BUFFER, 4)


def test_month_total_reflects_only_priced_rows(pricing_cw):
    """ai_month_to_date_usd must never carry a guessed rate for an unmatched model's
    tokens — the llama row contributes nothing (month_total is rounded to 2dp for
    display, the per-row figures to 4dp — round before comparing)."""
    body = _payload(sad.handle_inference_receipt())
    priced = [r for r in body["models"] if r["month"]["est_cost_usd"] is not None]
    assert {r["model"] for r in priced} == {_SONNET_ID, _TITAN_ID}
    assert body["ai_month_to_date_usd"] == round(sum(r["month"]["est_cost_usd"] for r in priced), 2)


def test_note_is_honest_about_unpriced_models(pricing_cw):
    """Acceptance bullet 2: the note must say, in-line, that an unpriced model was
    excluded and why — not silently omit it. #2883: it must name the model that is
    ACTUALLY unpriced and must no longer claim that of Titan."""
    body = _payload(sad.handle_inference_receipt())
    assert _UNPRICED_ID in body["note"]
    assert "no verified per-token price" in body["note"]
    assert _TITAN_ID not in body["note"]
    # the ceiling-figure substrings other tests pin must survive this change.
    assert "$75" not in body["note"]


def test_iam_grants_get_metric_data():
    """The batched read needs cloudwatch:GetMetricData. Without the grant the handler
    raises AccessDenied and the endpoint 503s — so the code and the policy must land
    together (an undeployed IAM change strands later CI deploys)."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # #2604: site_api()'s statements moved to the role_policies_serve.py sibling behind the
    # role_policies.py facade — scan the family so the pin follows the policy, not the file.
    src = next(
        (
            t
            for t in (open(p, encoding="utf-8").read() for p in sorted(glob(os.path.join(repo, "cdk", "stacks", "role_policies*.py"))))
            if 'sid="InferenceReceiptMetrics"' in t
        ),
        None,
    )
    assert src is not None, "#1911: no role_policies*.py declares sid=InferenceReceiptMetrics"
    start = src.index('sid="InferenceReceiptMetrics"')
    block = src[start : start + 400]
    assert "cloudwatch:GetMetricData" in block, "#1911: site_api() must grant cloudwatch:GetMetricData"


# ══════════════════════════════════════════════════════════════════════════════
# #3555 — per-feature DOLLARS, and one row per Lambda
#
# COST-03: /api/receipts withheld a per-feature dollar column citing "the per-Lambda
# metric stream carries no model dimension, so pricing it would mean inventing a model
# mix". That reason was never true of this platform. `ai.bedrock_client
# ._emit_usage_metrics` resolves the model on every call and emits
# `EstimatedCostUSD{LambdaFunction}` priced from it — landed #142 (2026-06-16), five
# weeks BEFORE the sentence was written (#1616, 2026-07-21), and
# `scripts/ai_budget_ledger.py` has graded per-feature dollars off that same series
# since #3374.
#
# COST-04: `list_metrics` returns one entry per dimension COMBINATION. site-api-ai emits
# its own inline token metrics ([LambdaFunction, Endpoint]) beside the chokepoint's bare
# [LambdaFunction], so it came back three times and the receipt appended three
# byte-identical rows — live 2026-09-05, 108,654 / 7,314 three times. Every query asks
# for the bare dimension set, so the extra rows were duplicates, not detail.
# ══════════════════════════════════════════════════════════════════════════════
_DUP_FN = "life-platform-site-api-ai"
_SOLO_FN = "daily-brief"
# Per-day values the fake returns, keyed by metric. One day of data (see _MultiDimCW),
# so month == today and the arithmetic is isolated from the bucketing logic.
_FEATURE_TOKENS_IN = 1000.0
_FEATURE_TOKENS_OUT = 200.0
_FEATURE_COST = 0.5


class _MultiDimCW:
    """list_metrics returns site-api-ai under THREE dimension sets (two carrying an
    Endpoint, one bare) — the live shape — plus one ordinary single-dimension feature."""

    def __init__(self, cost_for=(_DUP_FN, _SOLO_FN)):
        self.calls = {"list_metrics": 0, "get_metric_data": 0, "get_metric_statistics": 0}
        self.query_counts = []
        self._cost_for = set(cost_for)

    def list_metrics(self, Namespace, MetricName, **kw):
        self.calls["list_metrics"] += 1
        if Namespace == "AWS/Bedrock":
            return {"Metrics": []}
        return {
            "Metrics": [
                {"Dimensions": [{"Name": "Endpoint", "Value": "api_ask"}, {"Name": "LambdaFunction", "Value": _DUP_FN}]},
                {"Dimensions": [{"Name": "Endpoint", "Value": "api_board_ask"}, {"Name": "LambdaFunction", "Value": _DUP_FN}]},
                {"Dimensions": [{"Name": "LambdaFunction", "Value": _DUP_FN}]},
                {"Dimensions": [{"Name": "LambdaFunction", "Value": _SOLO_FN}]},
            ]
        }

    def get_metric_statistics(self, **kw):  # pragma: no cover
        raise AssertionError("must not fan out serial calls")

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        self.calls["get_metric_data"] += 1
        self.query_counts.append(len(MetricDataQueries))
        results = []
        for q in MetricDataQueries:
            stat = q["MetricStat"]["Metric"]
            fn = stat["Dimensions"][0]["Value"]
            name = stat["MetricName"]
            if name == "EstimatedCostUSD":
                if fn not in self._cost_for:
                    # No datapoints at all — the "never metered" case, which must
                    # publish as null and not as $0.00.
                    results.append({"Id": q["Id"], "Timestamps": [], "Values": []})
                    continue
                val = _FEATURE_COST
            elif name == "AnthropicInputTokens":
                val = _FEATURE_TOKENS_IN
            else:
                val = _FEATURE_TOKENS_OUT
            results.append({"Id": q["Id"], "Timestamps": [_NOW], "Values": [val]})
        return {"MetricDataResults": results}


@pytest.fixture
def multidim_cw(monkeypatch):
    fake = _MultiDimCW()
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: fake if s == "cloudwatch" else _FakeSSM())
    return fake


def test_a_lambda_emitting_several_dimension_sets_yields_exactly_one_row(multidim_cw):
    """COST-04. site-api-ai publishes three dimension sets; the receipt asks for the bare
    one, so three rows were three copies of one answer and a reader summing the column
    triple-counted the ask endpoints."""
    body = _payload(sad.handle_inference_receipt())
    names = [f["lambda"] for f in body["features"]]
    assert names.count(_DUP_FN) == 1, f"one row per Lambda, got {names}"
    assert sorted(names) == sorted([_DUP_FN, _SOLO_FN])


def test_the_duplicate_rows_are_not_merely_deduped_after_being_queried(multidim_cw):
    """The fix is at DISCOVERY, not at render: querying the same bare series three times
    and then collapsing the rows would leave the round-trip cost the issue's fix removed.
    2 features x 3 metrics = 6 queries, not 4 x 3 = 12."""
    _payload(sad.handle_inference_receipt())
    assert multidim_cw.query_counts == [6], f"duplicate dimension sets must not become queries: {multidim_cw.query_counts}"


def test_per_feature_dollars_are_published_from_the_chokepoint_series(multidim_cw):
    """COST-03. The dollars exist and always did — publish them. The x1.15 governor
    buffer is applied for the same reason #1997 applies it to every model row: one scale
    for every dollar figure this endpoint shows, or the two columns cannot be compared."""
    body = _payload(sad.handle_inference_receipt())
    row = next(f for f in body["features"] if f["lambda"] == _SOLO_FN)
    assert row["month_est_cost_usd"] == round(_FEATURE_COST * sad._budget._AI_SAFETY_BUFFER, 4)
    assert body["attribution"]["features_est_cost_usd"] == round(2 * _FEATURE_COST * sad._budget._AI_SAFETY_BUFFER, 2)


def test_an_unmetered_feature_publishes_null_not_zero(monkeypatch):
    """Absence read as success is the failure this platform keeps re-finding. A feature
    with tokens but NO cost datapoints was not free — it was not metered."""
    fake = _MultiDimCW(cost_for=(_SOLO_FN,))
    monkeypatch.setattr(sad.boto3, "client", lambda s, **k: fake if s == "cloudwatch" else _FakeSSM())
    body = _payload(sad.handle_inference_receipt())
    row = next(f for f in body["features"] if f["lambda"] == _DUP_FN)
    assert row["month_est_cost_usd"] is None, "an unmetered feature must not render as $0.00"
    assert body["attribution"]["unpriced_features"] == 1


def test_attribution_block_states_the_limit_that_is_real(multidim_cw):
    """The withholding reason is replaced by the honest one, and the reconciliation it
    cites is PUBLISHED rather than asserted (ADR-105) — a reader can check the ratio."""
    a = _payload(sad.handle_inference_receipt())["attribution"]
    assert "self-metered" in a["note"]
    assert a["drift_bar"] == sad._budget._DRIFT_RATIO_BAR
    assert a["reconciliation_ratio"] is not None
    # The negative control for the whole issue: the reason that was never true must be
    # gone, in every wording it appeared in.
    assert "model dimension" not in a["note"]
    assert "model mix" not in a["note"]

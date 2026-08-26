"""tests/test_freshness_checker_handler_wiring.py — handler-level wiring proof
for `lambdas/emails/freshness_checker_lambda.py` (#2799 acceptance audit,
residual `instrument-self-noop`).

Before this file, nothing drove `lambda_handler` itself: `grep -rn
"freshness_checker_lambda.lambda_handler" tests/` returned zero hits, and the
one test that touches the neighbouring `_sick_suppress` name
(`tests/test_engagement_core.py`) exercises `compute_presence()` — a different
engine entirely, not this handler's wiring. The checker is the instrument that
is supposed to catch every OTHER silent failure on the platform; per the
epic's own thesis ("nothing user- or data-facing may fail dark") an instrument
with no can-it-fail proof on its own wiring is exactly the gap the epic exists
to close.

Fixture-must-be-the-wire (per repo convention): this drives the real
`lambda_handler(event, context)` entrypoint with hand-written AWS doubles
swapped in for the module's `dynamodb` / `sns` / `cw` globals and the
in-handler `boto3.client("secretsmanager", ...)` call — never a helper
function in isolation. `health.sick_day_checker.get_sick_days_range` runs for
real against the fake table, so the `_sick_suppress` derivation (lines
~549-568) is exercised exactly as production wires it, not re-implemented in
the test.

Two paired handler tests prove BOTH directions of the `_sick_suppress` branch
are reachable and observably different (a single always-green wiring test
would not be a can-it-fail proof): with a sick day logged, the stale-source
SNS alert is suppressed; without one, an identical stale condition sends it.
"""

import os
import sys
from datetime import timedelta

from common.pacific_time import pacific_now  # #2817: the handler derives sick-day windows in the Pacific frame

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from emails import freshness_checker_lambda as fc  # noqa: E402

UID = fc.USER_ID


# ══════════════════════════════════════════════════════════════════════════
# HAND-WRITTEN AWS DOUBLES — no MagicMock (a non-terminating mock has OOM'd
# this repo's CI runner before, per tests/test_anomaly_detector_lambda.py).
# ══════════════════════════════════════════════════════════════════════════


class FakeTable:
    """In-memory DynamoDB Table double covering every query shape
    freshness_checker_lambda.py actually issues: pk equality + begins_with(sk),
    pk equality + sk BETWEEN, and plain get_item/put_item."""

    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.queries = []
        self.gets = []
        self.puts = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        expr = kwargs.get("KeyConditionExpression", "")
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk = vals.get(":pk")
        items = [r for r in self.rows if r.get("pk") == pk]
        if "begins_with" in expr:
            pfx_key = next((k for k in vals if k != ":pk"), None)
            if pfx_key:
                pfx = vals[pfx_key]
                items = [r for r in items if str(r.get("sk", "")).startswith(pfx)]
        elif "BETWEEN" in expr:
            bounds = sorted(v for k, v in vals.items() if k != ":pk")
            if len(bounds) >= 2:
                lo, hi = bounds[0], bounds[-1]
                items = [r for r in items if lo <= str(r.get("sk", "")) <= hi]
        fexpr = kwargs.get("FilterExpression")
        if fexpr:
            fields = [seg.replace("attribute_exists(", "").replace(")", "").strip() for seg in fexpr.split(" OR ")]
            items = [r for r in items if any(r.get(f) is not None for f in fields)]
        items = sorted(items, key=lambda r: str(r.get("sk", "")), reverse=bool(kwargs.get("ScanIndexForward") is False))
        limit = kwargs.get("Limit")
        if limit:
            items = items[:limit]
        proj = kwargs.get("ProjectionExpression")
        if proj:
            fields = [f.strip() for f in proj.split(",")]
            items = [{f: r[f] for f in fields if f in r} | {"sk": r["sk"]} for r in items]
        return {"Items": items, "LastEvaluatedKey": None}

    def get_item(self, Key, **kwargs):
        self.gets.append(Key)
        for r in self.rows:
            if r.get("pk") == Key.get("pk") and r.get("sk") == Key.get("sk"):
                proj = kwargs.get("ProjectionExpression")
                if proj:
                    fields = [f.strip() for f in proj.split(",")]
                    return {"Item": {f: r[f] for f in fields if f in r}}
                return {"Item": dict(r)}
        return {}

    def put_item(self, Item):
        self.puts.append(dict(Item))
        self.rows = [r for r in self.rows if not (r.get("pk") == Item.get("pk") and r.get("sk") == Item.get("sk"))]
        self.rows.append(dict(Item))


class FakeDynamoDBResource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):  # noqa: N802 — mirrors the boto3 resource API
        return self._table


class FakeSNS:
    def __init__(self):
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)


class FakeCW:
    def __init__(self):
        self.metrics = []

    def put_metric_data(self, **kwargs):
        self.metrics.append(kwargs)


class FakeSecretsManager:
    """describe_secret always 'fails' (secret unknown) — the module's own
    try/except around each lookup treats that as non-fatal, so this proves
    the wiring survives a secrets-manager outage without faking success."""

    def describe_secret(self, SecretId):  # noqa: N803 — mirrors boto3's param casing
        raise RuntimeError(f"no such secret in test double: {SecretId}")


def _install(monkeypatch, table, sns=None, cw=None):
    sns = sns or FakeSNS()
    cw = cw or FakeCW()
    monkeypatch.setattr(fc, "dynamodb", FakeDynamoDBResource(table))
    monkeypatch.setattr(fc, "sns", sns)
    monkeypatch.setattr(fc, "cw", cw)

    def _fake_boto_client(service_name, **kwargs):
        if service_name == "secretsmanager":
            return FakeSecretsManager()
        raise AssertionError(f"unexpected boto3.client({service_name!r}) from the handler")

    monkeypatch.setattr(fc.boto3, "client", _fake_boto_client)
    # Keep the handler's per-run work scoped to one deterministic source so
    # the test is about the WIRING, not the full live registry.
    monkeypatch.setattr(fc, "SOURCES", {"whoop": "Whoop"})
    monkeypatch.setattr(fc, "SOURCE_STALE_HOURS", {})
    monkeypatch.setattr(fc, "BEHAVIORAL_SOURCES", set())
    monkeypatch.setattr(fc, "DAILY_SOURCES", set())
    monkeypatch.setattr(fc, "FIELD_COMPLETENESS_CHECKS", {})
    return sns, cw


def _sick_row(day):
    return {"pk": f"USER#{UID}#SOURCE#sick_days", "sk": f"DATE#{day.isoformat()}", "date": day.isoformat()}


# ══════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════


def test_handler_runs_end_to_end_and_reports_stale_source(monkeypatch):
    """Baseline can-it-fail proof: an empty `whoop` partition through the REAL
    handler is reported stale and triggers an SNS publish — the wiring this
    epic exists to guarantee actually does something when a source goes dark."""
    table = FakeTable(rows=[])  # no whoop data at all -> "No data found"
    sns, cw = _install(monkeypatch, table)

    body = fc.lambda_handler({}, None)

    assert body["statusCode"] == 200
    assert body["stale_count"] == 1
    assert body["stale_sources"] == ["Whoop"]
    stale_publishes = [p for p in sns.published if "stale source" in p.get("Subject", "")]
    assert len(stale_publishes) == 1, f"expected exactly one stale-source SNS publish, got {sns.published}"
    assert "Whoop" in stale_publishes[0]["Message"]
    # SLO metrics really reached CloudWatch (not just computed and dropped).
    slo_calls = [m for m in cw.metrics if m.get("Namespace") == "LifePlatform/Freshness"]
    assert any(any(d["MetricName"] == "StaleSourceCount" and d["Value"] == 1 for d in m["MetricData"]) for m in slo_calls)


def test_handler_sick_suppress_silences_the_stale_alert(monkeypatch):
    """The other half of the same proof: an IDENTICAL stale condition, but with
    a sick day logged inside the SICK_SUPPRESS_DAYS lookback window, must NOT
    publish the stale-source alert — while the underlying staleness is still
    honestly reported in the return body (suppression is about paging, not
    about pretending the data is fresh)."""
    # #2817: plant the sick row in the HANDLER'S OWN day frame — a UTC 'yesterday'
    # lands outside the Pacific lookback window between 17:00 and 24:00 PT
    yesterday = (pacific_now() - timedelta(days=1)).date()
    table = FakeTable(rows=[_sick_row(yesterday)])
    sns, _cw = _install(monkeypatch, table)

    body = fc.lambda_handler({}, None)

    assert body["stale_count"] == 1
    assert body["stale_sources"] == ["Whoop"]
    stale_publishes = [p for p in sns.published if "stale source" in p.get("Subject", "")]
    assert stale_publishes == [], f"sick-day suppression did not hold: {sns.published}"


def test_handler_survives_a_secretsmanager_outage(monkeypatch):
    """The OAuth/manual-rotation secret sweep (lines ~870-952) creates its own
    boto3 client and calls describe_secret per secret; FakeSecretsManager
    always raises. The handler must still return 200 — this is the "own
    instrument doesn't page itself" proof for that block."""
    table = FakeTable(rows=[{"pk": f"USER#{UID}#SOURCE#whoop", "sk": "DATE#2026-01-01", "hrv": 55}])
    _install(monkeypatch, table)

    body = fc.lambda_handler({}, None)

    assert body["statusCode"] == 200

"""#4628 box 2 — the five additive Apple Health day fields are the sum over unique reading
timestamps of everything delivered for that day; no cross-source max, no GREATEST.

The fixture is the wire: every Health Auto Export delivery archived for the UTC day
2026-10-14 that carried one of the five fields (26 deliveries, trimmed to those
readings — see the fixture's own `_provenance`), replayed through the real webhook
handler against an in-memory S3 + a DynamoDB double that APPLIES each update_item, so
the asserted number is what the row holds after the last delivery. That day's stored
row read 11525.99 steps — exactly its largest single delivery — while the phone
delivered 13230 unique-timestamp steps; and the phone re-sent readings across
deliveries that day (a naive sum is 18309), so the dedup is exercised by real data.
"""

import json
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (
    health_auto_export_additive as additive,  # noqa: E402
    health_auto_export_lambda as hae,  # noqa: E402
)
from ingestion.source_registry import raw_date_key  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "hae_additive_day_2026-10-14.json")
DAY = "2026-10-14"
_BEARER = "test-bearer-4628"


class _NoSuchKey(Exception):
    pass


class _S3Exceptions:
    NoSuchKey = _NoSuchKey


class FakeS3:
    exceptions = _S3Exceptions()

    def __init__(self, get_error=None):
        self.objects = {}
        self.get_error = get_error

    def get_object(self, Bucket=None, Key=None, **_):
        if self.get_error is not None and "additive_readings" in Key:
            raise self.get_error
        if Key not in self.objects:
            raise _NoSuchKey(Key)
        body = self.objects[Key]

        class _B:
            def read(self_inner):
                return body.encode("utf-8")

        return {"Body": _B()}

    def put_object(self, Bucket=None, Key=None, Body=None, **_):
        self.objects[Key] = Body
        return {}


class ApplyingTable:
    """A DynamoDB double that applies `SET #a = :v` / `if_not_exists` clauses, so a replay of
    many deliveries leaves the row exactly as the real merges would."""

    def __init__(self, stored=None):
        self.item = dict(stored or {})

    def get_item(self, Key=None, ProjectionExpression=None, ExpressionAttributeNames=None, **_):
        names = ExpressionAttributeNames or {}
        wanted = [names.get(p.strip(), p.strip()) for p in (ProjectionExpression or "").split(",") if p.strip()]
        item = {k: v for k, v in self.item.items() if not wanted or k in wanted}
        return {"Item": item} if item else {}

    def update_item(self, UpdateExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_):
        for name_ph, guarded, plain in re.findall(
            r"(#[A-Za-z0-9]+) = (?:if_not_exists\(#[A-Za-z0-9]+, (:[A-Za-z0-9]+)\)|(:[A-Za-z0-9]+))", UpdateExpression
        ):
            name = ExpressionAttributeNames[name_ph]
            if guarded and name in self.item:
                continue
            self.item[name] = ExpressionAttributeValues[guarded or plain]
        return {}


def _deliveries():
    with open(FIXTURE) as fh:
        return json.load(fh)["deliveries"]


def _delivered_unique_sum():
    """The independent expectation: per field, the sum over unique reading timestamps of every
    reading delivered for DAY, computed straight from the fixture (not through the writer)."""
    by_field = {}
    for d in _deliveries():
        for m in d["payload"]["data"]["metrics"]:
            field = hae.METRIC_MAP[m["name"]]["field"]
            for r in m["data"]:
                by_field.setdefault(field, {}).setdefault(r["date"], r["qty"])
    return {f: round(sum(tsq.values()), 2) for f, tsq in by_field.items()}


@pytest.fixture
def wired(monkeypatch):
    def _wire(stored=None, get_error=None):
        s3, table = FakeS3(get_error=get_error), ApplyingTable(stored)
        monkeypatch.setattr(hae, "s3_client", s3)
        monkeypatch.setattr(hae, "table", table)
        monkeypatch.setattr(hae, "get_api_key", lambda: _BEARER)
        return s3, table

    return _wire


def _replay(deliveries):
    for d in deliveries:
        event = {"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(d["payload"])}
        assert hae.lambda_handler(event, None)["statusCode"] == 200


def test_replayed_day_stores_the_sum_over_unique_reading_timestamps(wired):
    """Box 2: after every archived delivery of the day, stored ÷ delivered is 1.00 for all five
    fields — including a re-sent reading counting once (a second full replay changes nothing)
    and a stored value above the sum being replaced (no GREATEST), and the archive object the value is summed from sits at the registry-resolved key.
    """
    # steps: the live row's pre-fix value (the largest single sync, BELOW delivered); basal: a value
    # ABOVE delivered, which a GREATEST-on-write would keep — the archived sum must replace both.
    s3, table = wired(stored={"steps": 11525.99, "basal_calories": 2000.0})
    expected = _delivered_unique_sum()
    assert set(expected) == set(additive.ADDITIVE_SUM_FIELDS), "the fixture must carry all five additive fields"

    naive_steps = sum(
        r["qty"] for d in _deliveries() for m in d["payload"]["data"]["metrics"] if m["name"] == "step_count" for r in m["data"]
    )
    assert naive_steps - expected["steps"] > 1000, "the fixture lost its real re-sent readings — the dedup is no longer exercised"

    _replay(_deliveries())
    _replay(_deliveries())  # the whole day re-sent: every reading already archived

    offenders = {}
    for field, want in expected.items():
        got = float(table.item[field])
        if abs(got / want - 1.0) > 1e-6:
            offenders[field] = (got, want)
    assert not offenders, f"stored ≠ delivered (stored, delivered unique-timestamp sum): {offenders}"
    assert float(table.item["steps"]) > 11525.99, "the stored value must no longer be the largest single sync"
    assert table.item[additive.PROVENANCE_FIELD] is True
    archived = json.loads(s3.objects[raw_date_key("apple_health", DAY, sub="additive_steps")])
    assert sum(len(tsq) for tsq in archived["readings"].values()) == 185


def test_one_delivery_day_is_unchanged_from_the_legacy_value(wired):
    """A day the phone delivers in one sync stores exactly what the old max-of-source write
    stored — the fix changes multi-delivery days only."""
    _, table = wired()
    first = _deliveries()[0]
    legacy, _, _ = hae.process_generic_metrics(first["payload"]["data"]["metrics"])
    _replay([first])
    for field, value in legacy[DAY].items():
        if field in additive.ADDITIVE_SUM_FIELDS:
            assert float(table.item[field]) == pytest.approx(value, abs=1e-6), field


def test_unreadable_archive_falls_back_to_the_guarded_legacy_write(wired):
    """Fail-safe: when the archive cannot be read (the pre-IAM-grant state, or an S3 blip) the
    delivery keeps today's GREATEST-guarded path — a stored day is never lowered — and the row
    is not stamped as a delivered-readings sum."""
    s3, table = wired(stored={"steps": 11525.99}, get_error=RuntimeError("AccessDenied"))
    _replay(_deliveries()[:3])
    assert float(table.item["steps"]) == pytest.approx(11525.99)
    assert additive.PROVENANCE_FIELD not in table.item
    assert not [k for k in s3.objects if "additive_readings" in k]

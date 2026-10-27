"""#5440 — two concurrent HAE deliveries must not overwrite each other's readings in the additive archive.

The wire (2026-10-26 04:59:19Z, UTC day 2026-10-26): the phone POSTed two payloads 57 ms apart; both
read the day's `additive_distance_walk_run_miles` object before either wrote, and the unconditional PUT
let the later one drop the other's nine minutes. The writer now compare-and-swaps on the object's ETag
(If-Match / If-None-Match) and re-reads and re-merges when it loses. The quantities below are synthetic;
the shape (source tag, offset timestamps, units) is the live one.
"""

import hashlib
import json
import os
import sys

import pytest
from botocore.exceptions import ClientError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.dirname(__file__)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (  # noqa: E402
    health_auto_export_additive as additive,
    health_auto_export_lambda as hae,
)
from ingestion.source_registry import raw_date_key  # noqa: E402
from operational import hae_additive_integrity_qa as integ  # noqa: E402

DAY = "2026-10-26"
FIELD = "distance_walk_run_miles"
SRC = "Matthew’s Apple Watch|Matt 17"
KEY = raw_date_key("apple_health", DAY, sub=f"additive_{FIELD}")


class _NoSuchKey(Exception):
    pass


class _S3Exceptions:
    NoSuchKey = _NoSuchKey


def _conflict(code="PreconditionFailed"):
    return ClientError({"Error": {"Code": code, "Message": "At least one of the pre-conditions you specified did not hold"}}, "PutObject")


class EtagS3:
    """An S3 double with real conditional-write semantics: ETag = sha256(body), If-Match must equal the
    stored ETag, If-None-Match `*` must find no object. `before_put` runs once, at the first PUT, to
    interleave another delivery between this one's read and its write."""

    exceptions = _S3Exceptions()

    def __init__(self, before_put=None, put_error=None):
        self.objects, self.puts, self.before_put, self.put_error = {}, 0, before_put, put_error

    @staticmethod
    def _etag(body):
        return '"' + hashlib.sha256(body.encode("utf-8")).hexdigest() + '"'

    def get_object(self, Bucket=None, Key=None, **_):
        if Key not in self.objects:
            raise _NoSuchKey(Key)
        body = self.objects[Key]

        class _B:
            def read(self_inner):
                return body.encode("utf-8")

        return {"Body": _B(), "ETag": self._etag(body)}

    def put_object(self, Bucket=None, Key=None, Body=None, IfMatch=None, IfNoneMatch=None, **_):
        if self.before_put is not None:
            hook, self.before_put = self.before_put, None
            hook()
        if self.put_error is not None:
            raise self.put_error
        if IfNoneMatch == "*" and Key in self.objects:
            raise _conflict()
        if IfMatch is not None and (Key not in self.objects or self._etag(self.objects[Key]) != IfMatch):
            raise _conflict()
        self.puts += 1
        self.objects[Key] = Body
        return {}


def _metrics(minutes, qty=0.01):
    """A delivery's metrics list: walking/running distance for the given UTC minutes of DAY, phone-style offset stamps."""
    data = [{"date": f"{DAY} {m // 60:02d}:{m % 60:02d}:00 +0000", "qty": qty, "units": "mi", "source": SRC} for m in minutes]
    return [{"name": "walking_running_distance", "units": "mi", "data": data}]


def _deliver(s3, minutes, qty=0.01):
    daily = {}
    return additive.apply_archived_sums(daily, _metrics(minutes, qty), hae.METRIC_MAP, hae.parse_date_str, s3, "bucket", None), daily


def _stored_readings(s3):
    return json.loads(s3.objects[KEY])["readings"][SRC]


def test_a_delivery_that_lost_the_race_remerges_onto_the_winners_object():
    s3 = EtagS3()
    minutes_a, minutes_b = list(range(0, 9)), list(range(100, 109))
    results = {}

    def other_delivery_lands_first():
        results["b"] = _deliver(s3, minutes_b)

    s3.before_put = other_delivery_lands_first
    archived, daily = _deliver(s3, minutes_a)

    assert len(_stored_readings(s3)) == 18, "both deliveries' readings must be in the object"
    assert archived == {DAY: {FIELD}}
    assert daily[DAY][FIELD] == pytest.approx(0.18), "the day value is the sum of the merged object, not the one delivery"
    assert s3.puts == 2  # B's write, then A's retry — A's first PUT was refused


def test_the_object_is_created_with_if_none_match_so_two_first_deliveries_cannot_clobber():
    s3 = EtagS3()

    def other_first_delivery():
        _deliver(s3, list(range(100, 109)))

    s3.before_put = other_first_delivery
    _, daily = _deliver(s3, list(range(0, 9)))
    assert len(_stored_readings(s3)) == 18
    assert daily[DAY][FIELD] == pytest.approx(0.18)


def test_a_redelivered_batch_after_a_conflict_still_counts_once():
    s3 = EtagS3()
    s3.before_put = lambda: _deliver(s3, list(range(0, 9)))  # the same minutes land first
    _, daily = _deliver(s3, list(range(0, 9)))
    assert len(_stored_readings(s3)) == 9
    assert daily[DAY][FIELD] == pytest.approx(0.09)


def test_a_qa_check_sees_no_shortfall_after_an_interleaved_pair():
    """The fix as the integrity check reads it: the archived sum equals the delivered readings of both payloads."""
    s3 = EtagS3()
    a, b = list(range(0, 9)), list(range(100, 109))
    s3.before_put = lambda: _deliver(s3, b)
    _, daily = _deliver(s3, a)
    payloads = [{"data": {"metrics": _metrics(a)}}, {"data": {"metrics": _metrics(b)}}]
    delivered = integ.delivered_day_values(payloads, [DAY])
    counts = integ.shortfall_counts(delivered, {(DAY, FIELD): daily[DAY][FIELD]})
    assert counts["checked"] == 1 and counts["short"] == 0


def test_a_persistent_conflict_falls_back_to_the_guarded_legacy_write_not_a_silent_overwrite():
    s3 = EtagS3(put_error=_conflict("ConditionalRequestConflict"))
    archived, daily = _deliver(s3, list(range(0, 9)))
    assert KEY not in s3.objects, "no unconditional overwrite after the retries are spent"
    assert archived == {} and FIELD not in daily.get(DAY, {}), "the caller keeps the legacy payload value under the GREATEST guard"


def test_a_non_conflict_write_failure_still_degrades_to_the_legacy_path():
    s3 = EtagS3(put_error=ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"))
    archived, _ = _deliver(s3, list(range(0, 9)))
    assert archived == {}
    assert s3.puts == 0

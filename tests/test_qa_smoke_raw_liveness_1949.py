"""tests/test_qa_smoke_raw_liveness_1949.py — #1949 raw_layout facet liveness.

operational/raw_archive_qa.check_raw_archive_liveness() is the runtime half of
the #1949 guard: the parity test (tests/test_raw_archive_role_parity.py) pins
repo config to repo grants, this check pins the DEPLOYED reality — if a source's
DDB partition is fresh (the writer demonstrably ran) but the newest object under
its raw_layout prefix is older than the liveness window, the facet's "ACTUAL"
claim is false and the check goes RED. Weather sat in exactly that state for
~5 months: DDB DATE#2026-08-01 fresh, raw/weather frozen at
2026/03/2026-03-09.json.

Driven with plain fakes through the module's DI surface (qa_smoke_lambda owns
the real AWS clients); dates are computed relative to now (no wall-clock time
bombs). The last test asserts the nightly wiring in qa_smoke_lambda itself.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import ingestion.source_registry as sr  # noqa: E402
from operational import raw_archive_qa  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402


class _FakeTable:
    def __init__(self, newest_date):
        self.newest_date = newest_date

    def query(self, **kwargs):
        if self.newest_date is None:
            return {"Items": []}
        return {"Items": [{"sk": f"DATE#{self.newest_date}"}]}


class _FakeS3:
    def __init__(self, newest_modified=None, fail=None, truncate_forever=False):
        self.newest_modified = newest_modified
        self.fail = fail
        self.truncate_forever = truncate_forever
        self.list_prefixes = []

    def list_objects_v2(self, Bucket=None, Prefix=None, **kwargs):
        if self.fail:
            raise Exception("An error occurred (AccessDenied) when calling the ListObjectsV2 operation")
        self.list_prefixes.append(Prefix)
        contents = [] if self.newest_modified is None else [{"Key": Prefix + "x.json", "LastModified": self.newest_modified}]
        resp = {"Contents": contents}
        if self.truncate_forever:
            resp["IsTruncated"] = True
            resp["NextContinuationToken"] = "tok"
        return resp


def _run(monkeypatch, layouts, table, s3):
    monkeypatch.setattr(sr, "raw_layouts", lambda: layouts)
    return raw_archive_qa.check_raw_archive_liveness(table, s3, "test-bucket", Check, CONTENT_TRUTH, lambda: datetime.now(timezone.utc))


_WEATHER_LAYOUT = {"weather": {"prefix": "raw/weather", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"}}


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def test_live_writer_with_dead_archive_fails(monkeypatch):
    """The weather state: DDB wrote yesterday, raw frozen for months → RED."""
    stale = datetime.now(timezone.utc) - timedelta(days=146)
    checks = _run(monkeypatch, _WEATHER_LAYOUT, _FakeTable(_days_ago(1)), _FakeS3(newest_modified=stale))
    (c,) = checks
    assert c.passed is False, f"expected FAIL, got: passed={c.passed} msg={c.message}"
    assert "#1949" in c.message and "raw/weather" in c.message


def test_live_writer_with_no_object_at_all_fails(monkeypatch):
    checks = _run(monkeypatch, _WEATHER_LAYOUT, _FakeTable(_days_ago(0)), _FakeS3(newest_modified=None))
    (c,) = checks
    assert c.passed is False
    assert "no raw object found" in c.message


def test_live_writer_with_fresh_archive_passes(monkeypatch):
    fresh = datetime.now(timezone.utc) - timedelta(hours=20)
    s3 = _FakeS3(newest_modified=fresh)
    checks = _run(monkeypatch, _WEATHER_LAYOUT, _FakeTable(_days_ago(1)), s3)
    (c,) = checks
    assert c.passed is True and not c.paused, c.message
    # date-tree listing is month-bounded — current + previous month, never the whole tree
    assert all(p.startswith("raw/weather/2") and p.endswith("/") for p in s3.list_prefixes)
    assert len(s3.list_prefixes) == 2


def test_quiet_writer_is_not_an_archive_verdict(monkeypatch):
    """Paused source / behavioral lapse: freshness tiers own that — not this check."""
    stale = datetime.now(timezone.utc) - timedelta(days=200)
    checks = _run(monkeypatch, _WEATHER_LAYOUT, _FakeTable(_days_ago(30)), _FakeS3(newest_modified=stale))
    (c,) = checks
    assert c.passed is True and "quiet" in c.message


def test_s3_denied_degrades_to_warn_naming_the_grant(monkeypatch):
    """Fail-soft until the operational_qa_smoke S3List raw/* grant deploys."""
    checks = _run(monkeypatch, _WEATHER_LAYOUT, _FakeTable(_days_ago(1)), _FakeS3(fail=True))
    (c,) = checks
    assert c.passed is None, f"S3 AccessDenied must WARN (fail-soft), got passed={c.passed}"
    assert "grant" in c.message


def test_flat_scheme_pages_the_whole_prefix(monkeypatch):
    layouts = {"hevy": {"prefix": "raw/hevy", "scheme": "flat-uuid"}}
    fresh = datetime.now(timezone.utc) - timedelta(days=1)
    s3 = _FakeS3(newest_modified=fresh)
    checks = _run(monkeypatch, layouts, _FakeTable(_days_ago(2)), s3)
    (c,) = checks
    assert c.passed is True, c.message
    assert s3.list_prefixes == ["raw/hevy/"], "flat-uuid must list the bare prefix, not month partitions"


def test_flat_scheme_truncation_is_inconclusive_not_red(monkeypatch):
    """If the pagination bound is hit with pages unread, an old max is a WARN —
    the newest object may live in an unread page."""
    stale = datetime.now(timezone.utc) - timedelta(days=90)
    s3 = _FakeS3(newest_modified=stale, truncate_forever=True)
    layouts = {"hevy": {"prefix": "raw/hevy", "scheme": "flat-uuid"}}
    checks = _run(monkeypatch, layouts, _FakeTable(_days_ago(1)), s3)
    (c,) = checks
    assert c.passed is None and "truncated" in c.message


def test_wired_into_lambda_handler():
    """The check must actually run nightly — assert lambda_handler calls it."""
    import ast
    import inspect

    import qa_smoke_lambda as qa

    # #2307: the run list moved out of lambda_handler into check_steps(), the one
    # place a check is wired in. Assert BOTH the live list and its source.
    tree = ast.parse(inspect.getsource(qa.check_steps))
    referenced = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert "check_raw_archive_liveness" in referenced, "raw_archive_qa.check_raw_archive_liveness not wired into check_steps()"
    assert "raw_archive_liveness" in [label for label, _fn in qa.check_steps()]

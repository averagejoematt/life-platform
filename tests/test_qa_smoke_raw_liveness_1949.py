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
from datetime import date, datetime, timedelta, timezone

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


# ── #3410: the archive is judged against its writer, not the wall clock ──────────
#
# The old rule compared `days_quiet` (whole PACIFIC CALENDAR DAYS back to the newest
# DDB DATE# — a *data day*) against `age_days` (FRACTIONAL UTC age of the newest raw
# object's LastModified — a *write time*), both against the same constant 7. A day-D
# object is always written at some hour during or after D, so a source sitting at the
# edge of the live window was GUARANTEED to score "writer LIVE, archive dead" with a
# perfectly healthy archive. These tests pin the band shut.


def _at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class _FrozenClock:
    """Stands in for the module's `datetime` so `datetime.now(tz)` is pinned.

    The module imports `datetime` by name and uses it for nothing but `.now()`,
    so a shim with one method is the whole surface."""

    def __init__(self, frozen):
        self._frozen = frozen

    def now(self, tz=None):
        return self._frozen if tz is None else self._frozen.astimezone(tz)


def _run_at(monkeypatch, layouts, table, s3, now_utc, today_pt):
    """Drive the check with BOTH clocks pinned. The real function reads wall-clock
    UTC for the object age and the injected PT clock for the data day, and #3410 is
    precisely a disagreement between those two — a test that lets either float
    cannot see it."""
    monkeypatch.setattr(sr, "raw_layouts", lambda: layouts)
    monkeypatch.setattr(raw_archive_qa, "datetime", _FrozenClock(now_utc))
    # pt_now_fn returns a datetime; only its .date() is read, so noon stands in for
    # any wall-clock hour on that Pacific day.
    pt_now = datetime(today_pt.year, today_pt.month, today_pt.day, 12, 0)
    return raw_archive_qa.check_raw_archive_liveness(table, s3, "test-bucket", Check, CONTENT_TRUTH, lambda: pt_now)


_WITHINGS_LAYOUT = {"withings": {"prefix": "raw/matthew/withings/measurements", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"}}


def test_same_data_day_in_both_channels_never_fails(monkeypatch):
    """THE RECORDED LIVE STATE (#3410). qa-smoke run 2026-09-01T05:18:44Z:

        DDB newest   DATE#2026-08-24
        raw newest   raw/matthew/withings/measurements/2026/08/2026-08-24.json
                     LastModified 2026-08-24T22:05:46Z

    The same data day in both channels — the archive is exactly as current as the
    writer — and the old rule FAILED it (days_quiet=7 <= 7 "LIVE",
    age_days=7.30 > 7 "dead"), holding qa-smoke-failures in ALARM through launch day.
    """
    checks = _run_at(
        monkeypatch,
        _WITHINGS_LAYOUT,
        _FakeTable("2026-08-24"),
        _FakeS3(newest_modified=_at(2026, 8, 24, 22, 5)),
        now_utc=_at(2026, 9, 1, 5, 18),
        today_pt=date(2026, 8, 31),  # 22:18 PT on 2026-08-31
    )
    (c,) = checks
    assert c.passed is True, f"archive and writer name the same data day — must not FAIL: {c.message}"


def test_no_false_fail_anywhere_inside_the_live_window(monkeypatch):
    """The band is closed for EVERY day the writer counts as live, not just the one
    day that happened to fire. Sweeps days_quiet 0..RAW_LIVENESS_DDB_LIVE_DAYS with
    the archive perfectly in step with the writer."""
    now = _at(2026, 9, 1, 5, 18)
    today_pt = date(2026, 8, 31)
    for quiet in range(raw_archive_qa.RAW_LIVENESS_DDB_LIVE_DAYS + 1):
        data_day = today_pt - timedelta(days=quiet)
        # archived late on its own data day — the worst-case healthy write time
        written = _at(data_day.year, data_day.month, data_day.day, 23, 59)
        checks = _run_at(
            monkeypatch,
            _WITHINGS_LAYOUT,
            _FakeTable(data_day.isoformat()),
            _FakeS3(newest_modified=written),
            now_utc=now,
            today_pt=today_pt,
        )
        (c,) = checks
        assert c.passed is True, f"days_quiet={quiet}: healthy in-step archive must not FAIL — {c.message}"


def test_archive_trailing_its_writer_still_fails(monkeypatch):
    """Negative control on the boundary itself — the rule must still be able to fail.

    Same live window as the test above (the writer is quiet 7 days, LIVE), but the
    archive stopped 40 days before the writer did. Lag, not age, is what reds it."""
    checks = _run_at(
        monkeypatch,
        _WITHINGS_LAYOUT,
        _FakeTable("2026-08-24"),
        _FakeS3(newest_modified=_at(2026, 7, 15, 22, 5)),
        now_utc=_at(2026, 9, 1, 5, 18),
        today_pt=date(2026, 8, 31),
    )
    (c,) = checks
    assert c.passed is False, f"an archive 40d behind its writer must FAIL: {c.message}"
    assert "#1949" in c.message and "behind the writer" in c.message


def test_founding_weather_incident_still_reds(monkeypatch):
    """Positive control: #1949's actual state — DDB fresh, raw frozen ~5 months.
    The rule that closes the false-FAIL band must not also close this."""
    checks = _run_at(
        monkeypatch,
        _WEATHER_LAYOUT,
        _FakeTable("2026-08-01"),
        _FakeS3(newest_modified=_at(2026, 3, 9, 12, 0)),
        now_utc=_at(2026, 8, 2, 5, 18),
        today_pt=date(2026, 8, 1),
    )
    (c,) = checks
    assert c.passed is False, f"the #1949 weather state must still FAIL: {c.message}"
    assert "raw/weather" in c.message

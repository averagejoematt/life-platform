"""Bug bash 2026-08-14 — two unauthenticated public 5xx on the read API.

Both endpoints validated the SHAPE of an input and then performed arithmetic on it
outside any guard, so a request a reader could type by accident returned a 502.

  AC1  /api/vitals — `?date=` was checked against `\\d{4}-\\d{2}-\\d{2}`, which
       matches impossible calendar dates. `2026-02-30` reached an unguarded
       `strptime` (ValueError) and `0001-01-01` survived strptime only to overflow
       `_anchor_dt - timedelta(days=30)` (OverflowError). Both surfaced as 502.
       NB the pre-fix clamp `min(date, _now)` is a STRING compare, which is why an
       impossible date sorting BELOW today crashed while `9999-99-99` sorted above
       it and silently returned today's sheet flagged `time_travel: true`.

  AC2  /api/changes-since — `?ts=` wrapped only `int(ts_str)` in its try; the
       `datetime.fromtimestamp()` two lines later sat outside it, so an in-range
       integer that is out of range as an epoch (`99999999999999`) returned 502
       while the sibling input `ts=abc` correctly returned 400.

The load-bearing property in both cases: the rejection must happen BEFORE any data
access. These tests run with FAKE credentials and no network — if a guard ever
regresses to validating after the DDB read, the call will fail on credentials
instead of returning 400, and the assertion catches it either way.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from web import site_api_lambda as L  # noqa: E402


def _get(path: str, qs: dict) -> dict:
    return L.lambda_handler(
        {
            "rawPath": path,
            "requestContext": {"http": {"method": "GET", "path": path, "sourceIp": "203.0.113.9"}},
            "queryStringParameters": qs,
            "headers": {},
        },
        None,
    )


# ── AC1 ───────────────────────────────────────────────────────────────────────

# Calendar-impossible but regex-shaped. The first three sort BELOW today (the
# crashing class); the last sorts above it (the silent-wrong class).
IMPOSSIBLE_DATES = ["2026-02-30", "2026-04-31", "2026-01-32", "2026-00-01", "0001-01-01", "9999-99-99"]


@pytest.mark.parametrize("bad", IMPOSSIBLE_DATES)
def test_vitals_rejects_impossible_calendar_dates(bad):
    """An impossible date is a 400, never a 5xx and never a silent today-sheet."""
    resp = _get("/api/vitals", {"date": bad})
    assert resp["statusCode"] == 400, f"date={bad!r} returned {resp['statusCode']}, expected 400"


def test_vitals_still_accepts_a_real_date_shape(monkeypatch):
    """Non-vacuity, and a direct proof that rejection precedes data access.

    A real calendar date must get PAST the validator. With FAKE credentials the
    only way to observe that is that it goes on to attempt the DynamoDB read and
    dies on the token — whereas every date in IMPOSSIBLE_DATES above returns 400
    without touching AWS at all. If the guard ever over-rejected, this would
    return a 400 response instead of raising, and the test fails.

    #2876 changed how that DDB failure surfaces: `/api/vitals?date=` is one of
    the 27 routes that used to `return` straight out of `lambda_handler`, so a
    raised `ClientError` used to escape uncaught (an unhandled Lambda
    invocation — no JSON response, no #2819 Handled5xx datapoint). Now every
    route funnels through `_dispatch_route`'s single exit point, so the SAME
    error is instead a clean handled 500 — worse response, better
    observability — which is the whole point of #2876. The non-vacuity check
    moves from "did it raise" to "did it reach the DDB call and get turned
    into a handled 500", proven via the logged security-token message
    (`logger` is a configured, non-propagating instance — caplog sees
    nothing, so monkeypatch `logger.error` directly, per
    test_board_route_refuses_2719.py's established technique).
    """
    logged = []
    monkeypatch.setattr(L.logger, "error", lambda msg, *a, **k: logged.append(msg % a if a else msg))

    resp = _get("/api/vitals", {"date": "2026-08-12"})

    assert resp["statusCode"] == 500, f"expected a handled 500, got {resp['statusCode']}: {resp.get('body')}"
    assert any("security token" in m.lower() for m in logged), logged


# ── AC2 ───────────────────────────────────────────────────────────────────────

# Integers that parse fine but are not representable as an epoch.
OUT_OF_RANGE_EPOCHS = ["99999999999999", "-99999999999", "253402300800", "-62135596800", "1000000000000"]


@pytest.mark.parametrize("bad", OUT_OF_RANGE_EPOCHS)
def test_changes_since_rejects_out_of_range_epochs(bad):
    """An out-of-range epoch gets the same clean 400 that `ts=abc` already got."""
    resp = _get("/api/changes-since", {"ts": bad})
    assert resp["statusCode"] == 400, f"ts={bad!r} returned {resp['statusCode']}, expected 400"


def test_changes_since_non_numeric_still_400():
    """The pre-existing contract this fix had to match, pinned so it cannot drift."""
    assert _get("/api/changes-since", {"ts": "abc"})["statusCode"] == 400


def test_changes_since_accepts_an_in_range_epoch():
    """Non-vacuity: a representable epoch must not be rejected by the range guard."""
    resp = _get("/api/changes-since", {"ts": "1786600000"})
    assert resp["statusCode"] != 400, "an in-range epoch must not be rejected by the ts guard"

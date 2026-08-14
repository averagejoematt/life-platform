"""#2658 — /api/predictions answered 200 with a zeroed coach ledger on failure.

`handle_predictions` parsed `?limit=` with a bare `int()` inside a handler-wide
`try`, whose `except` returned `_ok({... all empty ...})`. So a malformed limit —
something a reader or a script could send by accident — produced:

    HTTP 200  {"overall": {}, "by_coach": {}, "predictions": [], ...}

against a live baseline of 84 predictions this cycle and 2,584 lifetime. Absence
was rendered as zero, which is the ADR-104 violation: a reader cannot tell "the
coaches have made no predictions" from "your request was malformed".

Two distinct defects are pinned here:

  AC1  A non-integer `limit` is a 400, not a zeroed 200. Measured live before the
       fix, the whole class returned 200-with-nothing: `abc`, `3.5`, `1e3`, `" "`,
       and empty. `int()` accepts none of them.

  AC2  A genuine downstream failure returns 5xx, not a shaped-empty 200. This is
       the load-bearing half — the malformed-input case is only the way the bug was
       discovered, and fixing the parse alone would leave every OTHER exception in
       this handler still masquerading as an empty ledger.

Also fixed and pinned: a NEGATIVE limit reached `all_predictions[:limit]`, which
slices from the tail — `limit=-5` silently dropped the five most recent calls and
still answered 200. Valid-but-out-of-range values clamp into 1..200 rather than
rejecting, matching the `max(1, min(...))` convention the five sibling `limit`
handlers in `web/` already use.

FIXTURE-vs-WIRE (docs/CONVENTIONS.md §9a): these events are synthetic, so they
prove the handler and not the edge. The contract they encode was measured against
the deployed distribution on 2026-08-14 before the fix was written:
`/api/predictions?coach_id=bogus` returns a real `400 {"error": "Invalid coach_id"}`
through CloudFront, and `/api/vitals?date=2026-02-30` returns a real 502 — so 4xx
and 5xx both reach the client on `/api/*` and are not rewritten. (Contrast the 403
path, which IS rewritten to 200 + the homepage — that is #2680, still open.) If
that ever changes, this file's status-code assertions stop describing the wire.
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
from web import (
    site_api_coach as _coach,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
)


def _get(qs: dict) -> dict:
    return L.lambda_handler(
        {
            "rawPath": "/api/predictions",
            "requestContext": {"http": {"method": "GET", "path": "/api/predictions", "sourceIp": "203.0.113.9"}},
            "queryStringParameters": qs,
            "headers": {},
        },
        None,
    )


# ── AC1: a malformed limit is rejected, not silently zeroed ───────────────────

# Every one of these returned HTTP 200 with an all-empty ledger on the live site
# on 2026-08-14. None is accepted by `int()`.
BAD_LIMITS = ["abc", "3.5", "1e3", " ", "", "0x10", "nan", "1,000", "50; DROP"]


@pytest.mark.parametrize("bad", BAD_LIMITS)
def test_malformed_limit_is_a_400_not_a_zeroed_ledger(bad):
    resp = _get({"limit": bad})
    assert resp["statusCode"] == 400, f"limit={bad!r} returned {resp['statusCode']}, expected 400"


@pytest.mark.parametrize("bad", BAD_LIMITS)
def test_malformed_limit_never_answers_200(bad):
    """The specific ADR-104 defect, asserted independently of the chosen 4xx code.

    Stated separately from the 400 assertion so that a future decision to answer
    422 (or to clamp instead of reject) cannot quietly restore the thing that
    actually harmed the reader: a success envelope over a swallowed error.
    """
    assert _get({"limit": bad})["statusCode"] != 200, f"limit={bad!r} still answers 200"


# ── AC2: a real failure is a 5xx, not a shaped-empty 200 ──────────────────────


def test_downstream_failure_returns_5xx_not_an_empty_ledger(monkeypatch):
    """The load-bearing assertion.

    Forces an exception from inside the handler's `try` (the same place a DynamoDB
    outage or a shape change would raise) and pins that the response is a 5xx. Before
    the fix this returned 200 with `{"overall": {}, "by_coach": {}, "predictions": []}`
    — a reader would have seen a coach ledger of zero, not an error.
    """

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated partition-fetch failure")

    monkeypatch.setattr(_coach, "_parallel_fetch", _boom)

    resp = _get({})
    assert resp["statusCode"] >= 500, f"a downstream failure returned {resp['statusCode']}, expected 5xx"

    body = resp.get("body") or ""
    assert '"predictions": []' not in body, "a failure must not ship an empty-ledger payload"
    assert '"overall": {}' not in body, "a failure must not ship a zeroed overall block"


def test_the_forced_failure_is_actually_reached(monkeypatch):
    """A mutation must actually mutate.

    Guards the test above against silently passing because `_parallel_fetch` was
    never called (a refactor moving the fetch, or a wrong patch target, would make
    the 5xx assertion vacuous — it would pass on the credential error instead).
    """
    called = {"n": 0}

    def _spy(*_a, **_kw):
        called["n"] += 1
        raise RuntimeError("simulated partition-fetch failure")

    monkeypatch.setattr(_coach, "_parallel_fetch", _spy)
    _get({})
    assert called["n"] == 1, "the patched _parallel_fetch was never invoked — the 5xx test proves nothing"


# ── Valid input still gets through, and clamps instead of tail-slicing ────────

# Integers. Out-of-range ones clamp into 1..200; none may be rejected. `٣` is here
# rather than in BAD_LIMITS deliberately: `int("٣") == 3`, because Python's int()
# accepts any Unicode decimal digit. Asserting it were a 400 would have pinned a
# contract the implementation does not have.
VALID_LIMITS = ["1", "50", "200", "999", "0", "-5", " 7 ", "+3", "٣"]


@pytest.mark.parametrize("good", VALID_LIMITS)
def test_integer_limits_are_not_rejected(good):
    """Non-vacuity, and proof that rejection precedes data access.

    Under FAKE credentials every partition read fails, so a value that gets PAST the
    validator now lands on the total-failure path and returns 500 — while every value
    in BAD_LIMITS returns 400 without ever attempting a read. That 400-vs-500 split is
    the assertion: it proves the validator neither over-rejects nor lets bad input
    through, and it simultaneously demonstrates the AC2 behaviour end to end.
    """
    assert _get({"limit": good})["statusCode"] == 500


# ── The total-vs-partial boundary on the per-partition catch ──────────────────
#
# `_parallel_fetch` catches each partition error individually and yields [], so a
# total outage never reached the handler-wide guard at all — it produced a fully
# zeroed scorecard at HTTP 200. These two pin the new boundary from both sides.


def test_total_partition_failure_is_a_5xx(monkeypatch):
    """Every coach partition failing is a failure, not an empty ledger."""

    def _all_fail(jobs, *, failures=None):
        keys = list(jobs)
        if failures is not None:
            failures.extend(keys)
        return {k: [] for k in keys}

    monkeypatch.setattr(_coach, "_parallel_fetch", _all_fail)
    resp = _get({})
    assert resp["statusCode"] >= 500, "a total partition outage must not render as a zeroed ledger"


def test_partial_partition_failure_still_serves(monkeypatch):
    """Guards the fix against over-correcting.

    One degraded coach out of many is real degradation but not a failed request —
    it must still serve, or a single flaky partition would take the whole scorecard
    down. Without this, `if _fetch_failures:` would have been an easy mis-write for
    `if len(_fetch_failures) == len(scan_coaches):`.
    """
    seen = {}

    def _one_fails(jobs, *, failures=None):
        keys = list(jobs)
        seen["n"] = len(keys)
        if failures is not None:
            failures.append(keys[0])
        return {k: [] for k in keys}

    monkeypatch.setattr(_coach, "_parallel_fetch", _one_fails)
    resp = _get({})
    assert seen.get("n", 0) > 1, "fixture assumes a multi-coach scan; partial vs total is untested otherwise"
    assert resp["statusCode"] == 200, "one degraded partition must not fail the whole request"


def test_sibling_coach_id_guard_still_400s():
    """The pre-existing local contract the new guard had to match, pinned so it cannot drift."""
    assert _get({"coach_id": "bogus"})["statusCode"] == 400


def test_limit_guard_runs_before_the_coach_id_guard_and_both_are_400():
    """Both malformed params together still produce one clean 400, never a 5xx."""
    assert _get({"limit": "abc", "coach_id": "bogus"})["statusCode"] == 400

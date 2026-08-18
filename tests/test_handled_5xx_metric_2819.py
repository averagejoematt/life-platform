"""#2819 — the handled-5xx detector must actually fire on a handled 500.

Defect class owned (CONVENTIONS.md §9): *a handled 5xx that leaves AWS/Lambda
`Errors` at 0 and produces no metric*. The 2026-07-19 incident
(/api/fulfillment_ritual serving handled 500s for ~4h, INCIDENT_LOG.md) is the
recurrence this gate is built to catch.

The assertions are written against the real EMF wire shape — the `_aws` block
CloudWatch actually parses — not against a helper's return value, because it is
the wire shape that decides whether a metric exists at all (fixture must be the
wire).
"""

import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from web import site_api_common as sac  # noqa: E402


def _emitted(fn, *args, **kwargs):
    """Run `fn` and return the EMF handled-5xx lines it printed."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn(*args, **kwargs)
    lines = []
    for raw in buf.getvalue().splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if obj.get("_type") == "handled_5xx":
            lines.append(obj)
    return result, lines


def test_handled_500_emits_the_metric():
    sac.set_request_route("/api/fulfillment_ritual")
    resp, emitted = _emitted(sac._error, 500, "Internal error")

    assert resp["statusCode"] == 500
    assert len(emitted) == 1, "a handled 500 must produce exactly one datapoint"

    emf = emitted[0]
    # The metric must be REAL to CloudWatch: named inside the _aws block, not
    # merely present as a JSON field. This is the exact distinction that made the
    # pre-existing `status` field undetectable.
    directives = emf["_aws"]["CloudWatchMetrics"]
    assert len(directives) == 1
    d = directives[0]
    assert d["Namespace"] == "LifePlatform/SiteAPI"
    assert {m["Name"] for m in d["Metrics"]} == {"Handled5xx"}
    assert emf["Handled5xx"] == 1
    assert emf["Route"] == "/api/fulfillment_ritual"

    # Both dimension sets: the aggregate [] is what the alarm watches, ["Route"]
    # is what tells the operator which door broke. Losing the aggregate would
    # silently require one alarm per route.
    assert ["Route"] in d["Dimensions"]
    assert [] in d["Dimensions"], "the dimensionless aggregate is what site-api-handled-5xx alarms on"


def test_a_200_does_not_emit():
    sac.set_request_route("/api/vitals")
    _, emitted = _emitted(sac._ok, {"ok": True})
    assert emitted == [], "a success path must not publish a 5xx datapoint"


def test_4xx_does_not_emit():
    # A 404 or a 405 is a client error, not an outage. If these emitted, the
    # alarm would page on ordinary bot traffic hitting dead URLs.
    sac.set_request_route("/api/nope")
    for status in (400, 401, 403, 404, 405, 429, 499):
        _, emitted = _emitted(sac._error, status, "client error")
        assert emitted == [], f"{status} must not publish a 5xx datapoint"


def test_503_emits_too():
    # 14 handlers answer 503 for a degraded upstream. Those are the same class of
    # invisible failure as a 500 and must be counted.
    sac.set_request_route("/api/labs")
    _, emitted = _emitted(sac._error, 503, "Lab data temporarily unavailable.")
    assert len(emitted) == 1
    assert emitted[0]["status"] == 503


def test_write_door_envelope_emits():
    # `_envelope` is the third response builder (#2221), used by the write doors.
    # It carries no 5xx today, but it is a 5xx-capable path and the emitter must
    # not have to be remembered again if one appears.
    sac.set_request_route("/api/vote")
    _, emitted = _emitted(sac._envelope, 500, {"error": "write failed"})
    assert len(emitted) == 1


def test_emitter_never_raises():
    # An observability emitter that can throw turns a handled 500 into an
    # unhandled one. Feed it garbage and assert it stays silent.
    for bad in (None, "not-a-number", object()):
        sac.emit_handled_5xx(bad)  # must not raise


def test_route_falls_back_when_unset():
    # `_error` is called from 29 modules; if a future entry point forgets
    # set_request_route, the datapoint must still exist — an unlabelled alarm
    # beats no alarm.
    sac.set_request_route(None)
    _, emitted = _emitted(sac._error, 500, "boom")
    assert len(emitted) == 1
    assert emitted[0]["Route"] == "unknown"

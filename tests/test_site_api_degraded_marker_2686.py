"""#2686 — a 200 returned from inside an `except` must say that it is a fallback.

An AST sweep of `lambdas/web/` finds **14 handlers that return `_ok(...)` — HTTP 200 — from
inside an `except`**. Answering 200 with a fallback payload is often the right call: a
partial page beats a broken one. What the payload could not do is carry the distinction.

    {"coaches": [], "count": 0}                    roster empty, or DynamoDB timed out?
    {"huddle": [], "team_focus": [], "tensions": []}
    {"weekly_priority": {}, "open_actions": [], "coaches": [], "predictions": []}

A reader — or a chart, or the fork-me starter slice (#2541) — cannot tell a measurement
from a failure. That is the ADR-104 violation #2658 fixed on one endpoint, and #2658's own
AC4 sibling survey is what produced this list.

WHY THIS WIDENED FROM THE FILED TRIAGE. The issue sorted the 14 into "renders zeroed counts"
(6, fix), "reports a wrong verdict" (1, fix) and "probably fine" (7, leave) — and said
explicitly that it is a triage rather than a blanket fix. The reasoning behind "leave" was
that a single nullable narrative field, or a payload that already declares its error, is
honest enough. Two things moved me past that:

  * The triage's own boundary is soft. `{"weekly_priority": null}` on a failure and on a
    genuinely quiet week are still different facts wearing the same clothes; it is only
    *less loud* than a zeroed count, not more honest.
  * The reason the issue said "not a blanket fix" is that changing status codes or payload
    SHAPES per-handler needs judgment. Stamping `_meta.degraded` does neither. It changes
    no field any client reads, so nothing has to be re-taught, and the ambiguity goes away
    everywhere at once — including at the fourteenth site the filed table missed entirely
    (`site_api_protocols.protocols`, whose `except` is a real DynamoDB→S3 failover; the
    response never said which source answered).

So the guard has NO allowlist, and that is the point: an allowlist is the thing that rots.
Every `return _ok(...)` inside an `except` in `lambdas/web/` must pass `degraded=`, derived
by AST, so the fifteenth lands red on the day it is written.

ONE PAYLOAD NEEDED MORE THAN A MARKER. `handle_voice_fidelity` fell back to
`"verdict": "insufficient_data"` — a claim ABOUT THE DATA, that there is some and there is
not enough. On a read failure nothing was measured, so nothing is known about how much
there was. It now says `"unavailable"`. The marker tells you the response is a fallback;
it cannot un-say a false sentence inside the payload.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from web.site_api_common import _ok  # noqa: E402

WEB = pathlib.Path(_REPO) / "lambdas" / "web"


def _except_ok_returns():
    """(file, function, lineno, source) for every `return _ok(...)` inside an `except`."""
    found = []
    for path in sorted(WEB.glob("*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for handler in [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]:
                for ret in [n for n in ast.walk(handler) if isinstance(n, ast.Return)]:
                    call = ret.value
                    name = getattr(getattr(call, "func", None), "id", "") or getattr(getattr(call, "func", None), "attr", "")
                    if name == "_ok":
                        found.append((path.name, fn.name, ret.lineno, ast.get_source_segment(src, call) or ""))
    return found


SITES = _except_ok_returns()


# ── the derived guard ────────────────────────────────────────────────────────


def test_the_sweep_finds_the_surface_it_is_meant_to_guard():
    """Vacuity guard. An empty sweep passes every assertion below without proving anything."""
    assert len(SITES) >= 14, f"only {len(SITES)} except-200 sites found — the AST sweep broke"
    files = {f for f, _, _, _ in SITES}
    assert "site_api_coach_profile.py" in files and "site_api_lambda.py" in files


@pytest.mark.parametrize("file,func,lineno,src", SITES, ids=[f"{f}:{fn}" for f, fn, _, _ in SITES])
def test_every_200_returned_from_an_except_declares_itself_degraded(file, func, lineno, src):
    """No allowlist, on purpose — an allowlist is the thing that rots."""
    assert "degraded=" in src, (
        f"{file}:{lineno} in {func}() returns HTTP 200 from inside an `except` without "
        f"`degraded=`. A fallback payload that does not say it is a fallback is "
        f"indistinguishable from a measurement (ADR-104, #2686):\n    {' '.join(src.split())[:160]}"
    )


def test_the_protocols_failover_the_filed_triage_missed_is_covered():
    """The 14th site: its `except` is a real DynamoDB→S3 failover serving REAL data, so it
    never looked like the zeroed-count defect — and the response still never said which
    source answered."""
    hits = [s for s in SITES if s[0] == "site_api_protocols.py"]
    assert hits, "the protocols failover fell out of the sweep"
    assert all("degraded=" in s[3] for s in hits)


# ── the marker itself ────────────────────────────────────────────────────────


def _meta(resp):
    return json.loads(resp["body"])["_meta"]


def test_a_healthy_response_carries_no_marker():
    """The marker must mean something. Present on every response, it would mean nothing."""
    assert "degraded" not in _meta(_ok({"count": 3}))


def test_a_degraded_response_names_the_failure():
    resp = _ok({"coaches": [], "count": 0}, degraded=RuntimeError("dynamodb timed out"))
    assert _meta(resp)["degraded"]["reason"] == "RuntimeError: dynamodb timed out"


def test_the_marker_lives_in_meta_and_leaves_the_payload_alone():
    """Changing no field a client already reads is what makes this safe to apply to all 14."""
    body = json.loads(_ok({"coaches": [], "count": 0}, degraded=RuntimeError("boom"))["body"])
    assert body["coaches"] == [] and body["count"] == 0
    assert set(body) == {"_meta", "coaches", "count"}


def test_the_response_is_still_a_200_with_the_same_headers():
    """The triage's premise stands: a partial page beats a broken one."""
    good, bad = _ok({"x": 1}), _ok({"x": 1}, degraded=RuntimeError("boom"))
    assert bad["statusCode"] == 200 == good["statusCode"]
    assert bad["headers"] == good["headers"]


def test_the_failure_text_is_truncated():
    """An exception string is not a public surface, and a cached CDN response is a bad
    place for a stack-shaped message."""
    reason = _meta(_ok({}, degraded=RuntimeError("x" * 5000)))["degraded"]["reason"]
    assert len(reason) <= 160


def test_a_plain_string_reason_is_accepted():
    assert _meta(_ok({}, degraded="fell back to the S3 snapshot"))["degraded"]["reason"] == "fell back to the S3 snapshot"


@pytest.mark.parametrize("falsy", [None, "", 0, False])
def test_a_falsy_degraded_is_not_a_marker(falsy):
    """`degraded=None` is the default and must stay indistinguishable from omitting it."""
    assert "degraded" not in _meta(_ok({"x": 1}, degraded=falsy))


# ── the one payload that needed more than a marker ───────────────────────────


def test_voice_fidelity_no_longer_claims_insufficient_data_on_a_failure():
    """ "insufficient_data" is a claim ABOUT the data — that there is some, and not enough.
    On a read failure nothing was measured, so nothing is known about how much there was."""
    src = (WEB / "site_api_coach_ledger.py").read_text()
    tree = ast.parse(src)
    fallback = [
        ast.get_source_segment(src, ret.value)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "handle_voice_fidelity"]
        for h in [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
        for ret in [n for n in ast.walk(h) if isinstance(n, ast.Return)]
    ]
    assert fallback, "handle_voice_fidelity's except-return vanished — recheck this guard"
    assert all('"insufficient_data"' not in (s or "") for s in fallback), fallback
    assert all('"unavailable"' in (s or "") for s in fallback), fallback

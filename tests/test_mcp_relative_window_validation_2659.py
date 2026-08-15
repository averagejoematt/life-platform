"""#2659 — a nonsensical relative window must be a caller error, not a DB exception.

Explicit `start_date`/`end_date` were validated at the tool boundary. A **derived**
window — `start` computed from a relative `days` — was not. So `days=-1` built
`start > end`, DynamoDB answered `ValidationException`, and the caller got:

    Tool 'get_cgm' failed: ClientError: An error occurred (ValidationException) ...

under `error_code: INTERNAL`, whose default suggestion is

    "Retry the request — this may be a transient error."

It is not transient. It fails identically forever, and the advice sends the caller
into a retry loop over a permanent condition.

GUARD THE SET, NOT THE INSTANCE. The issue said "six of six tools tried"; the real
surface is **16 relative-window arguments** (`days` alone is on 12 tools). So the
list below is not hand-written — it is derived from the live registry schemas, and
the fix is enforced generically from each schema's own `minimum`/`maximum` rather
than a hardcoded set of argument names. A new tool taking `days` is covered by both
halves the day it lands.

The boundary is `mcp.handler._validate_tool_args`, which runs BEFORE the tool
function and therefore before any DynamoDB call — which is what the first acceptance
box asks for.
"""

from __future__ import annotations

import os
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

from mcp.handler import _validate_tool_args  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# Argument names that express a RELATIVE window (the derived-window path). Explicit
# start_date/end_date already had validation; these are the ones that did not.
_WINDOW_ARGS = ("days", "weeks", "lookback_days", "days_back", "window_days")


def _window_arg_tools():
    """(tool_name, arg_name) for every relative-window argument in the live registry."""
    found = []
    for name, spec in sorted(TOOLS.items()):
        props = (spec.get("schema", {}).get("inputSchema", {}) or {}).get("properties", {}) or {}
        for arg in sorted(props):
            if arg in _WINDOW_ARGS:
                found.append((name, arg))
    return found


WINDOW_TOOLS = _window_arg_tools()
IDS = [f"{t}:{a}" for t, a in WINDOW_TOOLS]

_PLACEHOLDER = {"string": "x", "integer": 1, "number": 1, "boolean": True, "array": [], "object": {}}


def _args(tool: str, **overrides):
    """A schema-valid payload for `tool`, plus the overrides under test.

    Some of these tools have OTHER required arguments (`get_coach_track_record`
    needs `coach_id`), and the boundary checks required-fields first — so a bare
    `{"days": -1}` would fail on the wrong rule and prove nothing about #2659.
    """
    schema = (TOOLS[tool].get("schema", {}) or {}).get("inputSchema", {}) or {}
    props = schema.get("properties", {}) or {}
    payload = {}
    for field in schema.get("required", []) or []:
        if field in overrides:
            continue
        payload[field] = _PLACEHOLDER.get((props.get(field) or {}).get("type", "string"), "x")
    payload.update(overrides)
    return payload


def test_the_derived_set_is_non_empty_and_broader_than_the_issue_said():
    """Non-vacuity, and a standing record that the filed scope understated this.

    A registry rename that broke the derivation would otherwise silently reduce
    this file to zero cases while still reporting green.
    """
    assert WINDOW_TOOLS, "derived no relative-window args — the walk is broken, not the registry"
    assert len(WINDOW_TOOLS) >= 16, f"expected the full window surface, derived only {len(WINDOW_TOOLS)}: {IDS}"


@pytest.mark.parametrize("tool,arg", WINDOW_TOOLS, ids=IDS)
@pytest.mark.parametrize("bad", [-1, 0, -30])
def test_a_nonpositive_relative_window_is_rejected_at_the_boundary(tool, arg, bad):
    """Rejected before the tool function runs — so before any DynamoDB call."""
    err = _validate_tool_args(tool, _args(tool, **{arg: bad}))
    assert err, f"{tool}({arg}={bad}) passed validation — it would reach DynamoDB"
    assert arg in err, f"error should name the offending argument, got: {err}"


@pytest.mark.parametrize("tool,arg", WINDOW_TOOLS, ids=IDS)
@pytest.mark.parametrize("bad", [-1, 0])
def test_the_rejection_is_not_a_database_exception_and_not_called_transient(tool, arg, bad):
    """The two things the caller actually saw: raw DDB text, and retry advice.

    `_validate_tool_args` returning a message means `handle_tools_call` raises a
    ValueError before dispatch, so the INTERNAL/"may be a transient error" path is
    never reached for this input.
    """
    err = _validate_tool_args(tool, _args(tool, **{arg: bad}))
    lowered = err.lower()
    assert "validationexception" not in lowered, err
    assert "clienterror" not in lowered, err
    for retry_word in ("transient", "retry the request"):
        assert retry_word not in lowered, f"validation error carries retry language: {err}"


@pytest.mark.parametrize("tool,arg", WINDOW_TOOLS, ids=IDS)
def test_a_sensible_window_still_passes(tool, arg):
    """The other half of the contract — the guard must not reject real requests.

    Without this, 'reject everything' would satisfy every assertion above.
    """
    assert _validate_tool_args(tool, _args(tool, **{arg: 7})) is None, f"{tool}({arg}=7) was rejected"


def test_the_test_and_the_validator_agree_on_what_a_window_arg_is():
    """The floor is applied by NAME for args whose schema declares no minimum, so this
    file and `handler._RELATIVE_WINDOW_ARGS` must not drift apart — otherwise the tests
    would cover a set the validator does not actually guard."""
    from mcp.handler import _RELATIVE_WINDOW_ARGS

    assert set(_WINDOW_ARGS) == set(
        _RELATIVE_WINDOW_ARGS
    ), f"test set {sorted(_WINDOW_ARGS)} != validator set {sorted(_RELATIVE_WINDOW_ARGS)}"


def test_an_arg_with_a_declared_minimum_is_still_enforced_from_the_schema():
    """The name-based floor is a SAFETY NET, not a replacement: args that do declare
    bounds (e.g. get_workouts' `limit`) must still be enforced from the schema."""
    declared = [
        (n, a, p["minimum"])
        for n, s in TOOLS.items()
        for a, p in ((s.get("schema", {}).get("inputSchema", {}) or {}).get("properties", {}) or {}).items()
        if isinstance(p, dict) and p.get("minimum") is not None and a not in _WINDOW_ARGS
    ]
    assert declared, "no non-window arg declares a minimum — this test would prove nothing"
    for tool, arg, lo in declared:
        err = _validate_tool_args(tool, _args(tool, **{arg: lo - 1}))
        assert err and arg in err, f"{tool}({arg}={lo - 1}) below its declared minimum {lo} was not rejected: {err}"

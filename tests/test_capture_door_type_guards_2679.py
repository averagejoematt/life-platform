"""#2679 — every capture door 502'd on a non-string JSON value.

Two defects, both reachable by an anonymous first-time visitor whose client sends a
mistyped field, and both surfacing as `502 Internal Server Error` — which reads as
"the site is down", not "your request was wrong":

  AC1  A non-string FIELD value. `(body.get("x") or "").strip()` raises
       AttributeError for an int, a list, or a dict, and the exception escapes the
       handler. `{"library_id": 999}` → 502, while the clean control
       `{"library_id": "<unknown-id>"}` → 400 on the very same door.

  AC2  A non-object BODY. `json.loads` returns a str/list/int for a well-formed but
       non-object body, so `body.get` itself raises. A bare-string body `"abc"` → 502
       on every door that parses one.

The module already owned the fix: `_sanitise_text` type-guards correctly, and
`/api/experiment_suggest` — which routes through it AND checks `isinstance(body, dict)`
(#2221) — already returned a clean 400 for both classes. The other doors simply did
not call it.

GUARD THE SET, NOT THE INSTANCE. The issue named four doors; the real set is larger,
and deriving it here is what found `/api/cohort_submit` (whose `value` handling is
fully type-guarded but which still lacked the body-object check). So the door list is
NOT hand-written below — it is read out of `site_api_lambda._SIMPLE_ROUTES`, filtered
to the POST verbs. A new capture door added without the guard fails this suite the day
it lands, with no edit here.

FIXTURE-vs-WIRE (docs/CONVENTIONS.md §9a): these envelopes are synthetic. The
contract they encode was confirmed against the deployed edge on 2026-08-14 — a 400
from `/api/*` reaches the client intact through CloudFront (measured on
`/api/predictions?coach_id=bogus`), and 502s from this exact class were observed live
by the bug bash. Assertions are on the status CLASS (not-5xx) or on "the handler did
not raise", never on a specific 4xx code, so the suite does not depend on which
rejection a given door chooses.
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

import json  # noqa: E402

import pytest  # noqa: E402
from web import site_api_lambda as L  # noqa: E402


def _body_parsing_post_doors() -> list:
    """Every POST route whose handler parses a JSON body — derived, never hand-listed.

    Two derivations composed, so neither has to be maintained by hand:
      1. the POST verbs out of the live route table, and
      2. the handler names that actually contain `json.loads(event.get("body"...))`,
         found by AST over `lambdas/web/`.

    The intersection is the real subject. `/api/replicate_certify` is a POST door that
    reads NO body (#1393 — self-certification carries no payload), so a malformed body
    is simply irrelevant to it; including it would assert a contract it does not have.
    """
    import ast
    import pathlib

    parsers = set()
    for p in pathlib.Path(_REPO, "lambdas/web").glob("*.py"):
        src = p.read_text()
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                # `json.loads(event.get("body") or "{}")` — the argument is a BoolOp,
                # not a bare Call, so match the `.get("body")` anywhere beneath the
                # loads() call rather than only in its direct args.
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "loads":
                    for sub in ast.walk(node):
                        if (
                            isinstance(sub, ast.Call)
                            and getattr(sub.func, "attr", None) == "get"
                            and sub.args
                            and isinstance(sub.args[0], ast.Constant)
                            and sub.args[0].value == "body"
                        ):
                            parsers.add(fn.name)
    # Some routes point at a verb-dispatcher (`_route_predict_week`) that delegates to
    # the real handler, so resolve one level of indirection — otherwise a door with a
    # GET/POST split silently drops out of the derived set.
    delegates = {}
    for p in pathlib.Path(_REPO, "lambdas/web").glob("*.py"):
        tree = ast.parse(p.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            called = {getattr(n.func, "id", None) for n in ast.walk(fn) if isinstance(n, ast.Call)}
            delegates[fn.name] = called & parsers

    def _parses(name: str) -> bool:
        return name in parsers or bool(delegates.get(name))

    return sorted(
        path for path, (verbs, fn) in L._SIMPLE_ROUTES.items() if verbs and "POST" in verbs and _parses(getattr(fn, "__name__", ""))
    )


POST_DOORS = _body_parsing_post_doors()


def _post(path: str, raw_body: str) -> dict:
    return L.lambda_handler(
        {
            "rawPath": path,
            "requestContext": {"http": {"method": "POST", "path": path, "sourceIp": "203.0.113.9"}},
            "queryStringParameters": {},
            "headers": {"content-type": "application/json"},
            "body": raw_body,
        },
        None,
    )


def test_the_derived_door_set_is_not_empty_and_covers_the_filed_four():
    """A derived set that silently became empty would make every test below vacuous."""
    assert len(POST_DOORS) >= 8, f"only {len(POST_DOORS)} POST doors derived — the route table shape probably changed"
    for filed in ("/api/challenge_vote", "/api/experiment_vote", "/api/nudge", "/api/board_question"):
        assert filed in POST_DOORS, f"{filed} (named in #2679) is not in the derived set"


# ── AC2: a well-formed but non-object body ────────────────────────────────────

# `json.loads` accepts every one of these. None of them has `.get`.
NON_OBJECT_BODIES = ['"a-bare-string"', "[1, 2, 3]", "7", "3.5", "true", "null"]


@pytest.mark.parametrize("path", POST_DOORS)
@pytest.mark.parametrize("raw", NON_OBJECT_BODIES)
def test_non_object_body_is_never_a_5xx(path, raw):
    resp = _post(path, raw)
    assert resp["statusCode"] < 500, f"POST {path} with body {raw} returned {resp['statusCode']} — a reader's typo must not 5xx"


# ── AC1: a non-string value in a field the door reads ─────────────────────────

# (door, field) pairs taken from each handler's own documented body contract.
# The VALUES are what matters; the field names only ensure the door actually reads
# the key, so the guard is exercised rather than skipped by an early "missing field".
DOOR_FIELDS = [
    ("/api/challenge_vote", "catalog_id"),
    ("/api/challenge_follow", "catalog_id"),
    ("/api/challenge_checkin", "challenge_id"),
    ("/api/experiment_vote", "library_id"),
    ("/api/experiment_follow", "library_id"),
    ("/api/experiment_suggest", "idea"),
    ("/api/nudge", "category"),
    ("/api/submit_finding", "metric_a"),
    ("/api/board_question", "question"),
    ("/api/predict_week", "week_id"),
]

NON_STRING_VALUES = [999, [1, 2], {"nested": "object"}, True, 3.5]


@pytest.mark.parametrize("path,field", DOOR_FIELDS)
@pytest.mark.parametrize("value", NON_STRING_VALUES)
def test_non_string_field_value_does_not_raise(path, field, value):
    """The precise defect: the AttributeError escaped the handler, and THAT is the 502.

    Asserted as "must not raise" rather than "status < 500" on purpose. A correctly
    type-guarded value is allowed to go on and do real work — and under FAKE
    credentials that work legitimately fails with a 503 (e.g. `/api/experiment_vote`
    cannot load its allowlist from S3). Asserting a status class here would therefore
    fail on infrastructure, not on the bug. The next test pins the 400 properly, with
    the allowlist supplied.
    """
    try:
        resp = _post(path, json.dumps({field: value}))
    except Exception as exc:  # noqa: BLE001 — any escape is the defect
        pytest.fail(f"POST {path} with {field}={value!r} raised {type(exc).__name__}: {exc}")
    assert resp["statusCode"] != 502


# ── The clean controls the fix must not disturb ───────────────────────────────


@pytest.fixture
def _allowlist(monkeypatch):
    """Supply the experiment allowlist so the door can complete offline.

    Without this the door returns a legitimate 503 (S3 unreachable under FAKE
    credentials) and no assertion about its 400 behaviour is possible.
    """
    from web import site_api_social as _social

    monkeypatch.setattr(_social, "_valid_library_ids", lambda: frozenset({"post-dinner-walk"}))


@pytest.mark.parametrize("value", NON_STRING_VALUES)
def test_non_string_id_becomes_a_clean_400_not_a_silent_accept(_allowlist, value):
    """With the allowlist available, a non-string id is REJECTED — not coerced in.

    The failure this guards against is subtler than the 502: `_sanitise_text(999)`
    returns the string `"999"`, so a fix that merely stops the crash could let a
    numeric id through as a vote for experiment "999". It must miss the allowlist.
    """
    resp = _post("/api/experiment_vote", json.dumps({"library_id": value}))
    assert resp["statusCode"] == 400, f"library_id={value!r} returned {resp['statusCode']}"


def test_unknown_id_control_still_400s(_allowlist):
    """The pre-existing clean rejection cited in the issue, pinned so it cannot drift."""
    resp = _post("/api/experiment_vote", json.dumps({"library_id": "definitely-not-a-real-experiment-id"}))
    assert resp["statusCode"] == 400


def test_a_valid_id_is_still_accepted_past_validation(_allowlist):
    """Non-vacuity: the guards must not reject the one id that IS valid.

    It cannot reach a 200 offline (the vote write needs DynamoDB), so what is pinned
    is that it gets PAST input validation — anything but a 400.
    """
    resp = None
    try:
        resp = _post("/api/experiment_vote", json.dumps({"library_id": "post-dinner-walk"}))
    except Exception:
        return  # reached the DDB write and died on credentials — past validation, which is the point
    assert resp["statusCode"] != 400, "a valid library_id was rejected by the input guards"


def test_a_missing_required_field_still_400s():
    """An empty object is still a bad request — the guard must not turn it into a 200."""
    assert _post("/api/experiment_vote", "{}")["statusCode"] == 400


def test_malformed_json_still_400s():
    """The pre-existing parse guard is untouched."""
    assert _post("/api/experiment_vote", "{not json at all")["statusCode"] == 400


def test_sanitise_text_is_the_shared_type_guard():
    """Pins the helper's contract directly, since every door now depends on it.

    If `_sanitise_text` ever stopped returning a str for a non-str input, every door
    above would regress at once and the failures would read as ten unrelated bugs.
    """
    from web.site_api_social import _sanitise_text

    for bad in (999, [1, 2], {"a": 1}, True, None, 3.5):
        assert isinstance(_sanitise_text(bad), str), f"_sanitise_text({bad!r}) did not return a str"
    # A bool is NOT treated as a number — `True` must not become the string "True".
    assert _sanitise_text(True) == ""
    assert _sanitise_text("  <b>hi</b>  ") == "hi"
    assert _sanitise_text("x" * 900, 100) == "x" * 100

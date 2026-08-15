"""#2688 — the AI doors 500'd or 502'd on a non-string field / non-object body.

Same class as #2679, different Lambda. `site-api-ai` has its own route table, so
`tests/test_capture_door_type_guards_2679.py` — which derives its doors from
`site_api_lambda._SIMPLE_ROUTES` — cannot see these and never will.

Measured live on 2026-08-14/15, BEFORE the fix. The filed issue said all three
doors return 500; the wire says there were **two** failure modes, and the second
is worse:

    POST /api/ask        {"question": 999}  -> 500  {"error": "AI service error"}
    POST /api/ask        "bare-string"      -> 500  {"error": "AI service error"}
    POST /api/explain    "bare-string"      -> 502  Internal Server Error
    POST /api/board_ask  {"question": 999}  -> 502  Internal Server Error
    POST /api/board_ask  "bare-string"      -> 502  Internal Server Error
    POST /api/ask        {"question": "hi"} -> 400  {"error": "Question too short"}  <- clean control

The 500 is a caught exception mislabelled as a backend fault. The 502 is an
AttributeError escaping the handler entirely — `body.get(...)` sat outside the
try — which also counts against the function's Lambda error metric. A reader's
typo was indistinguishable from Bedrock being down.

GUARD THE SET, NOT THE INSTANCE. The door list is not hand-written: it is read
by AST out of `site_api_ai_lambda.lambda_handler`'s own `path == "..."` dispatch,
so a new AI door added without the guard fails here the day it lands.

VACUITY — the trap this file exists to avoid. Offline, `/api/board_ask`'s
DynamoDB rate limiter fails CLOSED (`UnrecognizedClientException` on FAKE
credentials) and returns 429 before ever parsing a body. 429 is not 5xx, so a
naive "assert not 5xx" would have passed on all three doors while testing
nothing on one of them. The limiter is therefore neutralized below, and every
malformed-body assertion checks for the guard's OWN message rather than a mere
status class — a door that answers 429/403 fails.

FIXTURE-vs-WIRE (docs/CONVENTIONS.md §9a): these envelopes are synthetic, but
the contract was confirmed against the deployed edge — the six measurements
above were taken with curl against https://averagejoematt.com. What the fixture
encodes is the Function-URL event shape; what would invalidate it is CloudFront
rewriting a 400 body, which was separately measured NOT to happen for `/api/*`.
"""

from __future__ import annotations

import ast
import os
import pathlib
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
from web import site_api_ai_lambda as A  # noqa: E402

# Bodies that are well-formed JSON but NOT an object. `json.loads` returns a
# str/list/int, and the handler's next `body.get(...)` raised AttributeError.
NON_OBJECT_BODIES = ['"bare-string"', "[1, 2]", "42", "true", "null"]

# Well-formed object, wrong TYPE on the text field.
NON_STRING_FIELD_BODIES = [
    '{"question": 999}',
    '{"question": [1, 2]}',
    '{"question": {"a": 1}}',
    '{"question": true}',
]


def _ai_doors() -> list:
    """POST paths this Lambda dispatches — derived from its own handler, not listed."""
    src = pathlib.Path(_REPO, "lambdas", "web", "site_api_ai_lambda.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
    doors = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq):
            left, right = node.left, node.comparators[0]
            if isinstance(left, ast.Name) and left.id == "path" and isinstance(right, ast.Constant):
                if isinstance(right.value, str) and right.value.startswith("/api/"):
                    doors.append(right.value)
    return sorted(set(doors))


DOORS = _ai_doors()


@pytest.fixture(autouse=True)
def _reachable(monkeypatch):
    """Make every door actually REACH its body parsing.

    Without this, board_ask's DDB limiter fails closed on FAKE credentials and
    answers 429 before parsing anything — the whole suite would go green while
    exercising one door less than it claims.
    """
    monkeypatch.setattr(A, "_RATE_LIMITER_READY", False, raising=False)
    monkeypatch.setattr(A, "_board_rate_store", {}, raising=False)
    monkeypatch.setattr(A, "_ask_rate_check", lambda *a, **k: (True, 99), raising=False)
    monkeypatch.setattr(A, "_ai_paused_response", lambda: None, raising=False)


def _event(path: str, body: str) -> dict:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": "POST"}},
        "headers": {},
        "body": body,
    }


def _invoke(path: str, body: str):
    """Return the response, or fail loudly if the handler RAISED (the 502 class)."""
    try:
        return A.lambda_handler(_event(path, body), None)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"{path} raised {type(e).__name__} on body {body!r} — this is the 502 class (#2688): {e}")


def test_the_door_set_is_non_empty_and_complete():
    """Non-vacuity: an AST walk that silently found nothing would make every
    parametrized test below vanish rather than fail."""
    assert DOORS, "derived no AI doors — the AST walk is broken, not the module"
    assert set(DOORS) == {"/api/ask", "/api/board_ask", "/api/explain"}, DOORS


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("body", NON_OBJECT_BODIES)
def test_non_object_body_is_a_clean_400(door, body):
    """A bare string / array / scalar body must be rejected BY THE GUARD.

    Asserting the guard's own message — not merely "not 5xx" — is what keeps a
    429 or 403 from passing this test for the wrong reason.
    """
    resp = _invoke(door, body)
    assert resp["statusCode"] == 400, f"{door} {body} -> {resp['statusCode']} {resp.get('body')}"
    assert "JSON object" in json.loads(resp["body"])["error"], resp["body"]


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("body", NON_STRING_FIELD_BODIES)
def test_non_string_field_never_5xx(door, body):
    """A mistyped field is a client error. It must not raise and must not 5xx."""
    resp = _invoke(door, body)
    status = resp["statusCode"]
    assert status < 500, f"{door} {body} -> {status} {resp.get('body')}"
    assert status != 429, f"{door} answered 429 — the rate limiter short-circuited the body parse, so this assertion proved nothing"


@pytest.mark.parametrize("door", DOORS)
def test_clean_control_still_reaches_the_body(door):
    """The control from the live reproduction: a well-formed body must get past
    the guard and be answered on its merits (400 from a length/enum check), never
    the guard's own 'must be a JSON object'."""
    resp = _invoke(door, '{"question": "hi", "surface": "nope"}')
    assert resp["statusCode"] == 400, f"{door} -> {resp['statusCode']} {resp.get('body')}"
    assert "JSON object" not in json.loads(resp["body"])["error"], f"{door} rejected a valid object body: {resp['body']}"

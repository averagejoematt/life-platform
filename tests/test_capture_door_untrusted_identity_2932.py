"""#2932 — the fail-closed client-IP sentinel must not collapse two readers onto ONE
idempotency identity.

#1221 box 2 made `extract_client_ip` fail CLOSED: when `CloudFront-Viewer-Address` is
absent it returns the shared sentinel `no-trusted-client-ip` instead of trusting the
forgeable `X-Forwarded-For`. Right call for the RATE LIMITER — one shared bucket is a
safe failure. Wrong call for the three capture doors, which keyed their idempotency id
on the same identity (`sha256(f"{ip_hash}:{content}")[:12]`): under the sentinel, two
DIFFERENT readers submitting the same words derived the same id, and the second
submission was silently swallowed as a "duplicate" that never reached moderation —
silent data loss, indistinguishable from a genuine retry.

One helper, two callers, OPPOSITE needs on the missing-identity branch:

  * rate limiting  → `extract_client_ip`          → fail CLOSED (one shared bucket)
  * idempotency id → `extract_idempotency_identity` → fail OPEN (per-request unique;
                     dedup off, loudly logged — a duplicate review is visible, a
                     swallowed submission is not)

The behavioral tests run the REAL wire path — Function-URL event →
`web.site_api_lambda.lambda_handler` → real routing → real handler → the real
DynamoDB-backed rate limiter against the #1438 E2E harness — with the trusted header
REMOVED and the forgeable pair (`x-forwarded-for`, `sourceIp`) still present, so they
prove the forgeable headers neither mint identities nor rescue the derivation.

The guard section is issue #2932's third acceptance box: the coupling between every
idempotency-write route and the CloudFront behaviour that forwards
`CloudFront-Viewer-Address` is enforced by something that fails the build. Both sides
are DERIVED — door handlers from their own source (any function in the
`site_api_social*.py` family that calls `extract_idempotency_identity`), routes from
`site_api_lambda.py`'s route tables, behaviours from `web_stack.py` in declaration
order — so a new door or a new behaviour is swept in automatically, and a hand-list
cannot go stale.

AST over the CDK modules, never an import: CI's Deploy-critical/Unit Tests lane does
NOT install `aws_cdk`; importing it fails at COLLECTION and aborts the job. Reads a
known, named file family via a non-recursive `.glob` — not a source-tree sweep, so no
`_PREMERGE_EXTRA_FILES` registration is needed (#2372).
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import logging
import os
import pathlib
import re
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
import test_e2e_write_paths as _e2e  # noqa: E402 — the #1438 real-wire harness
from common import client_ip  # noqa: E402

# The shared fail-closed rate-limit identity (#1221) — what every identity-less
# caller's RATE bucket keys on, and what the idempotency id must never key on.
SENTINEL_HASH = hashlib.sha256(b"no-trusted-client-ip").hexdigest()[:16]

IDEA = "Try a two-week 10pm lights-out protocol and track HRV against the baseline."
FINDING = {"metric_a": "sleep", "metric_b": "hrv", "finding": "more sleep tracks higher hrv over time"}
QUESTION = {"question": "Is the morning-daylight protocol actually moving sleep onset?"}


@pytest.fixture()
def wp(monkeypatch):
    return _e2e.Harness(monkeypatch)


def _identityless(wp, path, body, forged_ip):
    """A wire-shaped envelope with NO trusted identity.

    `CloudFront-Viewer-Address` is removed — the state a behaviour dropped from the
    origin-request policy would produce — while the forgeable pair stays, set to a
    caller-chosen value, so these tests prove forged headers cannot substitute."""
    event = _e2e.Harness.event(path, "POST", body, ip=forged_ip)
    del event["headers"]["CloudFront-Viewer-Address"]
    resp = wp.api.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"]) if resp.get("body") else {}


# ══════════════════════════════════════════════════════════════════════════════
# The defect: two identity-less readers, identical content, BOTH must persist
# ══════════════════════════════════════════════════════════════════════════════


def test_two_identityless_readers_same_suggestion_both_reach_moderation(wp):
    s1, b1 = _identityless(wp, "/api/experiment_suggest", {"idea": IDEA, "source": "reader"}, "198.51.100.1")
    s2, b2 = _identityless(wp, "/api/experiment_suggest", {"idea": IDEA, "source": "reader"}, "198.51.100.2")
    assert (s1, s2) == (200, 200)

    rows = {sk: it for (pk, sk), it in wp.table.store.items() if pk == "USER#matthew#SOURCE#experiment_suggestions"}
    assert len(rows) == 2, f"two readers' identical suggestions collapsed onto {len(rows)} moderation row(s) — the #2932 silent dedup"
    assert b1["duplicate"] is False and b2["duplicate"] is False, "a stranger's identical idea was reported as the reader's own retry"
    assert b1["id"] != b2["id"]

    # The rate-limit identity in each stored row is honestly the shared sentinel —
    # never something minted from the forgeable headers.
    for it in rows.values():
        assert "198.51.100" not in json.dumps({k: v for k, v in it.items()}, default=str)


def test_two_identityless_readers_same_finding_both_stored(wp):
    s1, b1 = _identityless(wp, "/api/submit_finding", FINDING, "198.51.100.1")
    s2, b2 = _identityless(wp, "/api/submit_finding", FINDING, "198.51.100.2")
    assert (s1, s2) == (200, 200)

    keys = [k for k in wp.s3.put_keys if k.startswith("generated/findings/")]
    assert len(set(keys)) == 2, f"two readers' identical findings landed on {len(set(keys))} S3 object(s) — the second was overwritten"
    assert b1["finding_id"] != b2["finding_id"]
    # The stored records still carry the honest fail-closed rate identity.
    for k in set(keys):
        record = json.loads(wp.s3.objects[k])
        assert record["ip_hash"] == SENTINEL_HASH


def test_two_identityless_readers_same_board_question_both_stored(wp):
    s1, b1 = _identityless(wp, "/api/board_question", QUESTION, "198.51.100.1")
    s2, b2 = _identityless(wp, "/api/board_question", QUESTION, "198.51.100.2")
    assert (s1, s2) == (200, 200)

    keys = [k for k in wp.s3.put_keys if k.startswith("generated/board_questions/")]
    assert len(set(keys)) == 2, f"two readers' identical questions landed on {len(set(keys))} S3 object(s) — the second was overwritten"
    assert b1["id"] != b2["id"]


# ══════════════════════════════════════════════════════════════════════════════
# The other caller's contract is UNCHANGED: rate limiting still fails CLOSED
# ══════════════════════════════════════════════════════════════════════════════


def test_identityless_callers_still_share_one_fail_closed_rate_bucket(wp):
    """Rotating the forgeable header must NOT mint fresh buckets (#1221). Limit is
    3/h for submit_finding; four identity-less requests with four DIFFERENT forged
    X-Forwarded-For values must exhaust ONE shared budget."""
    for i in range(3):
        status, _ = _identityless(
            wp, "/api/submit_finding", {**FINDING, "finding": f"distinct finding number {i} long enough"}, f"198.51.100.{i}"
        )
        assert status == 200
    status, _ = _identityless(wp, "/api/submit_finding", {**FINDING, "finding": "a fourth distinct finding long enough"}, "198.51.100.99")
    assert status == 429, "an identity-less caller escaped the shared fail-closed bucket by rotating X-Forwarded-For"


def test_a_trusted_readers_identical_retry_still_dedupes_on_the_wire(wp):
    """The control: with the trusted header present (production today), the #2682
    idempotency contract is untouched — a retry is one row, flagged duplicate."""
    body = {"idea": IDEA, "source": "reader"}
    s1, b1 = wp.call("/api/experiment_suggest", body=body, ip=_e2e.IP_A)
    s2, b2 = wp.call("/api/experiment_suggest", body=body, ip=_e2e.IP_A)
    assert (s1, s2) == (200, 200)
    rows = [it for (pk, _sk), it in wp.table.store.items() if pk == "USER#matthew#SOURCE#experiment_suggestions"]
    assert len(rows) == 1
    assert b1["id"] == b2["id"] and b1["duplicate"] is False and b2["duplicate"] is True


def test_two_trusted_readers_same_idea_are_still_two_rows_on_the_wire(wp):
    """#2682's `test_a_different_reader_submitting_the_same_idea_is_not_deduped`,
    proven through the full lambda_handler wire path rather than a direct call."""
    body = {"idea": IDEA, "source": "reader"}
    assert wp.call("/api/experiment_suggest", body=body, ip=_e2e.IP_A)[0] == 200
    assert wp.call("/api/experiment_suggest", body=body, ip=_e2e.IP_B)[0] == 200
    rows = [it for (pk, _sk), it in wp.table.store.items() if pk == "USER#matthew#SOURCE#experiment_suggestions"]
    assert len(rows) == 2


# ══════════════════════════════════════════════════════════════════════════════
# The helper itself: trusted passthrough, untrusted uniqueness, loud failure
# ══════════════════════════════════════════════════════════════════════════════

_TRUSTED_EVENT = {
    "headers": {"cloudfront-viewer-address": "203.0.113.9:41234", "x-forwarded-for": "198.51.100.99"},
    "requestContext": {"http": {"sourceIp": "198.51.100.99"}},
}
_UNTRUSTED_EVENT = {
    "headers": {"x-forwarded-for": "198.51.100.99"},
    "requestContext": {"http": {"sourceIp": "198.51.100.99"}},
}


def test_trusted_identity_is_the_bare_viewer_address_same_as_the_rate_identity():
    """When the header arrives, the two derivations agree exactly — so every
    existing hand-derived id in the #2682 suite is byte-identical."""
    assert client_ip.extract_idempotency_identity(_TRUSTED_EVENT) == "203.0.113.9"
    assert client_ip.extract_idempotency_identity(_TRUSTED_EVENT) == client_ip.extract_client_ip(_TRUSTED_EVENT)


def test_untrusted_identity_is_unique_per_request_and_never_the_sentinel():
    a = client_ip.extract_idempotency_identity(_UNTRUSTED_EVENT)
    b = client_ip.extract_idempotency_identity(_UNTRUSTED_EVENT)
    assert a != b, "two identity-less requests derived the SAME idempotency identity — strangers collapse again"
    assert a.startswith("untrusted-client:") and b.startswith("untrusted-client:")
    assert client_ip.extract_client_ip(_UNTRUSTED_EVENT) not in (a, b)
    # The forgeable headers must not leak into the minted identity either.
    assert "198.51.100.99" not in a


def test_the_untrusted_derivation_is_loud_not_silent(caplog):
    """Acceptance box 2: the failure is observable. The minted-identity path logs a
    WARNING naming the missing header and the broken coupling."""
    with caplog.at_level(logging.WARNING, logger="common.client_ip"):
        client_ip.extract_idempotency_identity(_UNTRUSTED_EVENT)
    hits = [r for r in caplog.records if "#2932" in r.getMessage()]
    assert hits, "no warning logged — an identity-less capture-door request would degrade silently"
    assert "CloudFront-Viewer-Address" in hits[0].getMessage()


def test_the_rate_limit_helper_still_fails_closed():
    """The OTHER caller's contract, pinned next to its opposite: `extract_client_ip`
    on the same identity-less event stays the one shared sentinel."""
    assert client_ip.extract_client_ip(_UNTRUSTED_EVENT) == "no-trusted-client-ip"
    assert client_ip.extract_client_ip(_UNTRUSTED_EVENT) == client_ip.extract_client_ip(_UNTRUSTED_EVENT)


# ══════════════════════════════════════════════════════════════════════════════
# Acceptance box 3 — the derived route↔behaviour coupling guard
# ══════════════════════════════════════════════════════════════════════════════

_WEB_DIR = pathlib.Path(_REPO) / "lambdas" / "web"
_ROUTER = _WEB_DIR / "site_api_lambda.py"
_WEB_STACK = pathlib.Path(_REPO) / "cdk" / "stacks" / "web_stack.py"
_POLICIES = pathlib.Path(_REPO) / "cdk" / "stacks" / "web_cloudfront_policies.py"


def _door_handler_names() -> set:
    """Every function in the site_api_social*.py family whose identity feeds an
    idempotency id — derived from the source (it calls extract_idempotency_identity),
    never hand-listed."""
    names = set()
    for path in sorted(_WEB_DIR.glob("site_api_social*.py")):
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and "extract_idempotency_identity(" in (ast.get_source_segment(src, node) or ""):
                names.add(node.name)
    return names


def _routes_for(handler_names: set) -> set:
    """The /api routes whose handler is a capture door — read out of the router's own
    route tables (any dict literal mapping a '/api/...' string to the handler name)."""
    src = _ROUTER.read_text(encoding="utf-8")
    routes = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith("/api/")):
                continue
            if {n.id for n in ast.walk(value) if isinstance(n, ast.Name)} & handler_names:
                routes.add(key.value)
    return routes


def _behaviours(source: str) -> list:
    """(path_pattern, origin_request_policy_expr) for every CacheBehaviorProperty in
    DECLARATION order — which is CloudFront's evaluation order (most-specific first is
    a convention the table maintains by hand; the guard honours whatever is written)."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "CacheBehaviorProperty":
            pattern, orp = None, None
            for kw in node.keywords:
                if kw.arg == "path_pattern" and isinstance(kw.value, ast.Constant):
                    pattern = kw.value.value
                elif kw.arg == "origin_request_policy_id":
                    orp = ast.unparse(kw.value)
            out.append((node.lineno, pattern, orp))
    return [(pattern, orp) for _ln, pattern, orp in sorted(out)]


def _orp_violations(behaviours: list, routes: set) -> list:
    violations = []
    for route in sorted(routes):
        first_match = next(((p, orp) for p, orp in behaviours if p and fnmatch.fnmatchcase(route, p)), None)
        if first_match is None:
            violations.append(
                f"{route}: NO cache behaviour matches — the route falls to the default (S3) behaviour, "
                "where CloudFront-Viewer-Address is never forwarded and every reader is identity-less"
            )
        elif not first_match[1] or "_api_pol" not in first_match[1]:
            violations.append(
                f"{route}: served by behaviour {first_match[0]!r}, which carries no _api_pol origin-request policy — "
                "CloudFront-Viewer-Address will not reach the origin and the capture doors degrade to minted identities"
            )
    return violations


def test_the_derived_door_set_is_real():
    """Vacuity guard: the derivation must find the three known doors (a fourth is
    swept in automatically; losing one of these three means the id derivation was
    quietly reverted onto the rate-limit identity)."""
    doors = _door_handler_names()
    assert {"_handle_experiment_suggest", "_handle_submit_finding", "_handle_board_question"} <= doors, doors


def test_every_capture_door_is_routed():
    routes = _routes_for(_door_handler_names())
    assert {"/api/experiment_suggest", "/api/submit_finding", "/api/board_question"} <= routes, routes


def test_every_capture_door_route_is_served_by_a_viewer_address_behaviour():
    """The build-failing coupling: each idempotency-write route's FIRST matching
    CloudFront behaviour must carry an origin-request policy from
    web_cloudfront_policies.py (whose ORPs are all pinned to forward
    CloudFront-Viewer-Address by tests/test_cloudfront_viewer_address_policies_1221.py)."""
    behaviours = _behaviours(_WEB_STACK.read_text(encoding="utf-8"))
    assert len(behaviours) > 10, "the behaviour table shrank implausibly — did the parse target move?"
    violations = _orp_violations(behaviours, _routes_for(_door_handler_names()))
    assert not violations, "\n".join(violations)


def test_the_policy_chain_is_the_guarded_module():
    """The `_api_pol` the behaviours reference must come from build_api_policies —
    the module whose origin-request policies the #1221 guard pins to forward the
    header — and that module must still name the header in its origin allow-list."""
    stack_src = _WEB_STACK.read_text(encoding="utf-8")
    assert "_api_pol = build_api_policies(" in stack_src, "_api_pol no longer comes from web_cloudfront_policies.build_api_policies"
    policies_src = _POLICIES.read_text(encoding="utf-8")
    assert 'VIEWER_ADDRESS_HEADER = "CloudFront-Viewer-Address"' in policies_src
    assert (
        "VIEWER_ADDRESS_HEADER" in policies_src.split("_API_ORIGIN_HEADERS")[1].split(")")[0]
    ), "CloudFront-Viewer-Address left the /api origin-request header allow-list"


def test_guard_catches_a_behaviour_that_drops_the_policy():
    """Mutation proof 1 — strip every origin_request_policy_id from the behaviour
    table and the guard must fail. A gate that cannot fail is wired to nothing."""
    src = _WEB_STACK.read_text(encoding="utf-8")
    mutated = re.sub(r"origin_request_policy_id=.*", "", src)
    assert mutated != src, "mutation anchor missing — no origin_request_policy_id kwargs found to strip"
    violations = _orp_violations(_behaviours(mutated), _routes_for(_door_handler_names()))
    assert violations, "removing every origin-request policy tripped NOTHING — this guard is vacuous"


def test_guard_catches_a_route_no_behaviour_serves():
    """Mutation proof 2 — retarget the /api/* catch-all and the doors' routes fall to
    the default S3 behaviour; the guard must say so."""
    src = _WEB_STACK.read_text(encoding="utf-8")
    mutated = src.replace('path_pattern="/api/*"', 'path_pattern="/api-renamed/*"')
    assert mutated != src, "mutation anchor missing — the /api/* catch-all behaviour is gone"
    violations = _orp_violations(_behaviours(mutated), _routes_for(_door_handler_names()))
    assert any("NO cache behaviour matches" in v for v in violations), "orphaning the /api/* routes tripped NOTHING"

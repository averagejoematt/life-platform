#!/usr/bin/env python3
"""
tests/test_freshness_checker_iam_parity.py — monitored-list ⊆ IAM-grants guard.

#1330: The freshness checker's OAuth token-health check (R8-ST4) calls
`secretsmanager:DescribeSecret` on every secret in its OAUTH_SECRETS +
MANUAL_ROTATION_SECRETS lists. If a secret is monitored but the
freshness-checker role's `OAuthSecretDescribe` grant doesn't include it,
the DescribeSecret call AccessDenied's — silently, because the checker
swallows the exception — and the token-health safeguard is dead for that
secret. That already happened twice:
  - 2026-05-28: MANUAL_ROTATION_SECRETS added, grant lagged (documented in
    role_policies.py:OAuthSecretDescribe).
  - 2026-06-20 → 2026-07-25: strava RE-ENABLED in OAUTH_SECRETS, grant never
    restored → ~4 weeks of daily AccessDenied on life-platform/strava (#1330).

This test keys off the ACTUAL in-repo literals in BOTH files:
  - the monitored set: OAUTH_SECRETS + MANUAL_ROTATION_SECRETS, parsed straight
    from lambdas/emails/freshness_checker_lambda.py (they live in lambda_handler,
    so AST-extraction reads the real assignments regardless of scope);
  - the granted set: the resource ARNs of the `OAuthSecretDescribe` statement,
    read from the real construct returned by
    role_policies.operational_freshness_checker().

so it fails at PR time on any future divergence — exactly the structural guard
the incident class asked for.

Run:  python3 -m pytest tests/test_freshness_checker_iam_parity.py -v
"""

import ast
import os
import re
import sys
import types

import pytest

# #416 / ADR-117: deploy-critical lane (IAM/Secrets Manager consistency guard).
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRESHNESS_SRC = os.path.join(ROOT, "lambdas", "emails", "freshness_checker_lambda.py")
CDK_DIR = os.path.join(ROOT, "cdk")
CDK_STACKS = os.path.join(CDK_DIR, "stacks")


# ── The monitored set: parse the two literal lists from the checker source ────
def _extract_monitored_secrets() -> set:
    """AST-extract OAUTH_SECRETS + MANUAL_ROTATION_SECRETS from the checker.

    The lists are assigned inside lambda_handler(), so we walk the whole tree
    for Assign nodes targeting those names and collect their string-literal
    elements. This reads the real repo literals — no import-time side effects
    (boto3 resource creation, source_registry) required.
    """
    with open(FRESHNESS_SRC, "r") as f:
        tree = ast.parse(f.read(), filename=FRESHNESS_SRC)

    wanted = {"OAUTH_SECRETS", "MANUAL_ROTATION_SECRETS"}
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted and isinstance(node.value, (ast.List, ast.Tuple)):
                items = []
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        items.append(elt.value)
                found[target.id] = items

    missing = wanted - set(found)
    assert not missing, f"Could not find list literal(s) {missing} in {FRESHNESS_SRC}"

    monitored = set()
    for name in wanted:
        monitored.update(found[name])
    return monitored


# ── The granted set: read OAuthSecretDescribe resources from role_policies ────
def _extract_granted_secrets() -> set:
    """Import role_policies (with an aws_cdk stub, same pattern as
    tests/test_iam_secrets_consistency.py) and read the resource ARNs of the
    OAuthSecretDescribe statement on the freshness-checker role."""

    class _PolicyStatement:
        def __init__(self, sid="", actions=None, resources=None, **kwargs):
            self.sid = sid
            self.actions = list(actions or [])
            self.resources = list(resources or [])

    _iam_stub = types.ModuleType("aws_cdk.aws_iam")
    _iam_stub.PolicyStatement = _PolicyStatement
    _cdk_stub = types.ModuleType("aws_cdk")
    _cdk_stub.aws_iam = _iam_stub
    sys.modules.setdefault("aws_cdk", _cdk_stub)
    sys.modules["aws_cdk.aws_iam"] = _iam_stub

    for p in (CDK_DIR, CDK_STACKS):
        if p not in sys.path:
            sys.path.insert(0, p)

    import role_policies as rp

    stmts = rp.operational_freshness_checker()
    oauth_stmt = next((s for s in stmts if getattr(s, "sid", "") == "OAuthSecretDescribe"), None)
    assert oauth_stmt is not None, "OAuthSecretDescribe statement not found on operational_freshness_checker() role"

    arn_re = re.compile(r"arn:aws:secretsmanager:[^:]+:[^:]+:secret:([^\*\"]+)")
    granted = set()
    for resource in oauth_stmt.resources:
        m = arn_re.search(resource)
        if m:
            granted.add(m.group(1).rstrip("*").rstrip("/"))
    return granted


MONITORED = _extract_monitored_secrets()
GRANTED = _extract_granted_secrets()


def test_monitored_lists_are_nonempty():
    """Sanity: extraction actually found the literals (guards against a silently
    empty MONITORED set masking a real divergence)."""
    assert MONITORED, "OAUTH_SECRETS + MANUAL_ROTATION_SECRETS extracted empty — extraction is broken"
    assert GRANTED, "OAuthSecretDescribe resource list extracted empty — extraction is broken"
    # strava is the #1330 canary — assert it is actually present in the monitored
    # set so a future removal of strava from OAUTH_SECRETS makes this obvious.
    assert "life-platform/strava" in MONITORED, "strava expected in the monitored set (OAUTH_SECRETS) — see #1330"


def test_monitored_secrets_are_a_subset_of_iam_grants():
    """Every secret the freshness checker calls DescribeSecret on must be granted
    by the freshness-checker role's OAuthSecretDescribe statement. A monitored
    secret absent from the grant AccessDenies daily and silently — the exact
    #1330 (and 2026-05-28) incident class."""
    ungranted = sorted(MONITORED - GRANTED)
    assert not ungranted, (
        f"IAM parity FAIL: {len(ungranted)} monitored secret(s) NOT in the "
        f"OAuthSecretDescribe grant → freshness_checker will AccessDenied on them "
        f"(silently swallowed → dead token-health check):\n"
        + "\n".join(f"  {s}" for s in ungranted)
        + '\n\nFix: add _secret_arn("<name>") to the OAuthSecretDescribe resources '
        "list in cdk/stacks/role_policies.py:operational_freshness_checker() "
        "(then Matthew CDK-deploys the role). This is the #1330 / 2026-05-28 incident class."
    )

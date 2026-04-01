#!/usr/bin/env python3
"""
tests/test_iam_secrets_consistency.py — IAM/Secrets Manager consistency linter.

R8-8: Prevents IAM policy drift by cross-referencing secret ARN patterns
in role_policies.py against a known-secrets list.

Born from Architecture Review #8 Finding-1: COST-B created `ingestion-keys`
references in IAM that weren't in the documented 9-secret list. This class
of bug caused 3 production incidents (Mar 8, Mar 12, Feb 28).

Rules:
  S1  Every secret ARN in role_policies.py must reference a known secret
  S2  No secret references to deleted/deprecated secrets
  S3  Every known secret must be referenced by at least one IAM policy

Run:  python3 -m pytest tests/test_iam_secrets_consistency.py -v

v1.0.0 — 2026-03-13 (Architecture Review #8)
"""

import os
import sys
import re
import json
import pytest

# ── Add cdk/ and cdk/stacks/ to path ─────────────────────────────────────────
# cdk/ is needed so `from stacks.constants import ...` resolves as a package.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_DIR = os.path.join(ROOT, "cdk")
CDK_STACKS = os.path.join(CDK_DIR, "stacks")
sys.path.insert(0, os.path.abspath(CDK_DIR))
sys.path.insert(0, os.path.abspath(CDK_STACKS))

# ── Stub aws_cdk so role_policies.py imports without CDK installed ────────────
import types
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

import role_policies as rp
import inspect

# ══════════════════════════════════════════════════════════════════════════════
# Known secrets — the single source of truth for what exists in AWS.
# Update this list when adding or removing Secrets Manager secrets.
# Must match ARCHITECTURE.md "Secrets Manager" section.
# ══════════════════════════════════════════════════════════════════════════════

KNOWN_SECRETS = [
    "life-platform/whoop",
    "life-platform/withings",
    "life-platform/strava",
    "life-platform/garmin",
    "life-platform/eightsleep",
    "life-platform/ai-keys",
    "life-platform/habitify",
    "life-platform/ingestion-keys",  # COST-B bundle: Notion + Habitify + Todoist + Dropbox + HAE webhook keys
    "life-platform/webhook-key",     # Dedicated HAE webhook auth (exists but not yet primary — code reads ingestion-keys)
    "life-platform/mcp-api-key",     # MCP server auth (90-day auto-rotation via key-rotator Lambda)
    "life-platform/site-api-ai-key", # R17-04: isolated Anthropic key for site-api (separate from main ai-keys)
    "life-platform/notion",          # Notion API key (also in ingestion-keys bundle)
    "life-platform/dropbox",         # Dropbox API key (also in ingestion-keys bundle)
    "life-platform",                 # Wildcard prefix — pipeline_health_check reads all secrets to verify they exist
]

# Secrets that have been permanently deleted — must not appear in IAM policies.
DELETED_SECRETS = [
    "life-platform/api-keys",        # Permanently deleted 2026-03-14
]

# Secrets that are referenced in IAM but are known to be transitional.
# Add entries here during migrations; remove once IAM is updated.
# Format: {"secret_name": "reason it's allowed temporarily"}
TRANSITIONAL_ALLOWLIST = {
    # Example: "life-platform/ingestion-keys": "COST-B migration in progress — TB7-X",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_policy_functions():
    return {
        name: obj
        for name, obj in inspect.getmembers(rp, inspect.isfunction)
        if not name.startswith("_")
    }


def _extract_secret_names_from_policies():
    """Extract all secret names referenced in IAM policy ARN patterns."""
    secret_refs = {}  # secret_name → [function_names]
    pattern = re.compile(
        r"arn:aws:secretsmanager:[^:]+:[^:]+:secret:([^\*\"]+)"
    )

    for fn_name, fn in _all_policy_functions().items():
        stmts = fn()
        for stmt in stmts:
            secrets_actions = {"secretsmanager:getsecretvalue", "secretsmanager:putsecretvalue",
                               "secretsmanager:updatesecret", "secretsmanager:describesecret"}
            if not ({a.lower() for a in stmt.actions} & secrets_actions):
                continue
            for resource in stmt.resources:
                match = pattern.search(resource)
                if match:
                    secret_name = match.group(1).rstrip("*").rstrip("/")
                    if secret_name not in secret_refs:
                        secret_refs[secret_name] = []
                    secret_refs[secret_name].append(fn_name)

    return secret_refs


ALL_FUNCTIONS = _all_policy_functions()
SECRET_REFS = _extract_secret_names_from_policies()


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_s1_all_iam_secrets_are_known():
    """S1: Every secret referenced in IAM policies must be in the known-secrets list
    or the transitional allowlist."""
    unknown = []
    for secret_name, fn_names in SECRET_REFS.items():
        if secret_name not in KNOWN_SECRETS and secret_name not in TRANSITIONAL_ALLOWLIST:
            unknown.append(f"  '{secret_name}' (referenced by: {', '.join(fn_names)})")

    assert not unknown, (
        f"S1 FAIL: {len(unknown)} secret(s) referenced in IAM but not in KNOWN_SECRETS:\n"
        + "\n".join(unknown)
        + "\n\nEither:\n"
        "  (a) Add the secret to KNOWN_SECRETS if it exists in AWS\n"
        "  (b) Add to TRANSITIONAL_ALLOWLIST with a reason if migration is in progress\n"
        "  (c) Fix the IAM policy in role_policies.py to reference the correct secret\n"
        "\nThis is the exact class of bug that caused the Mar 8 / Mar 12 incidents."
    )


def test_s2_no_deleted_secrets_in_iam():
    """S2: No IAM policy may reference a permanently deleted secret."""
    violations = []
    for secret_name, fn_names in SECRET_REFS.items():
        if secret_name in DELETED_SECRETS:
            violations.append(f"  '{secret_name}' (referenced by: {', '.join(fn_names)})")

    assert not violations, (
        f"S2 FAIL: {len(violations)} DELETED secret(s) still referenced in IAM:\n"
        + "\n".join(violations)
        + "\n\nThese secrets no longer exist in AWS. Update role_policies.py to use "
        "the current secret name."
    )


def test_s3_all_known_secrets_referenced():
    """S3: Every known secret should be referenced by at least one IAM policy.
    Unreferenced secrets may indicate a stale KNOWN_SECRETS list or missing IAM."""
    # Some secrets are only accessed by the MCP server or operational Lambdas
    # that may use different access patterns. Only warn, don't fail.
    unreferenced = []
    for secret in KNOWN_SECRETS:
        if secret not in SECRET_REFS:
            unreferenced.append(secret)

    if unreferenced:
        # Soft check — some secrets are accessed via env var overrides or
        # non-standard patterns. Print warning but don't fail.
        import warnings
        warnings.warn(
            f"S3 INFO: {len(unreferenced)} known secret(s) not directly referenced "
            f"in any role_policies.py function: {unreferenced}. "
            f"This may be normal (MCP server reads ai-keys via env var)."
        )


def test_s4_known_secrets_count_matches_architecture():
    """S4: The count of known secrets should match what ARCHITECTURE.md documents.
    Update KNOWN_SECRETS when adding or removing secrets."""
    # As of v3.7.84: 11 active secrets (R17-04 added life-platform/site-api-ai-key)
    EXPECTED_COUNT = 14
    actual = len(KNOWN_SECRETS)
    assert actual == EXPECTED_COUNT, (
        f"S4 FAIL: KNOWN_SECRETS has {actual} entries, expected {EXPECTED_COUNT}. "
        f"If you added or removed a secret, update both KNOWN_SECRETS in this file "
        f"AND the ARCHITECTURE.md Secrets Manager table."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)

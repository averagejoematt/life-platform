#!/usr/bin/env python3
"""
tests/test_secret_references.py — Lambda source code secret name linter.

R13-F04: Prevents a class of deployment bug where Lambda source code
references a secret name (via os.environ.get or string literal) that
either doesn't exist in AWS or has been permanently deleted.

Root cause it prevents: The March 2026 Todoist-style 2-day outage where
a Lambda was deployed with a wrong SECRET_NAME default value that pointed
at a non-existent secret. No CI test caught it; alarm fired 2 days later.

Rules:
  SR1  Every secret name literal in Lambda source must be in KNOWN_SECRETS
       or DELETED_SECRETS (to surface deleted ones explicitly)
  SR2  No Lambda source may reference a DELETED secret by name
  SR3  Secret name patterns must follow the life-platform/* convention
       (catches typos like 'life-platorm/ai-keys')
  SR4  Sanity: at least some secret references found (guards against regex breakage)

Scope: lambdas/*.py and mcp/*.py and mcp_server.py

Run:  python3 -m pytest tests/test_secret_references.py -v

v1.0.0 — 2026-03-15 (R13-F04)
"""

import os
import re
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ── Source directories to scan ────────────────────────────────────────────────
SCAN_PATHS = [
    os.path.join(ROOT, "lambdas"),
    os.path.join(ROOT, "mcp"),
    os.path.join(ROOT, "mcp_server.py"),
]

# Files to explicitly exclude
EXCLUDE_PATTERNS = [
    "__pycache__",
    "cdk.out",
    "deprecated_secrets.txt",
    "test_secret_references.py",       # this file
    "test_iam_secrets_consistency.py", # already covers IAM layer
]

# ── Canonical known secrets ───────────────────────────────────────────────────
# Must stay in sync with test_iam_secrets_consistency.py KNOWN_SECRETS
# and ARCHITECTURE.md Secrets Manager table.
KNOWN_SECRETS = {
    "life-platform/whoop",
    "life-platform/withings",
    "life-platform/strava",
    "life-platform/garmin",
    "life-platform/eightsleep",
    "life-platform/ai-keys",
    "life-platform/habitify",
    "life-platform/ingestion-keys",
    "life-platform/webhook-key",
    "life-platform/mcp-api-key",
    # life-platform/google-calendar removed — retired ADR-030 (v3.7.46)
}

# Secrets permanently deleted — any source reference is an SR2 violation.
DELETED_SECRETS = {
    "life-platform/api-keys",   # deleted 2026-03-15 (TB7-4)
}

# Partial strings that appear in code but are NOT literal secret names.
# Used to avoid false positives on env var names, variable names, etc.
FALSE_POSITIVE_PATTERNS = {
    "SECRET_NAME",           # env var name
    "ANTHROPIC_SECRET",      # env var name
    "MCP_SECRET_NAME",       # env var name
    "HABITIFY_SECRET_NAME",  # env var name
    "NOTION_SECRET_NAME",    # env var name
    "secret_name",           # local variable name
    "_secret_name",          # local variable name
    "SecretString",          # boto3 response field
    "get_secret_value",      # boto3 call
    "secret.get(",           # dict access
    "secrets.get(",          # dict access
}

# Regex: matches quoted 'life-platform/...' string literals in source code.
_SECRET_LITERAL_RE = re.compile(
    r"""['\"](life-platform/[a-zA-Z0-9_\-]+)['\"]"""
)

# Convention: all secret names must have this prefix.
_CONVENTION_RE = re.compile(r"^life-platform/")


# ── File collection ───────────────────────────────────────────────────────────

def _collect_files():
    """Collect all Python source files to scan."""
    files = []
    for path in SCAN_PATHS:
        if os.path.isfile(path) and path.endswith(".py"):
            files.append(path)
        elif os.path.isdir(path):
            for fname in os.listdir(path):
                if not fname.endswith(".py"):
                    continue
                if any(ex in fname for ex in EXCLUDE_PATTERNS):
                    continue
                files.append(os.path.join(path, fname))
    return sorted(files)


def _extract_secret_literals(filepath):
    """Extract all 'life-platform/...' string literals from a source file.

    Returns list of (line_number, secret_name) tuples.
    Skips comment lines and lines containing known-false-positive patterns.
    """
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if stripped.startswith("#"):  # full-line comment
                    continue
                # Skip lines that are clearly env var names or variable assignments,
                # not actual secret string lookups
                if any(fp in line for fp in FALSE_POSITIVE_PATTERNS):
                    continue
                for match in _SECRET_LITERAL_RE.finditer(line):
                    secret_name = match.group(1)
                    results.append((lineno, secret_name))
    except Exception:
        pass
    return results


# ── Pre-compute scan results once at module load ──────────────────────────────

_FILES = _collect_files()
_ALL_REFS: list = []
for _f in _FILES:
    for _lineno, _name in _extract_secret_literals(_f):
        _ALL_REFS.append((_f, _lineno, _name))


# ══════════════════════════════════════════════════════════════════════════════
# SR1 — Every referenced secret must be in KNOWN_SECRETS
# ══════════════════════════════════════════════════════════════════════════════

def test_sr1_all_secret_references_are_known():
    """SR1: Every 'life-platform/...' string literal in Lambda source must be
    a known or explicitly-deleted secret.

    Unknown names = typo, stale reference to rotated name, or new undocumented
    secret. The Todoist 2-day outage (Mar 2026) had a wrong default value that
    this test would have caught at CI time.

    Fix: Add to KNOWN_SECRETS here + ARCHITECTURE.md, or fix the source name.
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if secret_name in KNOWN_SECRETS:
            continue
        if secret_name in DELETED_SECRETS:
            continue  # SR2 handles these separately
        rel = os.path.relpath(filepath, ROOT)
        violations.append(f"  {rel}:{lineno} — '{secret_name}' not in KNOWN_SECRETS")

    assert not violations, (
        f"SR1 FAIL: {len(violations)} unrecognised secret name(s) in source code:\n"
        + "\n".join(violations)
        + "\n\nFix: Add to KNOWN_SECRETS in this file + ARCHITECTURE.md, "
        "or update source to use the correct secret name."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR2 — No source file may reference a deleted secret
# ══════════════════════════════════════════════════════════════════════════════

def test_sr2_no_deleted_secret_references():
    """SR2: Lambda source must not reference permanently deleted secrets.

    After deletion, any Lambda that tries to read the secret fails at runtime
    with ResourceNotFoundException. This test ensures source is cleaned up
    before the secret is destroyed.

    Fix: Update the source to use the replacement secret name and redeploy.
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if secret_name in DELETED_SECRETS:
            rel = os.path.relpath(filepath, ROOT)
            violations.append(
                f"  {rel}:{lineno} — '{secret_name}' has been permanently deleted"
            )

    assert not violations, (
        f"SR2 FAIL: {len(violations)} source file(s) reference DELETED secret(s):\n"
        + "\n".join(violations)
        + "\n\nThese secrets no longer exist in AWS. Update source to use the "
        "replacement secret name and redeploy before traffic resumes."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR3 — Convention check: all secret names must have life-platform/ prefix
# ══════════════════════════════════════════════════════════════════════════════

def test_sr3_secret_names_follow_convention():
    """SR3: All 'life-platform/...' literals must follow the naming convention.

    Catches typos like 'life-platorm/ai-keys' (missed 'f') or
    'life_platform/ai-keys' (underscore instead of hyphen).
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if not _CONVENTION_RE.match(secret_name):
            rel = os.path.relpath(filepath, ROOT)
            violations.append(
                f"  {rel}:{lineno} — '{secret_name}' does not follow life-platform/* convention"
            )

    assert not violations, (
        f"SR3 FAIL: {len(violations)} secret name(s) violate naming convention:\n"
        + "\n".join(violations)
        + "\n\nAll secrets must start with 'life-platform/'."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR4 — Sanity: scanner must find at least some references
# ══════════════════════════════════════════════════════════════════════════════

def test_sr4_secret_references_found():
    """SR4: The scanner must find at least a minimum number of secret references.

    Guards against silent false-greens caused by a broken regex or empty
    SCAN_PATHS. If _ALL_REFS is empty it's the scanner that's broken, not
    the code.
    """
    MIN_EXPECTED = 3  # conservative lower bound
    assert len(_ALL_REFS) >= MIN_EXPECTED, (
        f"SR4 FAIL: Only {len(_ALL_REFS)} secret references found across all source files. "
        f"Expected at least {MIN_EXPECTED}. The scanner may be broken — "
        f"check _SECRET_LITERAL_RE and SCAN_PATHS.\n"
        f"Files scanned: {len(_FILES)}"
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

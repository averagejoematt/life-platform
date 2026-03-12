#!/usr/bin/env python3
"""
tests/test_cdk_s3_paths.py — CDK IAM S3 path vs Lambda write path linter.

Prevents the 2026-03-12 P0 class of bug where CDK IAM policy S3 resource path
diverged from the actual path the Lambda writes to.

Root cause: role_policies.py used the default raw/matthew/todoist/* prefix,
but todoist_lambda.py writes to raw/todoist/ (no matthew/ prefix). CDK
reconcile enforced this wrong IAM path, causing AccessDenied.

Strategy:
  - Convention: Lambdas write to raw/matthew/{source}/ and IAM allows raw/matthew/{source}/*
  - Exceptions are documented in ci/lambda_s3_paths.json
  - This test verifies:
    S1  Every _ingestion_base call in role_policies.py either uses the convention
        OR has an explicit s3_prefix that matches an entry in lambda_s3_paths.json
    S2  Every exception in lambda_s3_paths.json has evidence in the Lambda source
        (the Lambda actually writes to the declared prefix, not somewhere else)
    S3  No Lambda source writes to raw/matthew/{source}/ if it's declared as an
        exception (catches when Lambda gets refactored but manifest isn't updated)

Run:  python3 -m pytest tests/test_cdk_s3_paths.py -v
      python3 tests/test_cdk_s3_paths.py  (standalone)

v1.0.0 — 2026-03-12
"""

import json
import os
import re
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROLE_POLICIES_PATH = os.path.join(ROOT, "cdk", "stacks", "role_policies.py")
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")
MANIFEST_PATH = os.path.join(ROOT, "ci", "lambda_s3_paths.json")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _extract_ingestion_base_calls(src):
    """
    Extract all _ingestion_base(source_name, ...) calls from role_policies.py.
    Returns list of dicts: {source, s3_prefix_override, line}
    """
    results = []
    pattern = re.compile(
        r'_ingestion_base\s*\(\s*["\'](\w+)["\']'  # source name
        r'(.*?)\)',                                  # rest of args (lazy)
        re.DOTALL
    )
    for m in pattern.finditer(src):
        source = m.group(1)
        args_body = m.group(2)
        line = src[:m.start()].count('\n') + 1

        prefix_m = re.search(r's3_prefix\s*=\s*["\']([^"\']+)["\']', args_body)
        s3_prefix = prefix_m.group(1) if prefix_m else None

        results.append({"source": source, "s3_prefix": s3_prefix, "line": line})

    return results


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_s1_all_s3_prefixes_are_convention_or_documented():
    """S1: Every _ingestion_base call uses convention prefix OR is in the exception manifest."""
    manifest = _load_manifest()
    exceptions = manifest.get("exceptions", {})
    convention = manifest.get("convention", {})

    src = _read(ROLE_POLICIES_PATH)
    calls = _extract_ingestion_base_calls(src)

    failures = []
    convention_template = convention.get("default_iam_template", "raw/matthew/{source}/*")

    for call in calls:
        source = call["source"]
        s3_prefix = call["s3_prefix"]
        line = call["line"]

        if s3_prefix is None:
            # Using default convention — fine
            continue

        # Explicit prefix that matches convention exactly is redundant but not wrong
        expected_convention = convention_template.replace("{source}", source)
        if s3_prefix == expected_convention:
            continue

        # Has explicit non-convention override — must be in exceptions manifest
        if source not in exceptions:
            failures.append(
                f"role_policies.py:{line} — _ingestion_base('{source}') has s3_prefix='{s3_prefix}' "
                f"but '{source}' is not in ci/lambda_s3_paths.json exceptions.\n"
                f"    Add an entry to ci/lambda_s3_paths.json documenting why this deviates from convention."
            )
        else:
            expected_iam = exceptions[source].get("iam_prefix", "")
            if s3_prefix != expected_iam:
                failures.append(
                    f"role_policies.py:{line} — _ingestion_base('{source}') s3_prefix='{s3_prefix}' "
                    f"doesn't match manifest entry '{expected_iam}'.\n"
                    f"    Update either role_policies.py or ci/lambda_s3_paths.json."
                )

    assert not failures, (
        f"S1 FAIL: {len(failures)} undocumented S3 prefix deviation(s):\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_s2_exception_evidence_in_lambda_source():
    """S2: Every manifest exception must be verifiable in the Lambda source file."""
    manifest = _load_manifest()
    exceptions = manifest.get("exceptions", {})

    failures = []
    for source, entry in exceptions.items():
        lambda_file = entry.get("lambda_file", f"lambdas/{source}_lambda.py")
        expected_prefix = entry.get("expected_prefix", "")
        full_path = os.path.join(ROOT, lambda_file)

        if not os.path.exists(full_path):
            failures.append(
                f"Manifest exception '{source}' references lambda_file='{lambda_file}' "
                f"which doesn't exist. Update ci/lambda_s3_paths.json."
            )
            continue

        src = _read(full_path)
        prefix_to_find = expected_prefix.rstrip("/")
        if prefix_to_find not in src:
            failures.append(
                f"Manifest exception '{source}': expected to find '{prefix_to_find}' in "
                f"{lambda_file} but it's not there.\n"
                f"    Either the Lambda was refactored (update manifest) or the manifest is wrong."
            )

    assert not failures, (
        f"S2 FAIL: {len(failures)} manifest exception(s) can't be verified in Lambda source:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_s3_exceptions_dont_use_convention_prefix():
    """S3: If a source is in the exceptions manifest, its Lambda must NOT write to
    the convention prefix. Catches when Lambda gets refactored but manifest isn't updated."""
    manifest = _load_manifest()
    exceptions = manifest.get("exceptions", {})
    convention = manifest.get("convention", {})
    user_id = convention.get("user_id", "matthew")

    warnings = []
    for source, entry in exceptions.items():
        lambda_file = entry.get("lambda_file", f"lambdas/{source}_lambda.py")
        full_path = os.path.join(ROOT, lambda_file)
        if not os.path.exists(full_path):
            continue

        src = _read(full_path)
        convention_prefix = f"raw/{user_id}/{source}/"
        if convention_prefix in src:
            warnings.append(
                f"Exception '{source}' in manifest but Lambda source contains "
                f"convention prefix '{convention_prefix}'.\n"
                f"    If Lambda was updated to use convention, remove from ci/lambda_s3_paths.json."
            )

    # Soft fail — Lambda could legitimately write to both during a migration.
    if warnings:
        print("\n⚠️  S3 WARNINGS (non-blocking):")
        for w in warnings:
            print(f"  - {w}")


def test_s4_no_hardcoded_matthew_in_iam_comments():
    """S4: Canary for copy-paste errors — s3_prefix values with 'matthew' must
    match the convention pattern raw/matthew/{source}/*."""
    src = _read(ROLE_POLICIES_PATH)
    for m in re.finditer(r's3_prefix\s*=\s*["\']([^"\']*matthew[^"\']*)["\']', src):
        prefix = m.group(1)
        line = src[:m.start()].count('\n') + 1
        if not re.match(r'^raw/matthew/\w+/\*$', prefix):
            pytest.fail(
                f"role_policies.py:{line} — s3_prefix='{prefix}' contains 'matthew' but "
                f"doesn't match the convention pattern 'raw/matthew/{{source}}/*'.\n"
                f"    Correct format: 'raw/matthew/my_source/*'"
            )


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)

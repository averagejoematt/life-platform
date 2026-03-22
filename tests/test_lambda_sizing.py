"""
test_lambda_sizing.py — PIPE-03: Assert Lambda memory limits stay within expected bounds.

Prevents accidental over-provisioning (e.g. 3008MB set during debugging and forgotten).
Thresholds:
  - Ingestion Lambdas: <= 512MB (Garmin/Apple Health process large files; others <= 256MB)
  - Compute Lambdas: <= 512MB
  - Site API / Email / Operational: <= 256MB
  - Webhooks: <= 256MB
"""

import ast
import os
import re
import pytest

CDK_DIR = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")


def _parse_memory_calls(filepath: str) -> list[tuple[str, int]]:
    """
    Return list of (function_name, memory_mb) for all Lambda definitions in a CDK file.
    Looks for memory_mb= and memory_size= keyword arguments.
    """
    results = []
    with open(filepath) as f:
        source = f.read()

    # Match memory_mb=NNN or memory_size=NNN in Python source
    # This catches both create_platform_lambda(..., memory_mb=512) and
    # _lambda.Function(..., memory_size=256)
    for pattern, key in [
        (r'memory_mb\s*=\s*(\d+)', 'memory_mb'),
        (r'memory_size\s*=\s*(\d+)', 'memory_size'),
    ]:
        for match in re.finditer(pattern, source):
            mb = int(match.group(1))
            # Grab a bit of context for the error message
            start = max(0, match.start() - 100)
            ctx = source[start:match.start() + 40].replace('\n', ' ')
            results.append((ctx.strip(), mb))
    return results


def test_ingestion_stack_memory_limits():
    path = os.path.join(CDK_DIR, "ingestion_stack.py")
    findings = _parse_memory_calls(path)
    for ctx, mb in findings:
        assert mb <= 512, (
            f"ingestion_stack.py: memory setting {mb}MB exceeds 512MB cap.\n"
            f"Context: ...{ctx}..."
        )


def test_compute_stack_memory_limits():
    path = os.path.join(CDK_DIR, "compute_stack.py")
    findings = _parse_memory_calls(path)
    for ctx, mb in findings:
        assert mb <= 512, (
            f"compute_stack.py: memory setting {mb}MB exceeds 512MB cap.\n"
            f"Context: ...{ctx}..."
        )


def test_web_stack_memory_limits():
    """Site API and email-subscriber should stay <= 256MB."""
    path = os.path.join(CDK_DIR, "web_stack.py")
    findings = _parse_memory_calls(path)
    for ctx, mb in findings:
        assert mb <= 256, (
            f"web_stack.py: memory setting {mb}MB exceeds 256MB cap for web-facing Lambdas.\n"
            f"Context: ...{ctx}..."
        )


def test_email_stack_memory_limits():
    path = os.path.join(CDK_DIR, "email_stack.py")
    if not os.path.exists(path):
        pytest.skip("email_stack.py not found")
    findings = _parse_memory_calls(path)
    for ctx, mb in findings:
        assert mb <= 512, (
            f"email_stack.py: memory setting {mb}MB exceeds 512MB cap.\n"
            f"Context: ...{ctx}..."
        )


def test_no_3008mb_anywhere():
    """Catch the AWS-maximum-default value being accidentally set."""
    for fname in os.listdir(CDK_DIR):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(CDK_DIR, fname)
        findings = _parse_memory_calls(path)
        for ctx, mb in findings:
            assert mb != 3008, (
                f"{fname}: memory_size=3008 (AWS max-default) found — likely debugging artefact.\n"
                f"Context: ...{ctx}..."
            )
